"""Phase 1 MCP helpers."""

from __future__ import annotations

from karma_openclaw.phase1_tools import build_payment_code_request


def test_build_payment_code_request_hashes():
    body = build_payment_code_request(
        buyer_identity_id="b1",
        seller_identity_id="s1",
        amount=15.0,
        task_type="api.caption",
        task_description="caption test",
        payment_mode="preauth",
    )
    assert body["buyer_identity_id"] == "b1"
    assert len(body["task_description_hash"]) == 64
    assert body["payment_mode"] == "preauth"
    assert body["nonce"]
