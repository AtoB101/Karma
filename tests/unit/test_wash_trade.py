from __future__ import annotations

from datetime import datetime, timedelta

from services.wash_trade import TradeEdge, evaluate_wash_signals


def test_organic_trade_credits():
    v = evaluate_wash_signals(buyer_id="b1", seller_id="s1", amount=20.0, history=[])
    assert v.credit is True
    assert v.flags_delta == 0


def test_self_deal_blocked():
    v = evaluate_wash_signals(buyer_id="same", seller_id="same", amount=50.0, history=[])
    assert v.credit is False
    assert "self_deal" in v.signals
    assert v.flags_delta >= 2


def test_same_wallet_blocked():
    v = evaluate_wash_signals(
        buyer_id="b",
        seller_id="s",
        amount=20.0,
        history=[],
        buyer_wallet="0xABC",
        seller_wallet="0xabc",
    )
    assert v.credit is False
    assert "same_wallet" in v.signals


def test_dust_no_credit_no_flag_first():
    v = evaluate_wash_signals(buyer_id="b", seller_id="s", amount=0.01, history=[])
    assert v.credit is False
    assert "dust" in v.signals
    assert v.flags_delta == 0


def test_dust_repeat_same_pair_flags():
    hist = [TradeEdge(buyer_id="b", seller_id="s", amount=0.01, at=datetime.utcnow())]
    v = evaluate_wash_signals(buyer_id="b", seller_id="s", amount=0.02, history=hist)
    assert v.credit is False
    assert v.flags_delta >= 1


def test_circular_ping_pong():
    hist = [TradeEdge(buyer_id="s1", seller_id="b1", amount=10.0, at=datetime.utcnow())]
    v = evaluate_wash_signals(buyer_id="b1", seller_id="s1", amount=10.0, history=hist)
    assert v.credit is False
    assert "circular" in v.signals


def test_pair_velocity():
    now = datetime.utcnow()
    hist = [
        TradeEdge(buyer_id="b", seller_id="s", amount=12.0, at=now - timedelta(minutes=i))
        for i in range(3)
    ]
    v = evaluate_wash_signals(buyer_id="b", seller_id="s", amount=12.0, history=hist, now=now)
    assert v.credit is False
    assert "pair_velocity" in v.signals


def test_burst():
    now = datetime.utcnow()
    hist = [
        TradeEdge(buyer_id=f"b{i}", seller_id="s", amount=15.0, at=now - timedelta(minutes=i))
        for i in range(7)
    ]
    v = evaluate_wash_signals(buyer_id="b8", seller_id="s", amount=15.0, history=hist, now=now)
    assert v.credit is False
    assert "burst" in v.signals
