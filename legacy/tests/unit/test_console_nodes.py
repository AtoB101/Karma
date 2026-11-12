"""操作台节点层：去中心化的接入面（选节点 / 探活 / 容灾 / 自定义节点）。

这一层要解决的问题只有一个：操作台是纯静态页面，谁都能拿一份跑起来，
但「跟哪台节点说话」必须由用户自己选、自己换 —— 而不是写死在代码里。

静态检查之外，真正跑一遍 karma-nodes.js 的行为（tests/js/test_karma_nodes.cjs）。
"""
import re
import shutil
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
SCRIPTS = CONSOLE / "scripts"
CYBER_HTML = CONSOLE / "pages/cyber/index.html"
NODES_JS = SCRIPTS / "karma-nodes.js"
PANEL_JS = SCRIPTS / "cyber-node-panel.js"
API_JS = SCRIPTS / "karma-public-api.js"
BOOT_JS = SCRIPTS / "cyber-console.js"
PACK_DIR = SCRIPTS / "i18n-phrase"
RUNNER = ROOT / "tests" / "js" / "test_karma_nodes.cjs"
SHIPPED_LANGS = ("en", "ja", "ko", "es-AR", "es-SV")

CJK = re.compile(r"[\u4e00-\u9fff]")
JS_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"')
PACK_ENTRY = re.compile(r'^\s*"((?:[^"\\]|\\.)*)"\s*:', re.M)


def _chinese_literals(path: Path) -> set:
    out = set()
    for m in JS_STRING.finditer(path.read_text(encoding="utf-8")):
        if CJK.search(m.group(1)):
            out.add(m.group(1))
    return out


def _pack_keys(lang: str) -> set:
    text = (PACK_DIR / f"{lang}.js").read_text(encoding="utf-8")
    return set(PACK_ENTRY.findall(text))


def test_node_layer_ships_and_is_wired_before_the_api_client():
    assert NODES_JS.is_file(), "missing scripts/karma-nodes.js"
    assert PANEL_JS.is_file(), "missing scripts/cyber-node-panel.js"
    html = CYBER_HTML.read_text(encoding="utf-8")
    assert "karma-nodes.js" in html
    assert "cyber-node-panel.js" in html
    assert 'id="node-chip"' in html
    assert 'id="node-menu"' in html
    assert "data-karma-nodes-settings" in html
    # 顺序有实际意义：节点层要先就位，首个请求才会打到用户选的那台。
    # 带 scripts/ 前缀才只匹配 <script src>，不会撞上正文里提到文件名的注释。
    assert html.index("scripts/karma-nodes.js") < html.index("scripts/karma-public-api.js")
    assert html.index("scripts/karma-nodes.js") < html.index("scripts/cyber-console.js")


def test_api_client_and_console_bootstrap_defer_to_the_node_layer():
    api = API_JS.read_text(encoding="utf-8")
    assert "KarmaNodes.effectiveBase" in api, "API client ignores the selected node"
    assert "KarmaNodes.reportFailure" in api, "network failures never trigger failover"
    boot = BOOT_JS.read_text(encoding="utf-8")
    assert "KarmaNodes.effectiveBase" in boot, "console bootstrap ignores the selected node"


def test_hand_typed_api_base_is_never_silently_replaced():
    """「连接设置」里手填的地址必须赢过缓存的 node id —— 否则会被甩到别的机器上。"""
    src = NODES_JS.read_text(encoding="utf-8")
    assert "function legacyNode" in src
    assert "legacy:" in src
    assert "byId && normalizeForCompare(byId.base) === want" in src


def test_single_source_of_truth_for_the_active_endpoint():
    src = NODES_JS.read_text(encoding="utf-8")
    # 仍然只写老的那个键：其它脚本不用改口径，老用户设置也不失效。
    assert 'LS_BASE = "karma_cyber_api_base"' in src
    assert "KARMA_API_BASE = trimBase(node.base)" in src


def test_every_chinese_literal_in_the_node_layer_is_translated_in_all_packs():
    """节点层的中文文案必须 5 份语言包全覆盖 —— 少一条，那个语言的页面就留一块中文。"""
    literals = _chinese_literals(NODES_JS) | _chinese_literals(PANEL_JS)
    assert literals, "expected the node layer to carry Chinese UI copy"
    for lang in SHIPPED_LANGS:
        keys = _pack_keys(lang)
        missing = sorted(s for s in literals if not any(s == k or s in k for k in keys))
        assert not missing, f"{lang} phrase pack misses: {missing}"


def test_chip_label_in_the_page_is_translated():
    html = CYBER_HTML.read_text(encoding="utf-8")
    assert 'class="node-chip-key">节点<' in html
    for lang in SHIPPED_LANGS:
        assert "节点" in _pack_keys(lang), f"{lang} cannot translate the node chip"


def test_phrase_packs_stay_the_same_size():
    sizes = {lang: len(_pack_keys(lang)) for lang in SHIPPED_LANGS}
    assert len(set(sizes.values())) == 1, f"phrase packs drifted apart: {sizes}"


def test_node_layer_behaviour_suite():
    node = shutil.which("node")
    if not node:
        return
    proc = subprocess.run([node, str(RUNNER)], capture_output=True, text=True, timeout=180)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "checks passed" in proc.stdout
