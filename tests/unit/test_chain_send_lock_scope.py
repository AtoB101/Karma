"""发交易的进程锁只该护住「nonce + 广播」，不该把等回执也圈进去。

2026-09-30 并发压测实测：10 路并发 buyer-accept，每单两笔链上交易
（submitSettlement + buyerConfirm）。_send_tx 原本在 _SEND_LOCK 里
wait_for_transaction_receipt，于是 20 笔交易完全串行 —— 单个请求
438~462s，超过 nginx 300s 的 proxy_read_timeout，客户端全部 504（钱其实
到账了，接口早被掐断）。

这里钉住两条不变式：
  * 广播（send_raw_transaction）**在锁里** —— nonce 的分配与广播顺序不能被并发撕开；
  * 等回执（wait_for_transaction_receipt）**在锁外** —— 否则并发又变回串行。
"""
from __future__ import annotations

from types import SimpleNamespace

import pytest

from services.chain import allowance_escrow as ae

TX_HASH = b"" * 32


class _Eth:
    chain_id = 11155111
    gas_price = 1_000_000_000

    def __init__(self):
        self.counts = 0
        self.observed_locked = []
        self.waited = 0

    def get_transaction_count(self, address, tag=None):
        self.counts += 1
        return 7

    def send_raw_transaction(self, raw):
        self.observed_locked.append(("broadcast", ae._SEND_LOCK.locked()))
        return TX_HASH

    def wait_for_transaction_receipt(self, tx_hash, timeout=None):
        self.observed_locked.append(("receipt", ae._SEND_LOCK.locked()))
        self.waited += 1
        return {"status": 1, "transactionHash": TX_HASH, "blockNumber": 100}


class _W3:
    def __init__(self, eth):
        self.eth = eth


class _Account:
    address = "0x00000000000000000000000000000000000000AA"

    def sign_transaction(self, tx):
        return SimpleNamespace(raw_transaction=b"raw-tx")


class _Fn:
    def build_transaction(self, overrides):
        return {"nonce": overrides.get("nonce"), "from": overrides.get("from")}


@pytest.fixture()
def fake_chain(monkeypatch):
    eth = _Eth()
    monkeypatch.setattr(ae, "_web3", lambda: _W3(eth))
    monkeypatch.setattr(ae, "_LAST_NONCE", {})
    return eth


def test_receipt_is_awaited_outside_the_send_lock(fake_chain):
    receipt, tx_hash = ae._send_tx(_Fn(), account=_Account())

    assert fake_chain.waited == 1
    assert receipt["status"] == 1
    assert tx_hash.startswith("0x")
    assert fake_chain.observed_locked == [
        ("broadcast", True),
        ("receipt", False),
    ]


def test_nonce_is_reserved_under_the_lock(fake_chain):
    """广播必须还在锁里：nonce 分配 + 广播顺序是一个临界区。"""
    ae._send_tx(_Fn(), account=_Account())
    assert fake_chain.counts >= 2  # latest + pending 两次读
    assert fake_chain.observed_locked[0] == ("broadcast", True)


def test_a_reverted_receipt_still_raises(fake_chain, monkeypatch):
    def _bad(tx_hash, timeout=None):
        fake_chain.observed_locked.append(("receipt", ae._SEND_LOCK.locked()))
        return {"status": 0, "transactionHash": TX_HASH, "blockNumber": 100}

    monkeypatch.setattr(fake_chain, "wait_for_transaction_receipt", _bad)
    with pytest.raises(Exception):
        ae._send_tx(_Fn(), account=_Account())
