"""操作台静态包的构建 / 清单 / 校验 —— 去中心化分发的第一块地基。

操作台是一个纯静态目录（apps/console），没有服务端渲染，也没有构建产物。
这带来一个很好的性质：**任何人拿到同一份文件，都应该算出同一个摘要。**
「我手上这份操作台跟你发布的那份是不是同一份」因此变成一件可验证的事 ——
这也是把它放到 IPFS / 任意镜像站上之后，还能被人复核的前提。

三件事，各自独立：

    build   复制一份干净的静态包，逐文件算 sha256，写出 console-dist.json
    verify  拿一个现有目录跟清单对账：少文件 / 多文件 / 内容被改，都能指出来
    stamp   把发布结果（CID / 域名 / 网关）写回清单

清单是确定性的：文件按路径排序，root_sha256 = 各文件摘要按固定格式串起来的 sha256。
改一个字节，root_sha256 必变；只改生成时间，则不变。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

SCHEMA = "karma.console.dist/v1"
DEFAULT_SRC = "apps/console"
DEFAULT_MANIFEST_NAME = "console-dist.json"

# 不该进静态包的东西：版本控制的杂物、编辑器备份、日志、sourcemap。
IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".cache"}
IGNORE_FILES = {".DS_Store", "Thumbs.db", "desktop.ini"}
IGNORE_SUFFIXES = (".map", ".log", ".pyc", ".pyo", ".orig", ".rej", ".bak", "~")


class BundleError(RuntimeError):
    """清单/校验层面的错误，消息直接给用户看。"""


def _is_ignored(rel: Path) -> bool:
    name = rel.name
    if name in IGNORE_FILES:
        return True
    if any(name.endswith(s) for s in IGNORE_SUFFIXES):
        return True
    return any(part in IGNORE_DIRS for part in rel.parts)


def iter_files(root: Path):
    """按路径排序产出静态包里的文件（相对路径 + 绝对路径）。"""
    out = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if _is_ignored(rel):
            continue
        out.append((rel.as_posix(), path))
    out.sort(key=lambda pair: pair[0])
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def root_digest(entries) -> str:
    """总摘要：把 (path, sha256) 按固定格式串起来再哈希。

    故意把「每个文件的单独摘要」也留在清单里 —— 对不上账时要能一眼看出是哪个文件。
    """
    h = hashlib.sha256()
    for entry in entries:
        h.update(f"{entry['sha256']}  {entry['path']}\n".encode("utf-8"))
    return h.hexdigest()


def manifest_for(root: Path) -> dict:
    entries = []
    total = 0
    for rel, path in iter_files(root):
        digest = _sha256(path)
        size = path.stat().st_size
        entries.append({"path": rel, "sha256": digest, "bytes": size})
        total += size
    return {
        "files": entries,
        "file_count": len(entries),
        "total_bytes": total,
        "root_sha256": root_digest(entries),
    }


def build(src: Path, out: Path, timestamp: str | None = None) -> dict:
    """把 src 复制成一个干净静态包，写回清单，返回清单内容。"""
    if not (src / "pages" / "cyber" / "index.html").is_file():
        raise BundleError(f"{src} 看起来不是操作台目录（缺少 pages/cyber/index.html）")
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    for rel, path in iter_files(src):
        target = out / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)
    manifest = {
        "schema": SCHEMA,
        "generated_at": timestamp or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "src": src.as_posix(),
        "ipfs": {"cid": None, "dnslink": None, "gateway": None, "pinned_by": None},
    }
    manifest.update(manifest_for(out))
    write_manifest(out.parent / DEFAULT_MANIFEST_NAME, manifest)
    return manifest


def write_manifest(path: Path, manifest: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False, sort_keys=False) + "\n", encoding="utf-8")


def read_manifest(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise BundleError(f"找不到清单 {path}") from None
    except json.JSONDecodeError as exc:
        raise BundleError(f"清单不是合法 JSON：{exc}") from None
    if data.get("schema") != SCHEMA:
        raise BundleError(f"清单 schema 不认识：{data.get('schema')!r}")
    if not isinstance(data.get("files"), list):
        raise BundleError("清单缺少 files 列表")
    return data


def verify(root: Path, manifest: dict) -> list:
    """对账。返回问题列表；空列表 = 一致。"""
    problems = []
    want = {e["path"]: e for e in manifest["files"]}
    have = {}
    for rel, path in iter_files(root):
        have[rel] = path
    missing = sorted(set(want) - set(have))
    extra = sorted(set(have) - set(want))
    for rel in missing:
        problems.append(f"缺少文件：{rel}")
    for rel in extra:
        problems.append(f"多出文件：{rel}")
    entries = []
    for rel in sorted(set(want) & set(have)):
        path = have[rel]
        digest = _sha256(path)
        size = path.stat().st_size
        if digest != want[rel]["sha256"]:
            problems.append(f"内容不一致：{rel}（清单 {want[rel]['sha256'][:12]}… / 实际 {digest[:12]}…）")
        elif size != want[rel]["bytes"]:
            problems.append(f"大小不一致：{rel}（清单 {want[rel]['bytes']} / 实际 {size}）")
        entries.append({"path": rel, "sha256": digest, "bytes": size})
    if not problems and root_digest(entries) != manifest["root_sha256"]:
        problems.append("总摘要对不上：逐个文件都对，但 root_sha256 不一致（清单可能被改过）")
    return problems


def stamp(manifest_path: Path, cid: str | None, domain: str | None, gateway: str | None, pinned_by: str | None) -> dict:
    manifest = read_manifest(manifest_path)
    ipfs = manifest.setdefault("ipfs", {})
    if cid:
        ipfs["cid"] = cid
    if domain and cid:
        ipfs["dnslink"] = f"_dnslink.{domain}"
        ipfs["gateway"] = gateway or f"https://{domain}"
    elif gateway:
        ipfs["gateway"] = gateway
    if pinned_by:
        ipfs["pinned_by"] = pinned_by
    write_manifest(manifest_path, manifest)
    return manifest


def _cmd_build(args) -> int:
    manifest = build(Path(args.src), Path(args.out), timestamp=args.timestamp)
    print(f"OK  {manifest['file_count']} 个文件，{manifest['total_bytes']} 字节")
    print(f"    root_sha256 = {manifest['root_sha256']}")
    print(f"    清单写到 {Path(args.out).parent / DEFAULT_MANIFEST_NAME}")
    return 0


def _cmd_verify(args) -> int:
    manifest = read_manifest(Path(args.manifest))
    problems = verify(Path(args.dir), manifest)
    for line in problems:
        print(f"FAIL  {line}")
    if problems:
        print(f"校验失败：{len(problems)} 处不一致")
        return 1
    print(f"OK  {manifest['file_count']} 个文件与清单一致（root_sha256 {manifest['root_sha256'][:16]}…）")
    return 0


def _cmd_stamp(args) -> int:
    manifest = stamp(Path(args.manifest), args.cid, args.domain, args.gateway, args.pinned_by)
    ipfs = manifest.get("ipfs") or {}
    print(f"OK  cid={ipfs.get('cid')} dnslink={ipfs.get('dnslink')}")
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(prog="console_bundle", description="操作台静态包的构建 / 校验")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_build = sub.add_parser("build", help="复制一份干净静态包并写出清单")
    p_build.add_argument("--src", default=DEFAULT_SRC)
    p_build.add_argument("--out", default="dist/console")
    p_build.add_argument("--timestamp", default=None, help="固定生成时间（可复现构建）")
    p_build.set_defaults(func=_cmd_build)

    p_verify = sub.add_parser("verify", help="拿目录跟清单对账")
    p_verify.add_argument("--dir", default="dist/console")
    p_verify.add_argument("--manifest", default=None, help="默认取 <dir> 旁边的 console-dist.json")
    p_verify.set_defaults(func=_cmd_verify)

    p_stamp = sub.add_parser("stamp", help="把发布结果写回清单")
    p_stamp.add_argument("--manifest", default=f"dist/{DEFAULT_MANIFEST_NAME}")
    p_stamp.add_argument("--cid", default=None)
    p_stamp.add_argument("--domain", default=None)
    p_stamp.add_argument("--gateway", default=None)
    p_stamp.add_argument("--pinned-by", dest="pinned_by", default=None)
    p_stamp.set_defaults(func=_cmd_stamp)

    args = parser.parse_args(argv)
    if args.cmd == "verify" and args.manifest is None:
        args.manifest = str(Path(args.dir).resolve().parent / DEFAULT_MANIFEST_NAME)
    try:
        return args.func(args)
    except BundleError as exc:
        print(f"FAIL  {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
