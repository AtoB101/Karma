# -*- coding: utf-8 -*-
"""操作台静态资源的版本串 —— 「部署即换 URL」，旧代码进不到用户的页面。

为什么要有这个
--------------
操作台页面引用的是一批**文件名固定**的静态资源：

    <script src="../../scripts/cyber-authorize.js"></script>

浏览器按 URL 缓存。文件名不变，部署上去的新代码就可能长时间进不到用户手里 ——
真机踩过一次，代价不小：某个标签页里跑的还是部署前的旧向导（那次改动之前，
向导发的是 ``agent_binding: ""``），而服务端已经按新口径把这条硬拦成 400。
用户照着 1→4 填完、钱包也签了，点「生成」只看到一句英文报错，
看起来像新功能坏了。页面里的引用虽然是 no-cache（能重新校验），
但只要用户没重新加载页面，跑在内存里的仍旧是旧脚本。

做法：给每个本地 ``<script src>`` / ``<link href>`` 挂 ``?v=<内容摘要前 12 位>``。
**内容变了 URL 就变**，浏览器没有任何机会复用旧的那份；页面本身是 no-cache，
于是「页面 → 脚本」两级拿到的一定是同一版。i18n 的语言包同理：
i18n-cyber.js 会把自己 URL 上的 v 带给 ``i18n-phrase/<lang>.js``。

    python scripts/stamp_console_assets.py            # 就地写回
    python scripts/stamp_console_assets.py --check    # 只检查；有落后就退出码 1

摘要按 LF 归一化后再算（与 scripts/console_bundle.py 一致）：Windows 检出是 CRLF、
Linux 是 LF，不归一化的话同一份源码在两个平台会算出两个版本号，跨平台对不上账。

改完脚本/样式要重跑一次本脚本（门禁里有 ``--check``，忘了会红）。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

DEFAULT_ROOT = "apps/console"

#: 会被浏览器按 URL 缓存、改了就该重新取的文件才挂版本串。
STAMP_SUFFIXES = {".js", ".css"}
#: 不是本地资源的引用，一律别碰。
SKIP_PREFIXES = (
    "http://",
    "https://",
    "//",
    "data:",
    "#",
    "mailto:",
    "javascript:",
    "blob:",
    "tel:",
)
REF = re.compile(r'(\b(?:src|href)=")([^"]+)(")')


def _canonical(data: bytes) -> bytes:
    """按 LF 归一化后算摘要 —— 跨平台可比（见模块 docstring）。"""
    return data.replace(b"\r\n", b"\n")


def asset_version(path: Path) -> str:
    """内容摘要前 12 位。内容变了它必变，这就是版本号的来源。"""
    return hashlib.sha256(_canonical(path.read_bytes())).hexdigest()[:12]


def _split_tail(ref: str):
    """拆出「纯路径」和「查询串/锚点」。"""
    for i, ch in enumerate(ref):
        if ch in "?#":
            return ref[:i], ref[i:]
    return ref, ""


def _strip_version(tail: str) -> str:
    """把已有的 ``v=`` 抠掉，其余查询串与锚点照旧保留（重打要幂等）。"""
    if not tail:
        return ""
    if tail.startswith("#"):
        return tail
    body, frag = tail[1:], ""
    if "#" in body:
        body, frag = body.split("#", 1)
        frag = "#" + frag
    params = [p for p in body.split("&") if p and not p.startswith("v=")]
    return ("?" + "&".join(params) if params else "") + frag


def stamp_reference(ref: str, base_dir: Path, root: Path):
    """按需给一条引用挂版本串。返回 ``(新引用, 判定)``，判定用于报错时说清原因。"""
    if not ref.strip() or ref.startswith(SKIP_PREFIXES):
        return ref, "skip"
    raw, tail = _split_tail(ref)
    target = (base_dir / raw).resolve()
    if target.suffix.lower() not in STAMP_SUFFIXES:
        return ref, "skip"
    try:
        target.relative_to(root.resolve())
    except ValueError:
        # 指到操作台目录外面去了：不碰它（顺手也挡住 ../ 逃逸）。
        return ref, "skip"
    if not target.is_file():
        # 引用了一个不存在的文件：保持原样，让页面自己的 404 曝出来。
        return raw + tail, "missing"
    return "%s?v=%s%s" % (raw, asset_version(target), _strip_version(tail)), "stamped"


def stamp_html(path: Path, root: Path):
    """重打一个页面的引用。返回 ``(新文本, [(旧引用, 新引用), ...])``。"""
    text = path.read_bytes().decode("utf-8")
    changed = []

    def repl(m):
        new, why = stamp_reference(m.group(2), path.parent, root)
        if why == "stamped" and new != m.group(2):
            changed.append((m.group(2), new))
        return m.group(1) + new + m.group(3)

    return REF.sub(repl, text), changed


def html_files(root: Path):
    return sorted(p for p in root.rglob("*.html") if p.is_file())


def stamp(root: Path, write: bool):
    """重打整个操作台。返回 ``[(页面, [(旧, 新), ...]), ...]``；空 = 已经是最新。"""
    root = Path(root)
    pending = []
    for html in html_files(root):
        text, changed = stamp_html(html, root)
        if not changed:
            continue
        pending.append((html, changed))
        if write:
            # 按字节写回：只换我们改过的那几处，行尾保持检出时的原样。
            html.write_bytes(text.encode("utf-8"))
    return pending


def check(root: Path):
    """只检查。返回问题清单（空 = 一致）—— 门禁与单测都看它。"""
    problems = []
    for html, changed in stamp(root, write=False):
        rel = html.as_posix()
        for old, new in changed:
            problems.append("%s: %s -> %s" % (rel, old, new))
    return problems


def main(argv=None):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="给操作台的 script/style 引用挂内容版本串")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="操作台静态目录（默认 apps/console）")
    ap.add_argument("--check", action="store_true", help="只检查，不写回；有落后就退出码 1")
    args = ap.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print("找不到操作台目录：%s" % root, file=sys.stderr)
        return 2

    if args.check:
        problems = check(root)
        if problems:
            print("有 %d 条引用的版本串过期（跑 python scripts/stamp_console_assets.py 重打）：" % len(problems))
            for p in problems:
                print("  " + p)
            return 1
        print("操作台静态资源版本串：已是最新")
        return 0

    pending = stamp(root, write=True)
    if not pending:
        print("操作台静态资源版本串：已是最新，无需改动")
        return 0
    total = sum(len(c) for _h, c in pending)
    print("已重打 %d 条引用（%d 个页面）" % (total, len(pending)))
    for html, changed in pending:
        print("  %s：%d 条" % (html.as_posix(), len(changed)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
