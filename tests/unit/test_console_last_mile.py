"""Console: the public web surface is the Cyber Console (apps/console/pages/cyber/)."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONSOLE = ROOT / "apps/console"
CYBER = CONSOLE / "pages/cyber/index.html"

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
