from karma_openclaw.helpers import apply_openclaw_dev_delivery_signatures


def test_apply_dev_signatures_fills_missing():
    body = apply_openclaw_dev_delivery_signatures({"task_id": "t1"})
    assert body["signature"] == "0xopenclaw_execution_receipt_dev"
    assert body["seller_signature"] == "0xopenclaw_progress_dev"


def test_apply_dev_signatures_preserves_existing():
    body = apply_openclaw_dev_delivery_signatures(
        {"signature": "0xabc", "seller_signature": "0xdef"}
    )
    assert body["signature"] == "0xabc"
    assert body["seller_signature"] == "0xdef"
