# -*- coding: utf-8 -*-
"""操作台静态资源的「引用到底能不能落到文件」—— 部署前把 404 拦在本地。

为什么要有这个
--------------
操作台是一个纯静态目录（apps/console），线上按 /console/ 前缀原样发出去：

    /console                            -> apps/console/pages/cyber/index.html  （短入口，vhost 注入 <base>）
    /console/                           -> 同上
    /console/pages/cyber/index.html     -> apps/console/pages/cyber/index.html
    /console/**                         -> apps/console/**

页面里的相对引用（<script src>、<link href>、CSS 的 url()、脚本里的路径字面量）会不会
404，取决于**它自己的 URL 落在哪一层**。少算或多算一层 ``../`` 就一路指到别处，线上安静地
404 —— 而本地直接双击打开文件时看不出来（file:// 与 http:// 的基准不一样），要真按线上
前缀发出去才暴露。

真机踩过一次：``.globe-fallback`` 的背景纹理写成 ``url("../../assets/earth-texture.jpg")``。
样式表自己位于 /console/styles/，往上**两**级 = 站点根，浏览器就一直去要
``/assets/earth-texture.jpg``（线上 404），那 1.39 MB 的纹理从来没加载过；文件其实在
``/console/assets/``，只该往上**一**级（``../assets/...``）。

做法
----
把每一个引用按它真实的线上 URL 口径解析回仓库文件，逐个确认存在：

    python scripts/check_console_assets.py             # 默认 --check：有问题退出码 1
    python scripts/check_console_assets.py --selftest  # 用临时夹具自证能抓到 ``../../`` 这类错

解析口径（与 nginx vhost、console_last_mile_gate.sh 的注释一致）：

  * 页面（含短入口 /console 与长路径 /console/pages/cyber/index.html）的文档基准都是
    /console/<页面所在目录>/ —— 短入口由 vhost 注入 <base href>，等价于页面自己那一层；
  * CSS 的 url() 相对**样式表自己**（/console/styles/<name>.css 的所在目录）；
  * 脚本里的路径字面量相对**加载它的页面**的文档基准；
  * 只查真的被某个页面用 <script src> 加载过的脚本（没人加载的脚本里的路径指不到浏览器）。

不是本地资源的引用（http(s)://、//、data:、#、mailto:、javascript:、blob:、tel:）与
指向 /console/ 之外的**绝对**路径（如同源 API 的 /v1/...）一律跳过 —— 那些不是静态文件。
"""
from __future__ import annotations

import argparse
import posixpath
import re
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ROOT = "apps/console"
URL_PREFIX = "/console/"

#: 不是本地静态资源的引用，一律不解析。
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

PAGE_REF = re.compile(r'(?:src|href)="([^"]+)"')
SRC_REF = re.compile(r'src="([^"]+)"')
CSS_URL = re.compile(r"""url\(\s*["']?([^)"']+)["']?\s*\)""")
#: 脚本里的路径字面量：要么 ``./`` / ``../`` 开头，要么 assets|scripts|styles/ 开头。
JS_REF = re.compile(
    r"""["']((?:\.\.?/)+[A-Za-z0-9_.-]+(?:/[A-Za-z0-9_.-]+)*"""
    r"""|(?:assets|scripts|styles)/[A-Za-z0-9_.-]+\.[A-Za-z0-9]+)"""
    r"""(?:\?[^"']*)?["']"""
)


@dataclass(frozen=True)
class Issue:
    """一条会 404（或逃出 /console/ 前缀）的引用。"""

    where: str  # 人话定位（文件:行 或 文件 url()）
    raw: str  # 引用原文（去掉查询串/锚点）
    url: str  # 解析后的线上 URL
    reason: str  # "404：..." / "逃出 /console/ 前缀"


def _strip(raw: str) -> str:
    """去掉查询串与锚点，只留路径。"""
    for i, ch in enumerate(raw):
        if ch in "?#":
            return raw[:i]
    return raw


def _is_local(ref: str) -> bool:
    return bool(ref) and not ref.startswith(SKIP_PREFIXES)


def _resolve(base_url: str, ref: str) -> str:
    """把一条相对引用解析成线上 URL（posix 口径）。"""
    if ref.startswith("/"):
        return posixpath.normpath(ref)
    return posixpath.normpath(base_url.rstrip("/") + "/" + ref)


def _page_base(rel_dir: str) -> str:
    """页面文档基准：/console/<页面所在目录>/。"""
    return posixpath.normpath(URL_PREFIX + rel_dir + "/") + "/"


def _file_for(root: Path, url: str):
    """线上 URL -> 仓库文件；不在 /console/ 前缀下返回 None。"""
    if not url.startswith(URL_PREFIX):
        return None
    return root / url[len(URL_PREFIX):]


def _judge(root: Path, issues: list, where: str, ref: str, url: str) -> None:
    path = _file_for(root, url)
    if path is None:
        issues.append(Issue(where, ref, url, "逃出 %s 前缀" % URL_PREFIX))
    elif not path.is_file():
        issues.append(Issue(where, ref, url, "404：%s 不存在" % path.relative_to(root).as_posix()))


def _script_load_bases(root: Path, pages) -> dict:
    """脚本相对路径 -> 加载它的页面的文档基准集合。"""
    out: dict = {}
    for page in pages:
        rel = page.relative_to(root).as_posix()
        base = _page_base(posixpath.dirname(rel))
        for m in SRC_REF.finditer(page.read_text(encoding="utf-8")):
            ref = _strip(m.group(1))
            if not _is_local(ref):
                continue
            url = _resolve(base, ref)
            if not url.startswith(URL_PREFIX):
                continue
            target = root / url[len(URL_PREFIX):]
            if target.is_file() and target.suffix == ".js":
                out.setdefault(target.relative_to(root).as_posix(), set()).add(base)
    return out


def scan(root):
    """扫一遍操作台。返回 ``(issues, checked)``。"""
    root = Path(root)
    issues: list = []
    checked = 0

    pages = sorted(p for p in root.rglob("*.html") if p.is_file())
    styles = sorted(p for p in root.rglob("*.css") if p.is_file())
    scripts = sorted(p for p in root.rglob("*.js") if p.is_file())

    # 页面 src/href
    for page in pages:
        rel = page.relative_to(root).as_posix()
        base = _page_base(posixpath.dirname(rel))
        for lineno, line in enumerate(page.read_text(encoding="utf-8").splitlines(), 1):
            for m in PAGE_REF.finditer(line):
                ref = _strip(m.group(1))
                if not _is_local(ref):
                    continue
                checked += 1
                _judge(root, issues, "%s:%d" % (rel, lineno), ref, _resolve(base, ref))

    # CSS url()（相对样式表自己）
    for css in styles:
        rel = css.relative_to(root).as_posix()
        base = posixpath.dirname(URL_PREFIX + rel)
        for lineno, line in enumerate(css.read_text(encoding="utf-8").splitlines(), 1):
            for m in CSS_URL.finditer(line):
                ref = _strip(m.group(1).strip())
                if not _is_local(ref):
                    continue
                checked += 1
                _judge(root, issues, "%s:%d url()" % (rel, lineno), ref, _resolve(base, ref))

    # 脚本里的路径字面量（只查真的被页面加载的脚本）
    loads = _script_load_bases(root, pages)
    for js in scripts:
        rel = js.relative_to(root).as_posix()
        bases = loads.get(rel)
        if not bases:
            continue
        ordered = sorted(bases)
        seen: set = set()
        for lineno, line in enumerate(js.read_text(encoding="utf-8").splitlines(), 1):
            for m in JS_REF.finditer(line):
                ref = _strip(m.group(1))
                if not _is_local(ref) or (lineno, ref) in seen:
                    continue
                seen.add((lineno, ref))
                checked += 1
                if any(_file_for(root, _resolve(b, ref)) is not None
                       and _file_for(root, _resolve(b, ref)).is_file() for b in ordered):
                    continue
                _judge(root, issues, "%s:%d" % (rel, lineno), ref, _resolve(ordered[0], ref))

    return issues, checked


def _selftest() -> int:
    """在一个临时操作台里放好引用与坏引用，确认恰好抓到坏的那几条。"""
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "assets").mkdir()
        (root / "styles").mkdir()
        (root / "scripts").mkdir()
        (root / "pages" / "cyber").mkdir(parents=True)
        (root / "assets" / "tex.jpg").write_bytes(b"x")
        (root / "scripts" / "a.js").write_text(
            'var t = "../../assets/tex.jpg";\n', encoding="utf-8"
        )
        (root / "styles" / "good.css").write_text(
            '.g { background-image: url("../assets/tex.jpg"); }\n', encoding="utf-8"
        )
        # 就是线上那颗降落球踩过的错法：往上多了**一**级。
        (root / "styles" / "bad.css").write_text(
            '.b { background-image: url("../../assets/tex.jpg"); }\n', encoding="utf-8"
        )
        (root / "pages" / "cyber" / "index.html").write_text(
            '<link href="../../styles/good.css" rel="stylesheet">\n'
            '<script src="../../scripts/a.js"></script>\n'
            '<img src="../../assets/tex.jpg">\n',
            encoding="utf-8",
        )
        (root / "pages" / "cyber" / "broken.html").write_text(
            '<img src="../../assets/missing.png">\n', encoding="utf-8"
        )

        issues, checked = scan(root)
        urls = {i.url for i in issues}
        reasons = {i.url: i.reason for i in issues}
        want_escape, want_404 = "/assets/tex.jpg", "/console/assets/missing.png"

        problems = []
        if checked < 6:
            problems.append("只解析到 %d 条引用，太少（解析逻辑坏了？）" % checked)
        if want_escape not in urls:
            problems.append("没抓到逃出 /console/ 的引用 %s" % want_escape)
        elif "逃出" not in reasons[want_escape]:
            problems.append("%s 的分类不对：%s" % (want_escape, reasons[want_escape]))
        if want_404 not in urls:
            problems.append("没抓到 404 引用 %s" % want_404)
        extra = sorted(urls - {want_escape, want_404})
        if extra:
            problems.append("把好引用误报成问题：%s" % extra)
        if len(issues) != 2:
            problems.append("应恰好 2 条问题，实得 %d" % len(issues))

        if problems:
            print("自检失败：")
            for p in problems:
                print("  - " + p)
            return 1
        print("自检通过：恰抓到 2 条坏引用（逃出前缀 1 + 404 1），好引用无误报")
        return 0


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
    ap = argparse.ArgumentParser(description="操作台静态资源引用审计（引用能不能落到文件）")
    ap.add_argument("--root", default=DEFAULT_ROOT, help="操作台静态目录（默认 apps/console）")
    ap.add_argument("--check", action="store_true", help="只检查（默认行为），有问题退出码 1")
    ap.add_argument("--selftest", action="store_true", help="用临时夹具自证能抓到错误引用")
    args = ap.parse_args(argv)

    if args.selftest:
        return _selftest()

    root = Path(args.root)
    if not root.is_dir():
        print("找不到操作台目录：%s" % root, file=sys.stderr)
        return 2

    issues, checked = scan(root)
    print("=== 操作台静态资源引用审计 ===")
    print("  解析并检查的引用：%d 条" % checked)
    if not issues:
        print("  结果：全部命中文件（0 问题）")
        return 0
    print("  结果：%d 条引用落不到文件：" % len(issues))
    for it in issues:
        print("    - [%s] %s  ->  %s  (%s)" % (it.where, it.raw, it.url, it.reason))
    return 1


if __name__ == "__main__":
    raise SystemExit(main())