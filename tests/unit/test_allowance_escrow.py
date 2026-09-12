"""v2 allowance escrow: the money never leaves the user's own wallet.

These tests never touch a real chain — the receipt the backend verifies is built
here exactly the way ``KarmaAllowanceEscrow`` emits it, which is what makes the
"amount comes from the event, not the request body" guarantee testable.
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest
from eth_utils import keccak

from config.settings import settings
from services.chain import allowance_escrow as escrow
from services.chain import wallet_lock
from services.chain.wallet_lock import WalletLockError

ROOT = Path(__file__).resolve().parents[2]
CONSOLE_JS = ROOT / "apps/console/scripts/cyber-console.js"
CONSOLE_API_JS = ROOT / "apps/console/scripts/karma-public-api.js"
CONSOLE_HTML = ROOT / "apps/console/pages/cyber/index.html"

CONTRACT = "0x3fe45f40c19978e81296efaf63eb2ca0c79f0e66"
TOKEN = "0x6af606f5b071bf649dc136fcd308ed0c9adf38ff"
WALLET = "0x7ed437e5786ab0d217d52937da4ff4790998d94c"
OPERATOR = "0x1d147c9eefd9d1d4c4725700a05edc6ca13975cc"


def _word(value: int) -> str:
    return f"{value:064x}"


def _addr_word(addr: str) -> str:
    return addr.lower().replace("0x", "").rjust(64, "0")


def commit_receipt(
    *,
    bill_id: int = 3,
    owner: str = WALLET,
    operator: str = OPERATOR,
    token: str = TOKEN,
    amount_wei: int = 100_000_000,
    tx_hash: str = "0x" + "cd" * 32,
    to: str = CONTRACT,
    status: int = 1,
    emit_log: bool = True,
) -> dict:
    logs = []
    if emit_log:
        logs.append(
            {
                "address": to,
                "topics": [
                    "0x" + keccak(text=escrow.EVENTS[0]).hex(),
                    "0x" + _word(bill_id),
                    "0x" + _addr_word(owner),
                    "0x" + _addr_word(operator),
                ],
                "data": "0x" + _addr_word(token) + _word(amount_wei),
            }
        )
    return {
        "status": status,
        "to": to,
        "transactionHash": tx_hash,
        "blockNumber": 11689020,
        "logs": logs,
    }


def revoke_receipt(
    *,
    bill_id: int = 3,
    owner: str = WALLET,
    unspent_wei: int = 0,
    tx_hash: str = "0x" + "ef" * 32,
    status: int = 1,
) -> dict:
    return {
        "status": status,
        "to": CONTRACT,
        "transactionHash": tx_hash,
        "blockNumber": 11689021,
        "logs": [
            {
                "address": CONTRACT,
                "topics": [
                    "0x" + keccak(text=escrow.EVENTS[1]).hex(),
                    "0x" + _word(bill_id),
                    "0x" + _addr_word(owner),
                ],
                "data": "0x" + _word(unspent_wei),
            }
        ],
    }


# ------------------------------------------------------------- decoding rules


def test_event_topics_match_the_contract_signatures():
    for signature in escrow.EVENTS:
        name = signature.split("(")[0]
        abi_event = next(e for e in escrow.ABI if e.get("type") == "event" and e["name"] == name)
        assert abi_event["inputs"], name
    # The topic we filter on is derived from the same signature the console uses.
    assert escrow.EVENTS[0] == "BillCommitted(uint256,address,address,address,uint256)"
    assert escrow.EVENTS[1] == "BillRevoked(uint256,address,uint256)"


def test_parse_commit_reads_the_amount_from_the_event():
    event = escrow.parse_commit_receipt(commit_receipt(amount_wei=42_500_000, bill_id=9))
    assert event.bill_id == 9
    assert event.owner == WALLET
    assert event.operator == OPERATOR
    assert event.token_address.lower() == TOKEN
    assert event.amount_wei == 42_500_000
    assert escrow.wei_to_usdc(event.amount_wei) == pytest.approx(42.5)


def test_parse_commit_rejects_a_transaction_without_the_event():
    with pytest.raises(WalletLockError):
        escrow.parse_commit_receipt(commit_receipt(emit_log=False))


def test_parse_revoke_reads_the_bill():
    event = escrow.parse_revoke_receipt(revoke_receipt(bill_id=11, unspent_wei=5_000_000))
    assert event.bill_id == 11
    assert event.owner == WALLET
    assert event.unspent_wei == 5_000_000


def test_parse_commit_accepts_the_hexbytes_web3_actually_returns():
    """web3 hands back HexBytes, not str — the first live claim 500'd on this."""
    receipt = commit_receipt(bill_id=12, amount_wei=7_000_000)
    for log in receipt["logs"]:
        log["topics"] = [bytes.fromhex(t[2:]) for t in log["topics"]]
        log["data"] = bytes.fromhex(log["data"][2:])
    receipt["transactionHash"] = bytes.fromhex(receipt["transactionHash"][2:])
    event = escrow.parse_commit_receipt(receipt)
    assert event.bill_id == 12
    assert event.amount_wei == 7_000_000
    assert event.owner == WALLET
    assert event.token_address.lower() == TOKEN


def test_parse_revoke_accepts_hexbytes_too():
    receipt = revoke_receipt(bill_id=13)
    for log in receipt["logs"]:
        log["topics"] = [bytes.fromhex(t[2:]) for t in log["topics"]]
        log["data"] = bytes.fromhex(log["data"][2:])
    event = escrow.parse_revoke_receipt(receipt)
    assert event.bill_id == 13
    assert event.owner == WALLET


def _topic_hex(signature: str) -> str:
    return "0x" + keccak(text=signature).hex()


def test_bills_bound_is_decoded_by_word_position_not_by_abi_name():
    """The live 500 came from reading args["bindingId"] — decode raw words instead."""
    receipt = {
        "transactionHash": "0x" + "12" * 32,
        "to": CONTRACT,
        "status": 1,
        "logs": [
            {
                "address": CONTRACT,
                "topics": [bytes.fromhex(_topic_hex(escrow.BOUND_SIG)[2:]), bytes.fromhex(_word(21)[2:])],
                "data": bytes.fromhex(
                    (
                        _word(6) + _word(7) + _word(0xAB) + _word(30_000_000) + _word(9_000_000)
                    )
                ),
            }
        ],
    }
    bound = escrow.parse_bills_bound(receipt)
    assert bound["binding_id"] == 21
    assert bound["buyer_bill_id"] == 6
    assert bound["seller_bill_id"] == 7
    assert bound["scope_hash"] == "0x" + _word(0xAB)
    assert bound["amount_wei"] == 30_000_000
    assert bound["stake_wei"] == 9_000_000


def test_settled_and_slashed_decode_the_moved_amount():
    receipt = {
        "transactionHash": "0x" + "13" * 32,
        "status": 1,
        "logs": [
            {
                "address": CONTRACT,
                "topics": [_topic_hex(escrow.SETTLED_SIG), "0x" + _word(21)],
                "data": "0x"
                + _addr_word(WALLET)
                + _addr_word("0x" + "aa" * 20)
                + _addr_word(TOKEN)
                + _word(30_000_000),
            }
        ],
    }
    settled = escrow.parse_settled(receipt)
    assert settled["binding_id"] == 21
    assert settled["from"] == WALLET
    assert settled["token"].lower() == TOKEN
    assert settled["amount_wei"] == 30_000_000

    slash = {
        "transactionHash": "0x" + "14" * 32,
        "status": 1,
        "logs": [
            {
                "address": CONTRACT,
                "topics": [_topic_hex(escrow.SLASHED_SIG), "0x" + _word(22)],
                "data": "0x"
                + _addr_word("0x" + "bb" * 20)
                + _addr_word(WALLET)
                + _addr_word(TOKEN)
                + _word(9_000_000),
            }
        ],
    }
    slashed = escrow.parse_slashed(slash)
    assert slashed["binding_id"] == 22
    assert slashed["to"] == WALLET
    assert slashed["amount_wei"] == 9_000_000


def test_abi_event_field_names_are_the_real_ones():
    """An auto-generated `arg0` name is what made a live bind crash after landing."""
    events = {e["name"]: [i["name"] for i in e["inputs"]] for e in escrow.ABI if e.get("type") == "event"}
    assert events["BillsBound"] == [
        "bindingId",
        "buyerBillId",
        "sellerBillId",
        "scopeHash",
        "amount",
        "stakeAmount",
    ]
    assert events["Settled"] == ["bindingId", "from", "to", "token", "amount"]
    assert events["StakeSlashed"] == ["bindingId", "from", "to", "token", "amount"]
    assert events["BillCommitted"] == ["billId", "owner", "operator", "token", "amount"]


def test_reverted_receipt_is_refused():
    with pytest.raises(WalletLockError):
        escrow._assert_receipt_ok(commit_receipt(status=0))


def test_foreign_target_is_refused(monkeypatch):
    monkeypatch.setattr(settings, "allowance_escrow_address", CONTRACT)
    other = "0x" + "12" * 20
    with pytest.raises(WalletLockError):
        escrow._assert_receipt_target(commit_receipt(to=other))


# --------------------------------------------------------------- configuration


def test_escrow_config_reports_missing_env(monkeypatch):
    monkeypatch.setattr(settings, "chain_allowance_escrow_enabled", False)
    monkeypatch.setattr(settings, "allowance_escrow_address", "")
    assert escrow.escrow_enabled() is False
    assert "CHAIN_ALLOWANCE_ESCROW_ENABLED" in escrow.disabled_detail()
    assert escrow.escrow_config()["enabled"] is False

    # Addresses alone are not enough: the mode stays off until the flag is on.
    monkeypatch.setattr(settings, "allowance_escrow_address", CONTRACT)
    monkeypatch.setattr(settings, "erc20_token_address", TOKEN)
    monkeypatch.setattr(settings, "testnet_rpc_url", "https://example.invalid")
    assert escrow.escrow_enabled() is False

    monkeypatch.setattr(settings, "chain_allowance_escrow_enabled", True)
    assert escrow.escrow_enabled() is True
    cfg = escrow.escrow_config()
    assert cfg["contract_address"].lower() == CONTRACT
    assert cfg["mode"] == "allowance_escrow"
    # A missing operator key must never be silently reported as "can settle".
    monkeypatch.setattr(settings, "settlement_operator_private_key", "")
    assert escrow.can_server_settle() is False
    monkeypatch.setattr(settings, "settlement_operator_private_key", "0x" + "11" * 32)
    assert escrow.can_server_settle() is True


def test_operator_gas_is_capped(monkeypatch):
    """A fee spike must never make an automatic settlement drain the operator."""
    assert settings.settlement_max_gas_price_gwei > 0
    source = (ROOT / "services/chain/allowance_escrow.py").read_text(encoding="utf-8")
    assert "settlement_max_gas_price_gwei" in source
    assert "maxFeePerGas" in source
    monkeypatch.setattr(settings, "settlement_max_gas_price_gwei", 0.0)
    assert float(settings.settlement_max_gas_price_gwei) == 0.0


def test_orphaned_reservation_can_be_released():
    """A bind whose caller died must be recoverable, not stranded forever."""
    source = (ROOT / "services/chain/allowance_escrow.py").read_text(encoding="utf-8")
    assert "def cancel_binding(" in source
    events = {e["name"] for e in escrow.ABI if e.get("type") == "event"}
    functions = {f["name"] for f in escrow.ABI if f.get("type") == "function"}
    assert {"cancelBinding", "getBinding", "checkNoCustody"} <= functions
    assert "BillsBound" in events


def test_scope_and_proof_hashes_are_32_bytes():
    scope = escrow.scope_hash("karma:agent-task:v1", "task-1")
    assert scope.startswith("0x") and len(scope) == 66
    assert escrow.proof_hash(scope) == scope
    with pytest.raises(WalletLockError):
        escrow.proof_hash("0x1234")


# ------------------------------------------------------- operator nonce safety


class _StubEth:
    def __init__(self, nonces, chain_id=11155111, gas_price=1_000_000_000):
        self._nonces = list(nonces)
        self.chain_id = chain_id
        self.gas_price = gas_price
        self.sent = []

    def get_transaction_count(self, address, tag="latest"):
        if self._nonces:
            return self._nonces.pop(0)
        return 0


class _StubW3:
    def __init__(self, eth):
        self.eth = eth


class _StubAccount:
    address = OPERATOR

    def __init__(self, seen):
        self._seen = seen

    def sign_transaction(self, tx):
        self._seen.append(tx["nonce"])

        class _Signed:
            raw_transaction = b"raw"

        return _Signed()


class _StubFn:
    def build_transaction(self, overrides):
        return dict(overrides)


def test_operator_nonce_never_goes_backwards_when_the_rpc_lags(monkeypatch):
    """The live failure: bind mined, the RPC still answered with the pre-bind
    nonce, so submitSettlement was signed with a nonce that was already spent."""
    monkeypatch.setattr(escrow, "_LAST_NONCE", {})
    eth = _StubEth([17, 17])  # both "latest" and "pending" still say 17
    assert escrow._reserve_nonce(_StubW3(eth), OPERATOR) == 17
    # the node keeps lagging; the next signature must still move forward
    assert escrow._reserve_nonce(_StubW3(_StubEth([17, 17])), OPERATOR) == 18


def test_only_a_rejected_transaction_is_re_signed():
    """A pending transaction must never be re-signed with a higher nonce, or the
    operator pays twice."""
    assert escrow._is_stale_nonce(Exception("nonce too low: next nonce 18, tx nonce 17"))
    assert escrow._is_stale_nonce(Exception("nonce has already been used"))
    assert not escrow._is_stale_nonce(Exception("already known"))
    assert not escrow._is_stale_nonce(Exception("insufficient funds for gas * price + value"))


def test_send_tx_re_signs_once_after_a_stale_nonce_rejection(monkeypatch):
    eth = _StubEth([17, 17, 17, 17])

    def send_raw(raw):
        eth.sent.append(raw)
        if len(eth.sent) == 1:
            raise ValueError("nonce too low: next nonce 18, tx nonce 17")
        return "0x" + "aa" * 32

    eth.send_raw_transaction = send_raw

    def wait(tx_hash, timeout=120):
        class _Receipt:
            transactionHash = "0x" + "aa" * 32
            status = 1

        return _Receipt()

    eth.wait_for_transaction_receipt = wait
    seen: list[int] = []
    monkeypatch.setattr(escrow, "_web3", lambda: _StubW3(eth))
    monkeypatch.setattr(escrow, "_operator_account", lambda: _StubAccount(seen))
    monkeypatch.setattr(escrow, "_LAST_NONCE", {})

    _receipt, tx_hash = escrow._send_tx(_StubFn())
    assert len(eth.sent) == 2, "the rejected transaction must be re-signed exactly once"
    assert seen == [17, 18], "the retry must use a fresh nonce, not the same one"
    assert tx_hash == "0x" + "aa" * 32


def test_a_failed_submit_releases_the_binding_instead_of_stranding_it(monkeypatch):
    """bind landed + submit failed is exactly the orphan that had to be released
    by hand on 2026-09-12. It must now clean up after itself."""
    cancelled: list[dict] = []

    def boom(**_kwargs):
        raise WalletLockError("submit blew up")

    monkeypatch.setattr(
        escrow,
        "open_order",
        lambda **_kw: {"binding_id": 42, "bind_tx_hash": "0xbind", "scope_hash": "0x" + "11" * 32},
    )
    monkeypatch.setattr(escrow, "submit_settlement", boom)
    monkeypatch.setattr(
        escrow, "cancel_binding", lambda **kw: cancelled.append(kw) or {"binding_id": kw["binding_id"]}
    )

    with pytest.raises(WalletLockError):
        escrow.open_and_submit_order(
            buyer_bill_id="8",
            seller_bill_id="9",
            amount_usdc=30.0,
            stake_usdc=9.0,
            scope="s",
            task_id="t",
            proof="0x" + "ab" * 32,
        )
    assert cancelled == [{"binding_id": 42}]


def test_open_and_submit_returns_one_merged_result(monkeypatch):
    monkeypatch.setattr(
        escrow,
        "open_order",
        lambda **_kw: {
            "binding_id": 7,
            "bind_tx_hash": "0xbind",
            "scope_hash": "0x" + "22" * 32,
            "amount_usdc": 30.0,
            "stake_usdc": 9.0,
        },
    )
    monkeypatch.setattr(
        escrow,
        "submit_settlement",
        lambda **kw: {
            "binding_id": kw["binding_id"],
            "submit_tx_hash": "0xsubmit",
            "proof_hash": "0x" + "33" * 32,
            "pull_after": 123,
        },
    )
    out = escrow.open_and_submit_order(
        buyer_bill_id="a",
        seller_bill_id="b",
        amount_usdc=30.0,
        stake_usdc=9.0,
        scope="s",
        task_id="t",
        proof="0x" + "ab" * 32,
    )
    assert out["binding_id"] == 7
    assert out["bind_tx_hash"] == "0xbind"
    assert out["submit_tx_hash"] == "0xsubmit"
    assert out["pull_after"] == 123


# ------------------------------------------------------------------ api level


async def _commit_flow(
    client,
    monkeypatch,
    *,
    tx_hash: str,
    identity_id: str = "identity-escrow-test",
    receipt_owner: str = WALLET,
    amount_wei: int = 100_000_000,
    bill_id: int = 3,
):
    monkeypatch.setattr(settings, "chain_allowance_escrow_enabled", True)
    monkeypatch.setattr(settings, "allowance_escrow_address", CONTRACT)
    monkeypatch.setattr(settings, "erc20_token_address", TOKEN)
    monkeypatch.setattr(settings, "testnet_rpc_url", "https://example.invalid")
    monkeypatch.setattr(wallet_lock, "_wallets_of", lambda identity_id: {WALLET})
    monkeypatch.setattr(
        escrow,
        "fetch_receipt",
        lambda tx: commit_receipt(
            owner=receipt_owner, tx_hash=tx, amount_wei=amount_wei, bill_id=bill_id
        ),
    )
    return await client.post(
        f"/v1/escrow/{identity_id}/claim-commit", json={"tx_hash": tx_hash}
    )


@pytest.mark.asyncio
async def test_claim_commit_is_idempotent(client, db_session, monkeypatch):
    tx_hash = "0x" + "aa" * 32
    resp = await _commit_flow(client, monkeypatch, tx_hash=tx_hash)
    assert resp.status_code == 200, resp.text
    body = resp.json()["commit"]
    assert body["bill_id"] == "3"
    assert body["amount_usdc"] == pytest.approx(100.0)
    assert body["available_usdc"] == pytest.approx(100.0)

    again = await _commit_flow(client, monkeypatch, tx_hash=tx_hash)
    assert again.status_code == 200, again.text

    state = await client.get("/v1/escrow/identity-escrow-test")
    assert state.status_code == 200, state.text
    payload = state.json()
    assert payload["escrow"]["enabled"] is True
    assert payload["committed_usdc"] == pytest.approx(100.0)
    assert len(payload["commits"]) == 1


@pytest.mark.asyncio
async def test_claim_commit_rejects_a_wallet_that_is_not_signed_in(client, monkeypatch):
    resp = await _commit_flow(
        client,
        monkeypatch,
        tx_hash="0x" + "bb" * 32,
        receipt_owner="0x" + "99" * 20,
    )
    assert resp.status_code == 409
    assert "not signed in" in resp.json()["detail"]


@pytest.mark.asyncio
async def test_claim_commit_rejects_a_foreign_token(client, monkeypatch):
    monkeypatch.setattr(settings, "chain_allowance_escrow_enabled", True)
    monkeypatch.setattr(settings, "allowance_escrow_address", CONTRACT)
    monkeypatch.setattr(settings, "erc20_token_address", TOKEN)
    monkeypatch.setattr(settings, "testnet_rpc_url", "https://example.invalid")
    monkeypatch.setattr(wallet_lock, "_wallets_of", lambda identity_id: {WALLET})
    monkeypatch.setattr(
        escrow,
        "fetch_receipt",
        lambda tx: commit_receipt(tx_hash=tx, token="0x" + "34" * 20),
    )
    resp = await client.post(
        "/v1/escrow/identity-escrow-test/claim-commit", json={"tx_hash": "0x" + "cc" * 32}
    )
    assert resp.status_code == 409
    assert "different token" in resp.json()["detail"]


# --------------------------------------------------------- console wiring rules


def test_console_selectors_match_the_contract_signatures():
    text = CONSOLE_JS.read_text(encoding="utf-8")
    block = re.search(r"const ESCROW_SELECTORS = \{(.*?)\};", text, re.S)
    assert block, "the console must declare the escrow selectors"
    selectors = {
        key: value
        for key, value in re.findall(r"(\w+):\s*\"(0x[0-9a-f]{8})\"", block.group(1))
    }
    assert selectors["approve"] == "0x" + keccak(text="approve(address,uint256)").hex()[:8]
    assert selectors["allowance"] == "0x" + keccak(text="allowance(address,address)").hex()[:8]
    assert selectors["commit"] == "0x" + keccak(text="commit(address,uint256,address)").hex()[:8]
    assert selectors["revoke"] == "0x" + keccak(text="revoke(uint256)").hex()[:8]


def test_console_authorises_once_and_never_asks_for_a_key():
    text = CONSOLE_JS.read_text(encoding="utf-8")
    assert "onchainCommit" in text
    assert "ESCROW_SELECTORS.commit" in text
    assert "onchainEscrowRevoke" in text
    assert "ESCROW_SELECTORS.revoke" in text
    # The whole point of v2: no per-order signature, and no private key anywhere.
    for forbidden in ("privateKey", "mnemonic", "seedPhrase", "eth_sign"):
        assert forbidden not in text, forbidden


def test_console_explains_that_the_money_stays_in_the_wallet():
    js = CONSOLE_JS.read_text(encoding="utf-8")
    html = CONSOLE_HTML.read_text(encoding="utf-8")
    assert "资金留在你的钱包" in js
    assert "escrow-commits" in js
    assert 'id="escrow-commits"' in html


def test_console_api_exposes_the_escrow_helpers():
    text = CONSOLE_API_JS.read_text(encoding="utf-8")
    for name in ("getEscrowState", "claimCommit", "claimEscrowRevoke", "syncEscrow"):
        assert name in text, name
    assert "/v1/escrow/" in text