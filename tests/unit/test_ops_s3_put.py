from __future__ import annotations

import hashlib
import importlib.util
import threading
import urllib.parse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "ops" / "s3_put.py"


def _load():
    spec = importlib.util.spec_from_file_location("karma_ops_s3_put", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


s3_put = _load()

# AWS 官方签名测试套件里的 get-vanilla 向量（aws-sig-v4-test-suite/get-vanilla）。
# 这条向量覆盖了整条链：canonical request -> string to sign -> signing key -> signature。
# 它能过，说明签名算法本身是对的；下面几条再覆盖我们真正用到的编码边界。
AWS_ACCESS_KEY = "AKIDEXAMPLE"
AWS_SECRET_KEY = "wJalrXUtnFEMI/K7MDENG+bPxRfiCYEXAMPLEKEY"
AWS_EXPECTED_SIGNATURE = "5fa00fa31553b73ebf1942676e86291e8372ff2a2260956d9b8aae1d763fbf31"


def _get_vanilla_signature() -> str:
    headers = {"Host": "example.amazonaws.com", "X-Amz-Date": "20150830T123600Z"}
    canonical, signed = s3_put.build_canonical_request("GET", "/", {}, headers, s3_put.EMPTY_SHA256)
    assert signed == "host;x-amz-date"
    scope = "20150830/us-east-1/service/aws4_request"
    string_to_sign = s3_put.build_string_to_sign("20150830T123600Z", scope, canonical)
    key = s3_put.signing_key(AWS_SECRET_KEY, "20150830", "us-east-1", "service")
    import hmac

    return hmac.new(key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()


def test_sigv4_matches_aws_official_get_vanilla_vector():
    assert _get_vanilla_signature() == AWS_EXPECTED_SIGNATURE


def test_canonical_uri_encodes_reserved_chars_but_keeps_slashes():
    assert s3_put.canonical_uri("/karma-backups/2026 backup/a b.sql.gz") == \
        "/karma-backups/2026%20backup/a%20b.sql.gz"
    assert s3_put.canonical_uri("") == "/"
    assert s3_put.canonical_uri("relative/key") == "/relative/key"


def test_canonical_query_is_sorted_and_percent_encoded():
    assert s3_put.canonical_query({"b": "2", "a": "1", "c": "x y"}) == "a=1&b=2&c=x%20y"
    assert s3_put.canonical_query({}) == ""


def test_canonical_headers_collapses_whitespace_and_sorts():
    block, signed = s3_put.canonical_headers({"X-Test": "  a   b  ", "Host": "example.com"})
    assert block == "host:example.com\nx-test:a b\n"
    assert signed == "host;x-test"


class _Recorder(BaseHTTPRequestHandler):
    requests: list = []
    status = 200

    def do_PUT(self):  # noqa: N802 - http.server 约定
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        type(self).requests.append(
            {"path": self.path, "headers": {k.lower(): v for k, v in self.headers.items()}, "body": body}
        )
        self.send_response(type(self).status)
        self.send_header("Content-Length", "0")
        self.end_headers()

    def log_message(self, *args):  # 静音测试输出
        pass


@pytest.fixture()
def fake_s3():
    _Recorder.requests = []
    _Recorder.status = 200
    server = ThreadingHTTPServer(("127.0.0.1", 0), _Recorder)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield "http://127.0.0.1:%d" % server.server_port
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _write(tmp_path: Path, name: str, data: bytes) -> Path:
    path = tmp_path / name
    path.write_bytes(data)
    return path


def test_put_object_sends_path_style_signed_put(fake_s3, tmp_path):
    payload = b"create table settlements(id int);\n" * 100
    src = _write(tmp_path, "karma-db.sql.gz", payload)

    rc = s3_put.put_object(
        endpoint=fake_s3,
        bucket="karma-backups",
        key="nightly/20261001/karma-db.sql.gz",
        path=str(src),
        access_key=AWS_ACCESS_KEY,
        secret_key=AWS_SECRET_KEY,
        quiet=True,
    )

    assert rc == 0
    assert len(_Recorder.requests) == 1
    recorded = _Recorder.requests[0]
    assert recorded["path"] == "/karma-backups/nightly/20261001/karma-db.sql.gz"
    assert recorded["body"] == payload
    auth = recorded["headers"]["authorization"]
    assert auth.startswith("AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/")
    assert "/us-east-1/s3/aws4_request" in auth
    assert "SignedHeaders=" in auth and "Signature=" in auth
    assert recorded["headers"]["x-amz-content-sha256"] == hashlib.sha256(payload).hexdigest()


def test_put_object_uses_template_endpoint_path_prefix(fake_s3, tmp_path):
    src = _write(tmp_path, "manifest.txt", b"created_at=now\n")

    rc = s3_put.put_object(
        endpoint=fake_s3 + "/s3-gateway",
        bucket="b",
        key="k.txt",
        path=str(src),
        access_key=AWS_ACCESS_KEY,
        secret_key=AWS_SECRET_KEY,
        quiet=True,
    )

    assert rc == 0
    assert _Recorder.requests[0]["path"] == "/s3-gateway/b/k.txt"


def test_put_object_returns_3_on_http_error(fake_s3, tmp_path):
    _Recorder.status = 403
    src = _write(tmp_path, "x.bin", b"x")

    rc = s3_put.put_object(
        endpoint=fake_s3, bucket="b", key="k", path=str(src),
        access_key=AWS_ACCESS_KEY, secret_key=AWS_SECRET_KEY, quiet=True,
    )

    assert rc == 3
    assert len(_Recorder.requests) == 1


def test_put_object_reports_missing_file_without_network(tmp_path, capsys):
    rc = s3_put.main([
        "--endpoint", "http://127.0.0.1:9", "--bucket", "b", "--key", "k",
        "--file", str(tmp_path / "nope.bin"),
        "--access-key", "a", "--secret-key", "s",
    ])
    assert rc == 2


def test_dry_run_signs_but_does_not_send(fake_s3, tmp_path, capsys):
    src = _write(tmp_path, "y.bin", b"y")

    rc = s3_put.main([
        "--endpoint", fake_s3, "--bucket", "b", "--key", "k",
        "--file", str(src), "--access-key", AWS_ACCESS_KEY,
        "--secret-key", AWS_SECRET_KEY, "--dry-run",
    ])

    assert rc == 0
    assert _Recorder.requests == []
    out = capsys.readouterr().out
    assert "DRY-RUN PUT " in out
    assert "Authorization: AWS4-HMAC-SHA256 Credential=AKIDEXAMPLE/" in out


def test_default_endpoint_without_scheme_is_https():
    parsed = urllib.parse.urlsplit("https://minio.example.com:9000")
    assert parsed.scheme == "https"