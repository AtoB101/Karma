from karma_openclaw.orchestration import suggest_next_steps


def test_suggest_delivered_buyer():
    out = suggest_next_steps(
        role="buyer",
        settlement_status="delivered",
        voucher_status="accepted",
        handoff_ok=True,
    )
    assert "verification" in out["suggested_action"].lower() or "buyer" in out["suggested_action"].lower()


def test_handoff_not_ok_adds_hints():
    out = suggest_next_steps(role="seller", settlement_status="pending", voucher_status="accepted", handoff_ok=False)
    assert out["hints"]
