"""身份 · 认证 页面的静态接线门禁。

为什么要有这个文件：线上实测抓到过一个「点『建立子身份』毫无反应」的 bug ——
按钮绑上了监听器，但函数体是空的，页面不报错、控制台干净，用户只会以为坏了。
下面这几条就是冲着这类静默失效去的：
  1. 页面上被绑定的每个 id 都必须真实存在；
  2. 每个监听器都要真的绑上；
  3. 监听器不能是空函数体；
  4. 「建立子身份」必须真的调到 createSub()。
"""

from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps" / "console"
PAGE = CONSOLE / "pages" / "cyber" / "index.html"
IDENTITY_JS = CONSOLE / "scripts" / "cyber-identity-verify.js"

# 身份页上「人点了 / 选了就必须有反应」的控件。
CLICK_IDS = [
    "idv-face-open",
    "idv-face-shot",
    "idv-submit",
    "idv-reset",
    "idsub-new",
    "idsub-cancel",
    "idsub-wallet",
    "idsub-face",
    "idsub-create",
]
CHANGE_IDS = ["idv-doc-front", "idv-doc-back", "idv-face-file"]
WIRED_IDS = CLICK_IDS + CHANGE_IDS

# 只匹配「内联函数」形式的绑定；裸函数名（如 , createSub)）由第 4 条测试兜底。
BINDING = re.compile(
    r'byId\("([a-z0-9-]+)"\)\.addEventListener\("(click|change)",\s*(?:async\s+)?function\s*\([^)]*\)\s*\{'
)
EMPTY_BODY = re.compile(r"\s*\}")


def _page_html() -> str:
    return PAGE.read_text(encoding="utf-8")


def _identity_js() -> str:
    return IDENTITY_JS.read_text(encoding="utf-8")


def test_identity_page_script_is_loaded():
    assert "cyber-identity-verify.js" in _page_html(), "身份页必须加载 cyber-identity-verify.js"


def test_every_wired_id_exists_on_the_page():
    html = _page_html()
    missing = [i for i in WIRED_IDS if f'id="{i}"' not in html]
    assert not missing, f"脚本绑了这些 id，但页面上没有：{missing}"


def test_every_wired_id_has_a_listener():
    js = _identity_js()
    bound = {m.group(1) for m in BINDING.finditer(js)}
    bound |= set(re.findall(r'byId\("([a-z0-9-]+)"\)\.addEventListener\("(?:click|change)",\s*[A-Za-z_$]', js))
    missing = [i for i in WIRED_IDS if i not in bound]
    assert not missing, f"这些控件没有绑定事件：{missing}"


def test_no_listener_is_an_empty_function():
    """空函数体 = 点了没反应，而且不报错 —— 必须当门禁一样挡住。"""
    js = _identity_js()
    for match in BINDING.finditer(js):
        ident = match.group(1)
        after = js[match.end(): match.end() + 400]
        assert not EMPTY_BODY.match(after), (
            f"{ident} 的事件处理是空函数体（点了没反应且不报错）"
        )


def test_the_create_button_actually_calls_create_sub():
    js = _identity_js()
    idx = js.index('byId("idsub-create").addEventListener("click"')
    assert "createSub()" in js[idx: idx + 200], "『建立子身份』必须真的调用 createSub()"