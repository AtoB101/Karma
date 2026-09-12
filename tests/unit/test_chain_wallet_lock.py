"""On-chain wallet lock: receipt verification, ledger credit, and console wiring.

These tests never touch a real chain — the receipt the backend verifies is built
here exactly the way KarmaBilateral emits it, which is what makes the "amount
comes from the event, not the request body" guarantee testable.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from eth_utils import keccak

from config.settings import settings
from db.models.orm import CapacityModel
from services.chain import wallet_lock
from services.chain.wallet_lock import (
    BILL_BURNED_TOPIC,
    BILL_MINTED_TOPIC,
    WalletLockError,
    decode_bill_burned,
    decode_bill_minted,
)
from services.identity_gateway import store as identity_store

ROOT = Path(__file__).resolve().parents[2]
CONSOLE_JS = ROOT / "apps/console/scripts/cyber-console.js"
CONSOLE_HTML = ROOT / "apps/console/pages/cyber/index.html"

CONTRACT = "0x496d178a5d32e9410e52bd5800602bdee81b2a91"
TOKEN = "0x6af606f5b071bf649dc136fcd308ed0c9adf38ff"
WALLET = "0x7ed437e5786ab0d217d52937da4ff4790998d94c"


def _word(value: int) -> str:
    return f"{value:064x}"


def _addr_word(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def minted_receipt(
    *,
    bill_id: int = 7,
    owner: str = WALLET,
    token: str = TOKEN,
    amount_wei: int = 25_000_000,
    tx_hash: str = "0x" + "ab" * 32,
    to: str = CONTRACT,
    status: int = 1,
    emit_log: bool = True,
) -> dict:
    logs = []
    if emit_log:
        logs.append(
            {
                "address": to,
                "topics": [BILL_MINTED_TOPIC, "0x" + _word(bill_id), "0x" + _addr_word(owner)],
                "data": "0x" + _addr_word(token) + _word(amount_wei),
            }
        )
    return {
        "status": status,
        "to": to,
        "transactionHash": tx_hash,
        "blockNumber": 11685814,
        "logs": logs,
    }


def burned_receipt(
    *,
    bill_id: int = 7,
    owner: str = WALLET,
    amount_wei: int = 25_000_000,
    reason: str = "unlocked",
    tx_hash: str = "0x" + "cd" * 32,
    to: str = CONTRACT,
) -> dict:
    encoded = reason.encode("utf-8")
    padded = encoded + b"\x00" * ((32 - len(encoded) % 32) % 32)
    data = "0x" + _word(amount_wei) + _word(64) + _word(len(encoded)) + padded.hex()
    return {
        "status": 1,
        "to": to,
        "transactionHash": tx_hash,
        "blockNumber": 11685900,
        "logs": [
            {
                "address": to,
                "topics": [BILL_BURNED_TOPIC, "0x" + _word(bill_id), "0x" + _addr_word(owner)],
                "data": data,
            }
        ],
    }


# --------------------------------------------------------------- decode logic


def test_event_topics_match_the_contract_signatures():
    assert BILL_MINTED_TOPIC == "0x" + keccak(
        text="BillMinted(uint256,address,address,uint256)"
    ).hex()
    assert BILL_BURNED_TOPIC == "0x" + keccak(
        text="BillBurned(uint256,address,uint256,string)"
    ).hex()


def test_decode_bill_minted_reads_amount_from_the_event():
    event = decode_bill_minted(
        minted_receipt(amount_wei=12_340_000),
        contract_address=CONTRACT,
        expected_token=TOKEN,
    )
    assert event.bill_id == 7
    assert event.owner == WALLET
    assert event.token_address == TOKEN
    assert event.amount_wei == 12_340_000
    assert wallet_lock.wei_to_usdc(event.amount_wei) == pytest.approx(12.34)


def test_decode_bill_minted_rejects_foreign_transactions():
    with pytest.raises(WalletLockError):
        decode_bill_minted(
            minted_receipt(to="0x" + "22" * 20),
            contract_address=CONTRACT,
        )
    with pytest.raises(WalletLockError):
        decode_bill_minted(minted_receipt(status=0), contract_address=CONTRACT)
    with pytest.raises(WalletLockError):
        decode_bill_minted(minted_receipt(emit_log=False), contract_address=CONTRACT)
    with pytest.raises(WalletLockError):
        decode_bill_minted(
            minted_receipt(token="0x" + "33" * 20),
            contract_address=CONTRACT,
            expected_token=TOKEN,
        )


def test_decode_bill_burned_distinguishes_withdraw_from_settlement():
    event = decode_bill_burned(burned_receipt(), contract_address=CONTRACT)
    assert (event.bill_id, event.owner, event.reason) == (7, WALLET, "unlocked")

    # A settle() burn must not be mistaken for a user withdrawal.
    with pytest.raises(WalletLockError):
        decode_bill_burned(burned_receipt(reason="settled"), contract_address=CONTRACT)


def test_amount_conversion_round_trips():
    assert wallet_lock.usdc_to_wei(1.5) == 1_500_000
    assert wallet_lock.wei_to_usdc(wallet_lock.usdc_to_wei(0.01)) == pytest.approx(0.01)


def test_chain_config_reports_missing_env(monkeypatch):
    monkeypatch.setattr(settings, "chain_wallet_lock_enabled", False)
    monkeypatch.setattr(settings, "karma_bilateral_address", "")
    assert wallet_lock.chain_lock_enabled() is False
    assert "CHAIN_WALLET_LOCK_ENABLED" in wallet_lock.disabled_detail()
    assert wallet_lock.chain_config()["enabled"] is False

    # Addresses alone are not enough: deposits stay off until the flag is on, so
    # enabling them can never be a side effect of the settlement configuration.
    monkeypatch.setattr(settings, "karma_bilateral_address", CONTRACT)
    monkeypatch.setattr(settings, "erc20_token_address", TOKEN)
    monkeypatch.setattr(settings, "testnet_rpc_url", "https://example.invalid")
    assert wallet_lock.chain_lock_enabled() is False

    monkeypatch.setattr(settings, "chain_wallet_lock_enabled", True)
    monkeypatch.setattr(settings, "karma_bilateral_address", CONTRACT)
    monkeypatch.setattr(settings, "erc20_token_address", TOKEN)
    monkeypatch.setattr(settings, "testnet_rpc_url", "https://example.invalid")
    assert wallet_lock.chain_lock_enabled() is True
    cfg = wallet_lock.chain_config()
    assert cfg["contract_address"].lower() == CONTRACT
    assert cfg["chain_id"] == settings.testnet_chain_id


def test_wallets_of_follows_the_master_identity(monkeypatch):
    class _Ident:
        def __init__(self, wallet: str, parent: str | None = None):
            self.wallet = wallet
            self.parent_identity_id = parent

    table = {
        "master-1": _Ident("0x" + "AA" * 20),
        "sub-1": _Ident("0x" + "BB" * 20, parent="master-1"),
    }
    monkeypatch.setattr(identity_store, "get_by_id", lambda iid: table.get(iid))
    assert wallet_lock._wallets_of("sub-1") == {"0x" + "aa" * 20, "0x" + "bb" * 20}


def test_seller_default_stake_is_thirty_percent():
    """Sellers stake 30% of the order value on every accepted order."""
    assert settings.settlement_default_penalty_bps == 3000


# ------------------------------------------------------------------ API level


async def _credit_flow(
    client,
    monkeypatch,
    *,
    tx_hash: str,
    signed_in: set[str] | None = None,
    receipt_owner: str = WALLET,
):
    monkeypatch.setattr(settings, "chain_wallet_lock_enabled", True)
    monkeypatch.setattr(settings, "karma_bilateral_address", CONTRACT)
    monkeypatch.setattr(settings, "erc20_token_address", TOKEN)
    monkeypatch.setattr(settings, "testnet_rpc_url", "https://example.invalid")
    monkeypatch.setattr(wallet_lock, "_wallets_of", lambda identity_id: set(signed_in or {WALLET}))
    monkeypatch.setattr(
        wallet_lock,
        "fetch_receipt",
        lambda tx: minted_receipt(owner=receipt_owner, tx_hash=tx),
    )
    return await client.post(
        "/v1/capacity/identity-chain-test/claim-bill", json={"tx_hash": tx_hash}
    )


@pytest.mark.asyncio
async def test_claim_bill_credits_the_ledger_exactly_once(client, db_session, monkeypatch):
    tx_hash = "0x" + "11" * 32
    resp = await _credit_flow(client, monkeypatch, tx_hash=tx_hash)
    assert resp.status_code == 200, resp.text
    assert resp.json()["total_locked_usdc"] == pytest.approx(25.0)
    assert resp.json()["available_credits"] == pytest.approx(25.0)

    # Replaying the same transaction (page refresh, retry) must not re-credit.
    again = await _credit_flow(client, monkeypatch, tx_hash=tx_hash)
    assert again.status_code == 200, again.text
    assert again.json()["total_locked_usdc"] == pytest.approx(25.0)

    row = await db_session.get(CapacityModel, "identity-chain-test")
    assert row.total_locked_usdc == pytest.approx(25.0)

    state = await client.get("/v1/capacity/identity-chain-test/chain")
    assert state.status_code == 200, state.text
    body = state.json()
    assert body["chain"]["enabled"] is True
    assert body["onchain_locked_usdc"] == pytest.approx(25.0)
    assert body["ledger_locked_usdc"] == pytest.approx(25.0)
    assert body["bills"][0]["bill_id"] == "7"


@pytest.mark.asyncio
async def test_claim_bill_rejects_a_wallet_that_is_not_signed_in(client, monkeypatch):
    resp = await _credit_flow(
        client, monkeypatch, tx_hash="0x" + "22" * 32, receipt_owner="0x" + "99" * 20
    )
    assert resp.status_code == 409
    assert "not signed in" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_claim_bill_is_refused_when_the_chain_is_not_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "settlement_mode", "offchain")
    monkeypatch.setattr(settings, "chain_wallet_lock_enabled", False)
    resp = await client.post(
        "/v1/capacity/identity-chain-test/claim-bill", json={"tx_hash": "0x" + "33" * 32}
    )
    assert resp.status_code == 409
    assert "not configured" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_claim_bill_rejects_a_reverted_transaction(client, monkeypatch):
    monkeypatch.setattr(settings, "chain_wallet_lock_enabled", True)
    monkeypatch.setattr(settings, "karma_bilateral_address", CONTRACT)
    monkeypatch.setattr(settings, "erc20_token_address", TOKEN)
    monkeypatch.setattr(settings, "testnet_rpc_url", "https://example.invalid")
    monkeypatch.setattr(wallet_lock, "_wallets_of", lambda identity_id: {WALLET})
    monkeypatch.setattr(
        wallet_lock,
        "fetch_receipt",
        lambda tx: minted_receipt(status=0, tx_hash=tx),
    )
    resp = await client.post(
        "/v1/capacity/identity-chain-test/claim-bill", json={"tx_hash": "0x" + "44" * 32}
    )
    assert resp.status_code == 409
    assert "reverted" in resp.json()["detail"]


# --------------------------------------------------------------- console wiring


def test_console_selectors_match_the_contract_signatures():
    text = CONSOLE_JS.read_text(encoding="utf-8")
    expected = {
        "approve": "approve(address,uint256)",
        "allowance": "allowance(address,address)",
        "lock": "lock(address,uint256)",
        "unlock": "unlock(uint256)",
    }
    for name, signature in expected.items():
        selector = "0x" + keccak(text=signature)[:4].hex()
        assert re.search(rf'{name}:\s*"{selector}"', text), f"{name} selector drifted from {signature}"


def test_console_locks_with_the_wallet_and_claims_the_receipt():
    text = CONSOLE_JS.read_text(encoding="utf-8")
    assert "eth_sendTransaction" in text
    assert "wallet_switchEthereumChain" in text
    assert "cyberKarmaApi.claimBill(" in text
    assert "cyberKarmaApi.claimUnlock(" in text
    # No code path may ask the wallet for a key / mnemonic.
    for banned in ("eth_getEncryptionPublicKey", "eth_signTypedData_v4", "privateKey", "mnemonic"):
        assert banned not in text


def test_console_never_pretends_a_ledger_lock_is_real_money():
    js = CONSOLE_JS.read_text(encoding="utf-8")
    html = CONSOLE_HTML.read_text(encoding="utf-8")
    assert "台账模式 · 无链上资金" in js
    assert "链上锁仓记录" in js
    assert 'id="chain-bills"' in html


def test_console_api_exposes_the_chain_helpers():
    api = (ROOT / "apps/console/scripts/karma-public-api.js").read_text(encoding="utf-8")
    for name in ("getChainLockState", "claimBill", "claimUnlock"):
        assert name in api
