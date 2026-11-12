"""Console last-mile: ensure public API client exports settlement + trade helpers."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
API_JS = ROOT / "apps/console/scripts/karma-public-api.js"
ACTIONS_JS = ROOT / "apps/console/scripts/console-actions.js"


def test_karma_public_api_exports_write_helpers():
    text = API_JS.read_text(encoding="utf-8")
    for name in (
        "settlementLock",
        "settlementBuyerAccept",
        "settlementDispute",
        "createPaymentCode",
        "launchTradeOrder",
        "tradeLaunchSigningPreview",
        "lockCapacity",
    ):
        assert name in text, f"missing cyberKarmaApi helper {name}"


def test_console_trade_uses_eip712_typed_data_v4():
    trade_js = (ROOT / "apps/console/scripts/console-trade.js").read_text(encoding="utf-8")
    assert "eth_signTypedData_v4" in trade_js
    assert "tradeLaunchSigningPreview" in trade_js or "signing-preview" in trade_js
    assert "0xtrade_console" not in trade_js or "resolveBuyerSignature" in trade_js


def test_console_actions_binds_data_attribute():
    text = ACTIONS_JS.read_text(encoding="utf-8")
    assert "data-console-action" in text
    assert "settlement-submit" in text


def test_payments_page_wires_live_buttons():
    html = (ROOT / "apps/console/pages/payments/index.html").read_text(encoding="utf-8")
    assert 'data-console-action="capacity-lock"' in html
    assert "console-actions.js" in html
    assert "agent-service-guard" not in html


def test_overview_has_no_dead_guard_or_website_links():
    html = (ROOT / "apps/console/index.html").read_text(encoding="utf-8")
    assert "agent-service-guard" not in html
    assert "../website/index.html" not in html
