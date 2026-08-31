from __future__ import annotations

from datetime import datetime, timedelta

from services.reputation_pack import evaluate_pack_eligibility, score_to_e2


def test_undisputed_path_eligible():
    elig = evaluate_pack_eligibility(
        score=220,
        successful_tasks=8,
        disputed_tasks=0,
        last_incident_at=None,
    )
    assert elig.eligible is True
    assert elig.path == "undisputed"
    assert elig.dividend_eligible_offchain is False


def test_high_score_dividend_flag():
    elig = evaluate_pack_eligibility(
        score=320,
        successful_tasks=12,
        disputed_tasks=0,
        last_incident_at=None,
    )
    assert elig.dividend_eligible_offchain is True


def test_recent_dispute_blocks_pack():
    elig = evaluate_pack_eligibility(
        score=400,
        successful_tasks=20,
        disputed_tasks=1,
        last_incident_at=datetime.utcnow() - timedelta(days=10),
        last_incident_kind="dispute",
    )
    assert elig.eligible is False
    assert any("within_90d" in r for r in elig.reasons)


def test_rehab_after_90_days():
    elig = evaluate_pack_eligibility(
        score=250,
        successful_tasks=15,
        disputed_tasks=2,
        last_incident_at=datetime.utcnow() - timedelta(days=91),
        last_incident_kind="fraud",
        now=datetime.utcnow(),
    )
    assert elig.eligible is True
    assert elig.path == "rehab_90d"


def test_score_e2():
    assert score_to_e2(200.0) == 20000
    assert score_to_e2(200.5) == 20050


def test_insufficient_successes_blocks():
    elig = evaluate_pack_eligibility(
        score=400,
        successful_tasks=2,
        disputed_tasks=0,
        last_incident_at=None,
    )
    assert elig.eligible is False
    assert any("successes_below" in r for r in elig.reasons)


def test_wash_flags_block_pack():
    elig = evaluate_pack_eligibility(
        score=400,
        successful_tasks=20,
        disputed_tasks=0,
        last_incident_at=None,
        wash_trade_flags=3,
    )
    assert elig.eligible is False
    assert any("wash_flags" in r for r in elig.reasons)


def test_wash_flags_rehab_after_90_days():
    elig = evaluate_pack_eligibility(
        score=400,
        successful_tasks=20,
        disputed_tasks=0,
        last_incident_at=datetime.utcnow() - timedelta(days=91),
        last_incident_kind="wash",
        wash_trade_flags=5,
        now=datetime.utcnow(),
    )
    assert elig.eligible is True
    assert elig.path == "rehab_90d"
