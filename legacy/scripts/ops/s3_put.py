#!/usr/bin/env python3
"""Minimal S3-compatible PUT uploader -- stdlib only, AWS Signature V4.

为什么不用 aws / mc / rclone：生产服务器上一个都没装，而离站备份不该依赖「再装一个
客户端」。这段代码只做一件事——往 S3 兼容端点 PUT 一个文件——所以它小到可以整个读
一遍。签名部分有单测（tests/unit/test_ops_s3_put.py 用 AWS 官方测试向量），不是
「看起来对」的代码。

用法:
  s3_put.py --endpoint https://s3.example.com --bucket B --key K --file F \\
            --access-key A --secret-key S [--region us-east-1] [--style path|virtual-hosted] \\
            [--dry-run] [--quiet]
  s3_put.py --get --endpoint https://s3.example.com --bucket B --key K --out F \\
            --access-key A --secret-key S [--region us-east-1] [--style path|virtual-hosted]

退出码: 0 成功 / 2 参数错 / 3 传输或鉴权失败。
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import hmac
import os
import sys
import urllib.error
import urllib.parse
import urllib.request

ALGO = "AWS4-HMAC-SHA256"
SERVICE = "s3"
EMPTY_SHA256 = hashlib.sha256(b"").hexdigest()


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def canonical_uri(path: str) -> str:
    """S3 canonical URI: 逐段 URI-encode，'/' 保留，不做路径归一化。"""
    if not path:
        path = "/"
    if not path.startswith("/"):
        path = "/" + path
    return urllib.parse.quote(path, safe="/~")


def canonical_query(params: dict[str, str]) -> str:
    if not params:
        return ""
    items = sorted((k, v) for k, v in params.items())
    return "&".join(
        "%s=%s" % (urllib.parse.quote(str(k), safe="-_.~"),
                   urllib.parse.quote(str(v), safe="-_.~"))
        for k, v in items
    )


def canonical_headers(headers: dict[str, str]) -> tuple[str, str]:
    """返回 (canonical_headers_block, signed_headers)。值要 trim + 折叠内部空白。"""
    norm = {}
    for k, v in headers.items():
        nk = k.strip().lower()
        nv = " ".join(str(v).split())
        norm[nk] = nv
    names = sorted(norm)
    block = "".join("%s:%s\n" % (n, norm[n]) for n in names)
    return block, ";".join(names)


def build_canonical_request(method: str, path: str, query: dict[str, str],
                            headers: dict[str, str], payload_hash: str) -> tuple[str, str]:
    ch, signed = canonical_headers(headers)
    cr = "\n".join([
        method.upper(),
        canonical_uri(path),
        canonical_query(query),
        ch,
        signed,
        payload_hash,
    ])
    return cr, signed


def signing_key(secret: str, date_stamp: str, region: str, service: str = SERVICE) -> bytes:
    k = ("AWS4" + secret).encode("utf-8")
    k = hmac_sha256(k, date_stamp)
    k = hmac_sha256(k, region)
    k = hmac_sha256(k, service)
    return hmac_sha256(k, "aws4_request")


def build_string_to_sign(amz_date: str, scope: str, canonical_request: str) -> str:
    return "\n".join([
        ALGO,
        amz_date,
        scope,
        sha256_hex(canonical_request.encode("utf-8")),
    ])


def sign_request(method: str, path: str, query: dict[str, str], headers: dict[str, str],
                 payload: bytes, access_key: str, secret_key: str, region: str,
                 amz_date: str, service: str = SERVICE) -> tuple[str, dict[str, str]]:
    """返回 (Authorization 头值, 实际用于签名的完整 headers)。"""
    payload_hash = sha256_hex(payload)
    hdrs = dict(headers)
    hdrs["host"] = hdrs.get("host", "")
    hdrs["x-amz-date"] = amz_date
    hdrs["x-amz-content-sha256"] = payload_hash

    cr, signed = build_canonical_request(method, path, query, hdrs, payload_hash)
    date_stamp = amz_date[:8]
    scope = "%s/%s/%s/aws4_request" % (date_stamp, region, service)
    sts = build_string_to_sign(amz_date, scope, cr)
    sig = hmac.new(signing_key(secret_key, date_stamp, region, service),
                   sts.encode("utf-8"), hashlib.sha256).hexdigest()
    auth = "%s Credential=%s/%s, SignedHeaders=%s, Signature=%s" % (
        ALGO, access_key, scope, signed, sig)
    return auth, hdrs


def http_date(now: _dt.datetime | None = None) -> str:
    now = now or _dt.datetime.now(_dt.timezone.utc)
    return now.strftime("%a, %d %b %Y %H:%M:%S GMT")


def build_target(endpoint: str, bucket: str, key: str, style: str = "path") -> tuple[str, str, str]:
    """返回 (url, object_path, host_header)。object_path / host_header 参与签名。"""
    ep = endpoint.strip()
    if "://" not in ep:
        ep = "https://" + ep
    parsed = urllib.parse.urlsplit(ep)
    base_path = parsed.path.rstrip("/")
    hostname = parsed.hostname or ""
    port = parsed.port
    default_port = (parsed.scheme == "https" and port == 443) or (
        parsed.scheme == "http" and port == 80
    )

    if style == "virtual-hosted":
        # 阿里云 OSS 对二级域名桶强制 virtual-hosted style（path style 会 403
        # SecondLevelDomainForbidden）。bucket 名必须是合法 DNS 名。
        vhost = "%s.%s" % (bucket, hostname)
        if port is None or default_port:
            host_header = vhost
            netloc = vhost
        else:
            host_header = "%s:%s" % (vhost, port)
            netloc = host_header
        object_path = "%s/%s" % (base_path, key.lstrip("/"))
    else:
        if parsed.scheme == "https" and port in (None, 443):
            host_header = hostname
        elif parsed.scheme == "http" and port in (None, 80):
            host_header = hostname
        else:
            host_header = parsed.netloc
        netloc = parsed.netloc
        object_path = "%s/%s/%s" % (base_path, bucket, key.lstrip("/"))

    url = "%s://%s%s" % (parsed.scheme, netloc, object_path)
    return url, object_path, host_header


def put_object(endpoint: str, bucket: str, key: str, path: str, access_key: str,
               secret_key: str, region: str = "us-east-1", dry_run: bool = False,
               quiet: bool = False, timeout: int = 300, style: str = "path") -> int:
    with open(path, "rb") as fh:
        payload = fh.read()

    url, object_path, host_header = build_target(endpoint, bucket, key, style)

    now = _dt.datetime.now(_dt.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    headers = {
        "host": host_header,
        "content-type": "application/octet-stream",
        "content-length": str(len(payload)),
        "date": http_date(now),
    }
    auth, signed_headers = sign_request(
        "PUT", object_path, {}, headers, payload,
        access_key, secret_key, region, amz_date)

    if dry_run:
        print("DRY-RUN PUT %s" % url)
        print("Authorization: %s" % auth)
        print("payload_sha256: %s" % sha256_hex(payload))
        print("bytes: %d" % len(payload))
        return 0

    req = urllib.request.Request(url, data=payload, method="PUT")
    for k, v in signed_headers.items():
        req.add_header(k, v)
    req.add_header("Authorization", auth)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            if not quiet:
                print("PUT %s -> %d (%d bytes)" % (url, resp.status, len(payload)))
            return 0
    except urllib.error.HTTPError as exc:
        body = exc.read()[:2000].decode("utf-8", "replace")
        sys.stderr.write("PUT %s failed: HTTP %s\n%s\n" % (url, exc.code, body))
        return 3
    except Exception as exc:  # noqa: BLE001 - 传输层任何异常都算上传失败
        sys.stderr.write("PUT %s failed: %s: %s\n" % (url, type(exc).__name__, exc))
        return 3


def get_object(endpoint: str, bucket: str, key: str, out_path: str, access_key: str,
               secret_key: str, region: str = "us-east-1", quiet: bool = False,
               timeout: int = 300, style: str = "path") -> int:
    """从 S3 兼容端点 GET 一个对象并落盘到 out_path（F6 离站恢复演练用）。"""
    url, object_path, host_header = build_target(endpoint, bucket, key, style)

    now = _dt.datetime.now(_dt.timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    headers = {
        "host": host_header,
        "date": http_date(now),
    }
    auth, signed_headers = sign_request(
        "GET", object_path, {}, headers, b"",
        access_key, secret_key, region, amz_date)

    req = urllib.request.Request(url, method="GET")
    for k, v in signed_headers.items():
        req.add_header(k, v)
    req.add_header("Authorization", auth)

    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = resp.read()
            with open(out_path, "wb") as fh:
                fh.write(data)
            if not quiet:
                print("GET %s -> %d (%d bytes)" % (url, resp.status, len(data)))
            return 0
    except urllib.error.HTTPError as exc:
        body = exc.read()[:2000].decode("utf-8", "replace")
        sys.stderr.write("GET %s failed: HTTP %s\n%s\n" % (url, exc.code, body))
        return 3
    except Exception as exc:  # noqa: BLE001 - 传输层任何异常都算下载失败
        sys.stderr.write("GET %s failed: %s: %s\n" % (url, type(exc).__name__, exc))
        return 3


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="PUT/GET a file to/from an S3-compatible endpoint")
    ap.add_argument("--endpoint", required=True)
    ap.add_argument("--bucket", required=True)
    ap.add_argument("--key", required=True)
    ap.add_argument("--file", required=False)
    ap.add_argument("--get", action="store_true")
    ap.add_argument("--out")
    ap.add_argument("--access-key", required=True)
    ap.add_argument("--secret-key", required=True)
    ap.add_argument("--region", default=os.environ.get("KARMA_BACKUP_S3_REGION", "us-east-1"))
    ap.add_argument("--style", default=os.environ.get("KARMA_BACKUP_S3_STYLE", "path"),
                    choices=("path", "virtual-hosted"))
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--quiet", action="store_true")
    args = ap.parse_args(argv)

    if args.get:
        if not args.out:
            sys.stderr.write("--get requires --out\n")
            return 2
        return get_object(args.endpoint, args.bucket, args.key, args.out,
                          args.access_key, args.secret_key, args.region,
                          quiet=args.quiet, style=args.style)

    if not args.file:
        sys.stderr.write("missing --file (PUT), or use --get --out\n")
        return 2
    if not os.path.isfile(args.file):
        sys.stderr.write("no such file: %s\n" % args.file)
        return 2
    return put_object(args.endpoint, args.bucket, args.key, args.file,
                      args.access_key, args.secret_key, args.region,
                      dry_run=args.dry_run, quiet=args.quiet, style=args.style)


if __name__ == "__main__":
    sys.exit(main())
