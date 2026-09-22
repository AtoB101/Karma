"""操作台静态包的分发地基：清单生成、自校验、可复现。

操作台没有构建步骤，所以「发布」这件事的价值全在**可验证**上：
任何人都能拿这份清单去核对「我手上的操作台跟你发布的是不是同一份」。
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps" / "console"
MOD = ROOT / "scripts" / "console_bundle.py"
PUBLISH_SH = ROOT / "scripts" / "publish_console_ipfs.sh"

sys.path.insert(0, str(ROOT))

from scripts.console_bundle import BundleError, build, manifest_for, read_manifest, verify  # noqa: E402


def _build(tmp_path: Path, name: str = "console"):
    out = tmp_path / name
    manifest = build(CONSOLE, out, timestamp="2026-01-01T00:00:00Z")
    return out, manifest


def test_build_copies_a_faithful_bundle(tmp_path):
    out, manifest = _build(tmp_path)
    assert manifest["schema"] == "karma.console.dist/v1"
    assert manifest["file_count"] == len(manifest["files"]) > 0
    assert manifest["total_bytes"] == sum(f["bytes"] for f in manifest["files"])
    assert (out / "pages" / "cyber" / "index.html").is_file()
    assert (out / "scripts" / "karma-nodes.js").is_file()
    # 清单落在静态包旁边，发布脚本才找得到。
    assert (tmp_path / "console-dist.json").is_file()
    assert verify(out, manifest) == []


def test_build_is_reproducible_for_the_same_input(tmp_path):
    _, first = _build(tmp_path, "a")
    _, second = _build(tmp_path, "b")
    assert first["root_sha256"] == second["root_sha256"]
    assert first["files"] == second["files"]


def test_build_is_deterministic_regardless_of_timestamp(tmp_path):
    _, first = _build(tmp_path, "a")
    src = CONSOLE
    out = tmp_path / "c"
    second = build(src, out, timestamp="2030-12-31T23:59:59Z")
    assert first["root_sha256"] == second["root_sha256"]


def test_manifest_lists_files_sorted_and_free_of_junk(tmp_path):
    out, manifest = _build(tmp_path)
    paths = [f["path"] for f in manifest["files"]]
    assert paths == sorted(paths), "清单必须按路径排序，否则摘要不可复现"
    for bad in (".map", ".log", ".orig", ".rej", ".bak"):
        assert not [p for p in paths if p.endswith(bad)], f"静态包里混进了 {bad}"
    assert not [p for p in paths if "__pycache__" in p or "node_modules" in p]


def test_manifest_covers_the_whole_console_directory(tmp_path):
    _, manifest = _build(tmp_path)
    listed = {f["path"] for f in manifest["files"]}
    on_disk = {
        p.relative_to(CONSOLE).as_posix()
        for p in CONSOLE.rglob("*")
        if p.is_file() and ".git" not in p.parts
    }
    assert listed == on_disk, f"清单与磁盘不一致：{sorted(listed ^ on_disk)[:5]}"


def test_verify_reports_a_missing_file(tmp_path):
    out, manifest = _build(tmp_path)
    (out / "scripts" / "karma-nodes.js").unlink()
    problems = verify(out, manifest)
    assert any("缺少文件" in p and "karma-nodes.js" in p for p in problems), problems


def test_verify_reports_an_extra_file(tmp_path):
    out, manifest = _build(tmp_path)
    (out / "rogue.js").write_text("// not in the manifest\n", encoding="utf-8")
    problems = verify(out, manifest)
    assert any("多出文件" in p and "rogue.js" in p for p in problems), problems


def test_verify_catches_a_tampered_file(tmp_path):
    out, manifest = _build(tmp_path)
    target = out / "scripts" / "karma-nodes.js"
    target.write_text(target.read_text(encoding="utf-8") + "\n// tampered\n", encoding="utf-8")
    problems = verify(out, manifest)
    assert any("内容不一致" in p and "karma-nodes.js" in p for p in problems), problems


def test_verify_catches_a_doctored_manifest(tmp_path):
    """逐个文件都对得上、但总摘要被改过 —— 也必须拦下来。"""
    out, manifest = _build(tmp_path)
    path = tmp_path / "console-dist.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    data["root_sha256"] = "0" * 64
    path.write_text(json.dumps(data), encoding="utf-8")
    problems = verify(out, read_manifest(path))
    assert any("总摘要" in p for p in problems), problems


def test_read_manifest_rejects_unknown_schema(tmp_path):
    path = tmp_path / "console-dist.json"
    path.write_text(json.dumps({"schema": "something.else/v9", "files": []}), encoding="utf-8")
    with pytest.raises(BundleError):
        read_manifest(path)


def test_build_refuses_a_directory_that_is_not_the_console(tmp_path):
    bare = tmp_path / "not-console"
    bare.mkdir()
    with pytest.raises(BundleError):
        build(bare, tmp_path / "out")


def test_publisher_script_wires_build_verify_and_ipfs(tmp_path):
    text = PUBLISH_SH.read_text(encoding="utf-8")
    assert "console_bundle.py build" in text
    assert "console_bundle.py verify" in text, "发布前必须自校验"
    assert "console_bundle.py stamp" in text
    assert "ipfs add -r --cid-version 1" in text
    assert "dnslink=" in text
    assert "set -euo pipefail" in text
    # 没有 ipfs 时必须给出一条能照做的指令，而不是静默失败。
    assert "没找到 ipfs CLI" in text


def test_publisher_script_has_no_crlf():
    """LF 结尾：CRLF 的 shebang 在服务器上跑不起来。"""
    assert b"\r\n" not in PUBLISH_SH.read_bytes()


def test_module_cli_build_and_verify_round_trip(tmp_path):
    out = tmp_path / "console"
    # Windows 的控制台默认编码不是 UTF-8：显式指定，否则中文输出会把 subprocess 的
    # 读取线程整个炸掉（stdout 变成 None），断言就看不到真正的原因。
    env = {"PYTHONIOENCODING": "utf-8"}

    def run(*args):
        return subprocess.run(
            [sys.executable, str(MOD), *args],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
            env=env, timeout=120,
        )

    built = run("build", "--src", str(CONSOLE), "--out", str(out), "--timestamp", "2026-01-01T00:00:00Z")
    assert built.returncode == 0, built.stdout + built.stderr
    checked = run("verify", "--dir", str(out))
    assert checked.returncode == 0, checked.stdout + checked.stderr

    (out / "rules.json").write_text("{}", encoding="utf-8")
    broken = run("verify", "--dir", str(out))
    assert broken.returncode == 1
    assert "多出文件" in broken.stdout


def test_manifest_matches_a_fresh_walk_of_the_console():
    fresh = manifest_for(CONSOLE)
    assert fresh["root_sha256"]
    assert fresh["file_count"] > 0
