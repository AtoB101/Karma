"""操作台静态资源的内容版本串：部署上去了，用户手里那份就得跟着换。

真机背景：某次改动之后，用户在操作台点「生成」只拿到服务端的 400 —— 他页面上跑的
还是部署前的旧脚本（旧向导发 ``agent_binding: ""``），而服务端已经按新口径硬拦。
文件名固定 + 浏览器缓存，新代码就进不去用户的标签页。

改法：页面里的 ``<script src>`` / ``<link href>`` 一律挂 ``?v=<内容摘要前 12 位>``
（scripts/stamp_console_assets.py）。本文件钉住两件事：

* 页面上每一条本地 js/css 引用都带着版本串，而且跟文件当前内容对得上；
* 内容一变版本必变 —— 不然「挂上了」也只是个装饰，拦不住旧代码。
"""
from __future__ import annotations

import re
from pathlib import Path

from scripts import stamp_console_assets as stamp

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
CYBER = CONSOLE / "pages" / "cyber" / "index.html"

REF = re.compile(r'(?:src|href)="([^"]+\.(?:js|css))(?:\?([^"]*))?"')
VERSION = re.compile(r"(?:^|&)v=([0-9a-f]{12})(?:&|$)")


def _asset_refs(html: Path):
    """页面里的 js/css 引用：[(引用原文, 路径, 查询串)]。"""
    out = []
    for m in REF.finditer(html.read_text(encoding="utf-8")):
        out.append((m.group(0), m.group(1), m.group(2) or ""))
    return out


def test_every_local_asset_reference_is_versioned():
    refs = _asset_refs(CYBER)
    assert len(refs) > 20, "操作台的脚本引用不该这么少（页面结构变了？）"
    for raw, ref, query in refs:
        m = VERSION.search(query)
        assert m, f"这条引用没挂内容版本串：{raw}"
        target = (CYBER.parent / ref).resolve()
        assert target.is_file(), f"引用指向不存在的文件：{ref}"
        assert m.group(1) == stamp.asset_version(target), f"版本串跟文件内容对不上：{raw}"


def test_the_repo_stamps_are_current():
    problems = stamp.check(CONSOLE)
    assert not problems, (
        "版本串过期（跑 python scripts/stamp_console_assets.py 重打）：\n" + "\n".join(problems)
    )


def test_changing_an_asset_changes_its_version(tmp_path):
    """内容一动，版本串必须跟着动。"""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "pages" / "cyber").mkdir(parents=True)
    js = tmp_path / "scripts" / "a.js"
    js.write_text("var a = 1;\n", encoding="utf-8")
    page = tmp_path / "pages" / "cyber" / "index.html"
    page.write_text('<html><script src="../../scripts/a.js"></script></html>', encoding="utf-8")

    assert stamp.check(tmp_path), "没挂版本串就该报出来"
    stamp.stamp(tmp_path, write=True)
    assert stamp.check(tmp_path) == []
    first = page.read_text(encoding="utf-8")

    js.write_text("var a = 2;\n", encoding="utf-8")
    problems = stamp.check(tmp_path)
    assert problems and "a.js" in problems[0], "改了内容版本串却没变"

    stamp.stamp(tmp_path, write=True)
    assert stamp.check(tmp_path) == []
    assert page.read_text(encoding="utf-8") != first


def test_external_and_page_references_are_left_alone(tmp_path):
    """外链、页面互链、锚点不挂版本串 —— 挂了反而是麻烦。"""
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts" / "x.js").write_text("var x = 1;\n", encoding="utf-8")
    keep = (
        "https://cdn.example.com/lib.js",
        "//cdn.example.com/lib.js",
        "../../scripts/next.html",
        "#top",
        "data:text/javascript,void%200",
    )
    for ref in keep:
        new, why = stamp.stamp_reference(ref, tmp_path, tmp_path)
        assert new == ref, f"{ref} 不该被改（判定 {why}）"
