"""Requirement decomposer rule-based MVP."""

from services.requirement_decomposer import decompose_buyer_requirement


def test_decompose_extracts_amount_and_type():
    spec = decompose_buyer_requirement(
        requirement_text="为卖家做字幕 caption 任务 金额 25 USDC 精度 2",
        seller_identity_id="seller-1",
        buyer_identity_id="buyer-1",
    )
    assert spec["amount"] == 25.0
    assert spec["task_type"] == "api.caption"
    assert spec["task_precision"] == 2.0
    assert len(spec["agent_steps"]) >= 1
