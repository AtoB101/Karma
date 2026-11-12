"""操作台静态资源的引用要真的落到文件 —— 少/多算一层 ``../`` 就会线上 404。

真机背景：``.globe-fallback`` 的背景纹理写成 ``url("../../assets/earth-texture.jpg")``。
样式表自己在 /console/styles/，往上**两**级 = 站点根，浏览器就一直去要
``/assets/earth-texture.jpg``（线上 404），那 1.39 MB 的纹理从来没加载过；文件其实在
``/console/assets/``，只该往上**一**级。

这类错本地用 file:// 打开看不出来（基准不一样），只有按线上 /console/ 前缀发出去才暴露 ——
所以要在本地按线上口径解析一遍。本文件钉住：

* 仓库当前操作台的每一条引用（页面 src/href + CSS url() + 已加载脚本的路径字面量）
  都能解析到存在的文件；
* 逃出 /console/ 前缀（往上多算一级）与指向不存在文件（404）都会被抓出来；
* 工具自己的夹具自检能过（保证「抓错能力」没退化）。
"""
from __future__ import annotations

from pathlib import Path

from scripts import check_console_assets as links

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"


def test_repo_console_references_all_resolve():
    issues, checked = links.scan(CONSOLE)
    assert checked > 30, f"解析到的引用太少（{checked} 条）：解析逻辑是不是坏了"
    assert not issues, "这些引用落不到文件：\n" + "\n".join(
        f"  [{i.where}] {i.raw} -> {i.url} ({i.reason})" for i in issues
    )


def _fixture(tmp_path: Path) -> Path:
    """一个最小的操作台：一条页面引用 + 一条 CSS url()，都指向同一个存在的纹理。"""
    (tmp_path / "assets").mkdir()
    (tmp_path / "styles").mkdir()
    (tmp_path / "pages" / "cyber").mkdir(parents=True)
    (tmp_path / "assets" / "tex.jpg").write_bytes(b"x")
    (tmp_path / "styles" / "console.css").write_text(
        '.g { background-image: url("../assets/tex.jpg"); }\n', encoding="utf-8"
    )
    (tmp_path / "pages" / "cyber" / "index.html").write_text(
        '<link href="../../styles/console.css" rel="stylesheet">\n'
        '<img src="../../assets/tex.jpg">\n',
        encoding="utf-8",
    )
    return tmp_path


def test_healthy_fixture_has_no_issues(tmp_path):
    assert links.scan(_fixture(tmp_path))[0] == []


def test_miscounted_parent_is_caught(tmp_path):
    """往上多算一级：/console/styles/ + ../../assets/ -> /assets/（逃出 /console/ 前缀）。"""
    root = _fixture(tmp_path)
    (root / "styles" / "console.css").write_text(
        '.g { background-image: url("../../assets/tex.jpg"); }\n', encoding="utf-8"
    )
    issues, _ = links.scan(root)
    assert [i.url for i in issues] == ["/assets/tex.jpg"]
    assert "逃出" in issues[0].reason


def test_missing_file_is_caught(tmp_path):
    root = _fixture(tmp_path)
    (root / "pages" / "cyber" / "index.html").write_text(
        '<img src="../../assets/nope.png">\n', encoding="utf-8"
    )
    issues, _ = links.scan(root)
    assert [i.url for i in issues] == ["/console/assets/nope.png"]
    assert "404" in issues[0].reason


def test_tool_selftest_passes(capsys):
    assert links._selftest() == 0
    assert "自检通过" in capsys.readouterr().out