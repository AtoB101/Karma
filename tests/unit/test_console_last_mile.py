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
        "lockCapacity",
    ):
        assert name in text, f"missing cyberKarmaApi helper {name}"


def test_console_actions_binds_data_attribute():
    text = ACTIONS_JS.read_text(encoding="utf-8")
    assert "data-console-action" in text
    assert "settlement-submit" in text


def test_payments_page_wires_live_buttons():
    html = (ROOT / "apps/console/pages/payments/index.html").read_text(encoding="utf-8")
    assert 'data-console-action="capacity-lock"' in html
    assert "console-actions.js" in html
