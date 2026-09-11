"""Console: the public web surface is the Cyber Console (apps/console/pages/cyber/)."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
CYBER = CONSOLE / "pages/cyber/index.html"
I18N = CONSOLE / "scripts/i18n-cyber.js"
CONSOLE_JS = CONSOLE / "scripts/cyber-console.js"

LEGACY_PAGES = (
    "pages/dashboard.html",
    "pages/mvvs-dashboard.html",
    "pages/bilateral-status.html",
    "pages/openclaw-connect.html",
    "pages/security-funds.html",
    "pages/verifier-explorer.html",
    "pages/agents/index.html",
    "pages/disputes/index.html",
    "pages/evidence/index.html",
    "pages/payments/index.html",
    "pages/receiving/index.html",
    "pages/settings/index.html",
    "pages/trade/index.html",
)


def test_karma_public_api_exports_write_helpers():
    text = (CONSOLE / "scripts/karma-public-api.js").read_text(encoding="utf-8")
    for name in (
        "settlementLock",
        "settlementBuyerAccept",
        "settlementDispute",
        "createPaymentCode",
        "launchTradeOrder",
        "tradeLaunchSigningPreview",
        "lockCapacity",
    ):
        assert name in text, f"missing karmaPublicApi helper {name}"


def test_karma_public_api_resolves_same_origin_base():
    text = (CONSOLE / "scripts/karma-public-api.js").read_text(encoding="utf-8")
    assert "karmaResolveApiBase" in text
    # an explicitly empty base must survive as "" (same origin), not fall back to localhost
    assert 'raw === undefined || raw === null' in text


def test_legacy_console_pages_are_gone():
    for rel in LEGACY_PAGES:
        assert not (CONSOLE / rel).exists(), f"legacy console page still present: {rel}"


def test_cyber_console_is_the_only_ui():
    html = CYBER.read_text(encoding="utf-8")
    assert "../../styles/cyber-console.css" in html
    assert "../../scripts/karma-public-api.js" in html
    for gone in ("console-actions.js", "console-bootstrap.js", "console-trade.js", "dashboard.js"):
        assert gone not in html, f"cyber console still loads removed script: {gone}"


def test_index_redirects_to_cyber_console():
    html = (CONSOLE / "index.html").read_text(encoding="utf-8")
    assert "pages/cyber/index.html" in html


def _shipped_langs():
    """Languages i18n-cyber.js is willing to advertise in the picker."""
    match = re.search(r"SHIPPED_LANGS\s*=\s*\[([^\]]*)\]", I18N.read_text(encoding="utf-8"))
    assert match, "i18n-cyber.js must declare SHIPPED_LANGS"
    return re.findall(r'"([^"]+)"', match.group(1))


def test_language_picker_lists_exactly_the_shipped_langs():
    """A language may only be offered when its pack renders the whole page.

    ja/ko/es/fr/de/pt-BR keep partial packs (32 of 224 keys), so older builds
    listed them while the page stayed English. The HTML fallback and the runtime
    list must agree, otherwise the drift comes back.
    """
    html = CYBER.read_text(encoding="utf-8")
    select = re.search(r'<select id="cyberLang".*?</select>', html, re.S)
    assert select, "the console lost its language picker"
    options = re.findall(r'<option value="([^"]+)"', select.group(0))
    assert options == _shipped_langs()


def test_language_picker_labels_come_from_the_pack_registry():
    text = I18N.read_text(encoding="utf-8")
    block = re.search(r"const LANG_LABELS\s*=\s*\{(.*?)\n  \};", text, re.S)
    assert block, "i18n-cyber.js must declare LANG_LABELS"
    for code in _shipped_langs():
        key = re.escape(code)
        assert re.search(r'(?:"%s"|%s)\s*:' % (key, key), block.group(1)), f"missing label for {code}"
    js = CONSOLE_JS.read_text(encoding="utf-8")
    assert "SHIPPED_LANGS" in js, "the picker must read SHIPPED_LANGS, not a local copy"
    assert "LANG_LABELS" in js, "the picker must read LANG_LABELS, not a local copy"
