"""v2 allowance escrow — the user's USDC never leaves their own wallet.

How this differs from ``wallet_lock`` (v1 ``KarmaBilateral.lock()``)
------------------------------------------------------------------
v1 moved the money *into* the contract, so every later step needed the bill
owner's signature again. Here the wallet keeps its balance and grants the
escrow one ERC-20 allowance; ``commit()`` merely records a responsibility
("this wallet has committed up to X"). Settlement pulls

    payerWallet --transferFrom--> payeeWallet

so the contract's token balance is always zero (``checkNoCustody``) and there is
nothing custodied to freeze, seize or re-hypothecate.

Security model (mirrors ``wallet_lock``)
---------------------------------------
* Karma never holds, asks for, or transmits a user private key / seed phrase.
  The user signs ``approve`` + ``commit`` once in their own wallet; this module
  only *reads* the resulting receipt (and, for the operator path, sends Karma's
  own operational account so the user never signs again).
* Amounts come from the on-chain ``BillCommitted`` event, never from the request
  body, so a client cannot inflate its own credits.
* One bill is credited exactly once: ``allowance_commits`` is keyed by bill id
  and the commit tx hash is unique, so replaying a transaction is a no-op.
* The bill must belong to a wallet that SIWE-proved for this identity.
* ``isBacked``/``available`` are read back from the chain, so the console shows
  what the contract says, not what the database hopes.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import AllowanceCommitModel, EscrowBindingModel
from services.chain.wallet_lock import (
    WalletLockError,
    _field,
    _hex_int,
    _hexstr,
    _topic_address,
    fetch_receipt,
    token_decimals,
    usdc_to_wei,
    wei_to_usdc,
)

logger = structlog.get_logger(__name__)

IDLE = "open"
REVOKED = "revoked"
CLOSED = "closed"

_ZERO = "0x0000000000000000000000000000000000000000"

EVENTS = [
    "BillCommitted(uint256,address,address,address,uint256)",
    "BillRevoked(uint256,address,uint256)",
    "BillsBound(uint256,uint256,uint256,bytes32,uint256,uint256)",
    "SettleSubmitted(uint256,bytes32,uint256)",
    "Settled(uint256,address,address,address,uint256)",
    "StakeSlashed(uint256,address,address,address,uint256)",
]

_ABI_FUNCTIONS = [
    {
        "name": "commit",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "token", "type": "address"},
            {"name": "amount", "type": "uint256"},
            {"name": "operator", "type": "address"},
        ],
        "outputs": [{"name": "billId", "type": "uint256"}],
    },
    {
        "name": "revoke",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "billId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "bind",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "buyerBillId", "type": "uint256"},
            {"name": "sellerBillId", "type": "uint256"},
            {"name": "scopeHash", "type": "bytes32"},
            {"name": "amount", "type": "uint256"},
            {"name": "stakeAmount", "type": "uint256"},
        ],
        "outputs": [{"name": "bindingId", "type": "uint256"}],
    },
    {
        "name": "submitSettlement",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [
            {"name": "bindingId", "type": "uint256"},
            {"name": "proofHash", "type": "bytes32"},
        ],
        "outputs": [],
    },
    {
        "name": "finalizeSettlement",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "bindingId", "type": "uint256"}],
        "outputs": [{"name": "paid", "type": "uint256"}],
    },
    {
        "name": "finalizeBreach",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "bindingId", "type": "uint256"}],
        "outputs": [{"name": "slashed", "type": "uint256"}],
    },
    {
        "name": "getBill",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "billId", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "billId", "type": "uint256"},
                    {"name": "owner", "type": "address"},
                    {"name": "operator", "type": "address"},
                    {"name": "token", "type": "address"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "reserved", "type": "uint256"},
                    {"name": "spent", "type": "uint256"},
                    {"name": "state", "type": "uint8"},
                    {"name": "createdAt", "type": "uint256"},
                ],
            }
        ],
    },
    {
        "name": "available",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "billId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "uint256"}],
    },
    {
        "name": "isBacked",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "billId", "type": "uint256"}],
        "outputs": [{"name": "", "type": "bool"}],
    },
    {
        "name": "disputeWindowSeconds",
        "type": "function",
        "stateMutability": "view",
        "inputs": [],
        "outputs": [{"name": "", "type": "uint256"}],
    },
]


BILL_STATE = {0: "none", 1: "open", 2: "closed"}
BINDING_STATE = {0: "none", 1: "active", 2: "finalizing", 3: "settled", 4: "slashed", 5: "cancelled"}


def _event_inputs(sig: str) -> list[dict[str, Any]]:
    """Turn ``Name(uint256,address)`` into ABI inputs (all non-indexed).

    ``process_receipt`` needs the *indexed* flags to match the contract exactly,
    so the two indexed layouts we actually use are patched in ``EVENT_INDEXED``.
    """
    name, rest = sig.split("(")
    types = rest.rstrip(")").split(",")
    indexed = EVENT_INDEXED.get(name, set())
    params = []
    for i, typ in enumerate(types):
        params.append({"name": f"arg{i}", "type": typ, "indexed": i in indexed})
    return params


# Which positional args the contract declares as `indexed`.
EVENT_INDEXED: dict[str, set[int]] = {
    "BillCommitted": {0, 1, 2},   # billId, owner, operator
    "BillRevoked": {0, 1},        # billId, owner
    "BillsBound": {0},            # bindingId
    "SettleSubmitted": {0},       # bindingId
    "Settled": {0},               # bindingId
    "StakeSlashed": {0},          # bindingId
}

_ABI_EVENTS = [
    {
        "name": sig.split("(")[0],
        "type": "event",
        "anonymous": False,
        "inputs": _event_inputs(sig),
    }
    for sig in EVENTS
]

ABI = _ABI_FUNCTIONS + _ABI_EVENTS
ABI_JSON = json.dumps(ABI)


# ----------------------------------------------------------------- config view


def configured_address() -> str:
    return (settings.allowance_escrow_address or "").strip()


def operator_address() -> str:
    return (settings.settlement_operator_address or "").strip()


def _missing_chain_config() -> list[str]:
    missing: list[str] = []
    if not settings.chain_allowance_escrow_enabled:
        missing.append("CHAIN_ALLOWANCE_ESCROW_ENABLED")
    if not configured_address():
        missing.append("ALLOWANCE_ESCROW_ADDRESS")
    if not (settings.erc20_token_address or "").strip():
        missing.append("ERC20_TOKEN_ADDRESS")
    if not (settings.testnet_rpc_url or "").strip():
        missing.append("TESTNET_RPC_URL")
    return missing


def escrow_enabled() -> bool:
    return not _missing_chain_config()


def disabled_detail() -> str:
    missing = _missing_chain_config()
    if not missing:
        return ""
    return "allowance escrow is not configured: " + ", ".join(missing)


def escrow_config() -> dict[str, Any]:
    """Everything the Console needs to build approve/commit/revoke calldata."""
    return {
        "enabled": escrow_enabled(),
        "mode": "allowance_escrow",
        "chain_id": int(settings.testnet_chain_id or 0),
        "contract_address": configured_address(),
        "token_address": (settings.erc20_token_address or "").strip(),
        "token_decimals": token_decimals(),
        "token_symbol": "USDC",
        "operator_address": operator_address(),
        "dispute_window_seconds": int(settings.allowance_escrow_dispute_window or 0),
        "can_server_settle": bool(can_server_settle()),
        "explorer_url": (settings.chain_explorer_url or "").strip(),
        "missing_config": _missing_chain_config(),
    }


def can_server_settle() -> bool:
    return bool((settings.settlement_operator_private_key or "").strip() and configured_address())


# ---------------------------------------------------------------------- web3


def _web3():
    if not (settings.testnet_rpc_url or "").strip():
        raise WalletLockError(disabled_detail() or "TESTNET_RPC_URL not set")
    from web3 import Web3

    return Web3(Web3.HTTPProvider(settings.testnet_rpc_url, request_kwargs={"timeout": 20}))


def _contract(w3, address: str | None = None):
    return w3.eth.contract(
        address=w3.to_checksum_address(address or configured_address()), abi=ABI
    )


def _operator_account():
    from eth_account import Account

    key = (settings.settlement_operator_private_key or "").strip()
    if not key:
        raise WalletLockError(
            "no Karma settlement operator is configured (SETTLEMENT_OPERATOR_PRIVATE_KEY)"
        )
    return Account.from_key(key)

# ------------------------------------------------------------ receipt decode


@dataclass(frozen=True)
class CommitEvent:
    bill_id: int
    owner: str
    operator: str
    token_address: str
    amount_wei: int
    tx_hash: str
    block_number: int | None = None


@dataclass(frozen=True)
class RevokeEvent:
    bill_id: int
    owner: str
    unspent_wei: int
    tx_hash: str


def _hex_address(value: Any) -> str:
    text = _hexstr(value)
    return text.lower()


def _topic(sig: str) -> str:
    """keccak256(signature) as a 0x-prefixed topic, computed, never hardcoded."""
    from eth_utils import keccak

    return "0x" + keccak(text=sig).hex()


def _topic_int(topic: Any) -> int:
    # web3 hands back HexBytes, not str: normalise before parsing.
    return _hex_int(_hexstr(topic))


def _topic_word_addr(topic: Any) -> str:
    return _topic_address(_hexstr(topic))


def _data_words(data: str) -> list[str]:
    text = _hexstr(data)
    if text.startswith("0x"):
        text = text[2:]
    return [text[i : i + 64] for i in range(0, len(text), 64)]


def _word_to_int(word: str) -> int:
    return int(word or "0", 16)


def parse_commit_receipt(receipt: Any) -> CommitEvent:
    """Read ``BillCommitted`` out of a commit() transaction.

    Decoded from raw topics/data on purpose: no RPC round-trip, so the
    "amount comes from the event, not the request body" rule is unit-testable.
    """
    want = _topic(EVENTS[0])
    for log in _field(receipt, "logs", []) or []:
        topics = list(_field(log, "topics", []) or [])
        if not topics or _hexstr(topics[0]).lower() != want:
            continue
        if len(topics) < 4:
            continue
        words = _data_words(_field(log, "data", "0x"))
        if len(words) < 2:
            continue
        return CommitEvent(
            bill_id=_topic_int(topics[1]),
            owner=_topic_word_addr(topics[2]),
            operator=_topic_word_addr(topics[3]),
            token_address="0x" + words[0][-40:].lower(),
            amount_wei=_word_to_int(words[1]),
            tx_hash=_hexstr(_field(receipt, "transactionHash", "")),
            block_number=_field(receipt, "blockNumber"),
        )
    raise WalletLockError(
        "no BillCommitted event found in this transaction — not a Karma commitment"
    )


def parse_revoke_receipt(receipt: Any) -> RevokeEvent:
    want = _topic(EVENTS[1])
    for log in _field(receipt, "logs", []) or []:
        topics = list(_field(log, "topics", []) or [])
        if not topics or _hexstr(topics[0]).lower() != want:
            continue
        if len(topics) < 3:
            continue
        words = _data_words(_field(log, "data", "0x"))
        return RevokeEvent(
            bill_id=_topic_int(topics[1]),
            owner=_topic_word_addr(topics[2]),
            unspent_wei=_word_to_int(words[0]) if words else 0,
            tx_hash=_hexstr(_field(receipt, "transactionHash", "")),
        )
    raise WalletLockError("no BillRevoked event found in this transaction")

def _assert_receipt_ok(receipt: Any) -> None:
    status = _field(receipt, "status")
    if status is not None and int(status) != 1:
        raise WalletLockError("this transaction reverted — nothing was committed")


def _assert_receipt_target(receipt: Any) -> None:
    """The transaction must have gone to *our* escrow, not some look-alike."""
    want = configured_address()
    got = _hexstr(_field(receipt, "to", "")).lower()
    if want and got and got != want.lower():
        raise WalletLockError("this transaction was not sent to the Karma escrow")


def _assert_owner_allowed(owner: str, wallets: set[str]) -> None:
    if not wallets:
        raise WalletLockError(
            "cannot verify wallet ownership for this identity — connect the wallet in "
            "the Console (SIWE) and retry"
        )
    if owner.lower() not in wallets:
        raise WalletLockError(
            "this commitment belongs to a wallet that is not signed in for this identity"
        )


def _assert_token_allowed(token_address: str) -> None:
    expected = (settings.erc20_token_address or "").strip().lower()
    if expected and token_address.lower() != expected:
        raise WalletLockError(
            "this commitment uses a different token than the configured settlement token"
        )


async def _by_bill(db: AsyncSession, bill_id: str) -> AllowanceCommitModel | None:
    return await db.get(AllowanceCommitModel, str(bill_id))


async def _by_commit_tx(db: AsyncSession, tx_hash: str) -> AllowanceCommitModel | None:
    result = await db.execute(
        select(AllowanceCommitModel).where(AllowanceCommitModel.commit_tx_hash == tx_hash)
    )
    return result.scalar_one_or_none()


async def list_commits(db: AsyncSession, identity_id: str) -> list[AllowanceCommitModel]:
    result = await db.execute(
        select(AllowanceCommitModel)
        .where(AllowanceCommitModel.identity_id == identity_id)
        .order_by(AllowanceCommitModel.created_at.desc())
    )
    return list(result.scalars().all())


async def list_bindings(db: AsyncSession, identity_id: str) -> list[EscrowBindingModel]:
    result = await db.execute(
        select(EscrowBindingModel)
        .where(
            (EscrowBindingModel.buyer_identity_id == identity_id)
            | (EscrowBindingModel.seller_identity_id == identity_id)
        )
        .order_by(EscrowBindingModel.created_at.desc())
    )
    return list(result.scalars().all())


# --------------------------------------------------------------- public writes


async def claim_commit(
    db: AsyncSession,
    *,
    identity_id: str,
    tx_hash: str,
    wallets: set[str],
) -> AllowanceCommitModel:
    """Credit a wallet-signed ``commit()`` to this identity (idempotent).

    The amount is read from the chain, so the client cannot choose it. The bill
    must belong to a wallet proven for this identity. Replaying the same tx —
    or claiming the same bill twice — returns the existing row untouched.
    """
    receipt = fetch_receipt(tx_hash)
    _assert_receipt_ok(receipt)
    _assert_receipt_target(receipt)
    event = parse_commit_receipt(receipt)
    _assert_owner_allowed(event.owner, wallets)
    _assert_token_allowed(event.token_address)

    existing = await _by_bill(db, str(event.bill_id))
    if existing is not None:
        if existing.commit_tx_hash != event.tx_hash:
            raise WalletLockError("this bill id is already credited to another transaction")
        return existing

    existing_tx = await _by_commit_tx(db, event.tx_hash)
    if existing_tx is not None:
        return existing_tx

    row = AllowanceCommitModel(
        bill_id=str(event.bill_id),
        identity_id=identity_id,
        wallet_address=event.owner,
        chain_id=int(settings.testnet_chain_id or 0),
        contract_address=configured_address(),
        token_address=event.token_address,
        operator=event.operator,
        amount_wei=str(event.amount_wei),
        amount_usdc=wei_to_usdc(event.amount_wei),
        spent_usdc=0.0,
        reserved_usdc=0.0,
        commit_tx_hash=event.tx_hash,
        block_number=event.block_number,
        state=IDLE,
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    await db.flush()
    logger.info(
        "allowance_commit_claimed",
        identity_id=identity_id,
        bill_id=row.bill_id,
        amount_usdc=row.amount_usdc,
    )
    return row


async def claim_revoke(
    db: AsyncSession,
    *,
    identity_id: str,
    bill_id: str,
    tx_hash: str,
    wallets: set[str],
) -> AllowanceCommitModel:
    """Mark a commitment revoked after the owner's ``revoke()`` transaction."""
    row = await _by_bill(db, bill_id)
    if row is None or row.identity_id != identity_id:
        raise WalletLockError("unknown commitment for this identity")
    if row.state == REVOKED and row.revoke_tx_hash == tx_hash:
        return row

    receipt = fetch_receipt(tx_hash)
    _assert_receipt_ok(receipt)
    _assert_receipt_target(receipt)
    event = parse_revoke_receipt(receipt)
    if str(event.bill_id) != str(bill_id):
        raise WalletLockError("this transaction revokes a different bill")
    _assert_owner_allowed(event.owner, wallets)
    if event.owner.lower() != (row.wallet_address or "").lower():
        raise WalletLockError("this transaction revokes a different wallet's bill")

    row.state = REVOKED
    row.revoke_tx_hash = event.tx_hash
    row.updated_at = datetime.utcnow()
    await db.flush()
    return row


async def sync_commits(db: AsyncSession, identity_id: str) -> list[AllowanceCommitModel]:
    """Read every recorded bill back from the chain (the chain is the truth)."""
    rows = await list_commits(db, identity_id)
    if not rows or not escrow_enabled():
        return rows
    w3 = _web3()
    contract = _contract(w3)
    for row in rows:
        if row.state == REVOKED:
            continue
        try:
            bill = contract.functions.getBill(int(row.bill_id)).call()
            reserved_wei = int(bill[5])
            spent_wei = int(bill[6])
            state_code = int(bill[7])
            backed = contract.functions.isBacked(int(row.bill_id)).call()
        except Exception as exc:  # RPC hiccup: keep the last known values
            logger.warning("allowance_sync_failed", bill_id=row.bill_id, error=str(exc))
            continue
        row.reserved_usdc = wei_to_usdc(reserved_wei)
        row.spent_usdc = wei_to_usdc(spent_wei)
        row.backed = bool(backed)
        row.state = CLOSED if state_code == 2 else IDLE
        row.last_synced_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
    await db.flush()
    return rows


# ----------------------------------------------------- server-side settlement


def _send_tx(fn, account=None):
    """Sign and send with Karma's own operational account, then wait for it."""
    w3 = _web3()
    account = account or _operator_account()
    chain_id = int(settings.testnet_chain_id or 0) or w3.eth.chain_id
    tx = fn.build_transaction(
        {
            "from": account.address,
            "nonce": w3.eth.get_transaction_count(account.address),
            "chainId": chain_id,
        }
    )
    signed = account.sign_transaction(tx)
    raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
    tx_hash = w3.eth.send_raw_transaction(raw)
    receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
    hx = _hexstr(getattr(receipt, "transactionHash", tx_hash))
    if not hx.startswith("0x"):
        hx = "0x" + hx
    return receipt, hx


def scope_hash(scope: str, task_id: str) -> str:
    """bytes32 commitment scope = keccak256("<scope>:<task_id>")."""
    from web3 import Web3

    digest = Web3.keccak(text=f"{scope}:{task_id}").hex()
    return digest if digest.startswith("0x") else "0x" + digest


def proof_hash(proof: str) -> str:
    from web3 import Web3

    if str(proof).startswith("0x"):
        raw = str(proof)
    else:
        digest = Web3.keccak(text=str(proof)).hex()
        raw = digest if digest.startswith("0x") else "0x" + digest
    text = str(raw)
    if len(text) != 66:
        raise WalletLockError("proof hash must be 32 bytes (0x + 64 hex chars)")
    return text


def open_order(
    *,
    buyer_bill_id: str,
    seller_bill_id: str,
    amount_usdc: float,
    stake_usdc: float,
    scope: str,
    task_id: str,
) -> dict[str, Any]:
    """Bind a buyer commitment to a seller stake and submit the proof.

    Runs on Karma's operational account, which the buyer named as ``operator``
    when committing — that is what removes the per-order signature. It can only
    ever *record* an obligation: the money moves later, from the buyer's wallet,
    and only while the buyer's own allowance stands.
    """
    if not escrow_enabled():
        raise WalletLockError(disabled_detail())
    w3 = _web3()
    contract = _contract(w3)
    amount_wei = usdc_to_wei(amount_usdc)
    stake_wei = usdc_to_wei(stake_usdc)

    receipt, bind_tx = _send_tx(
        contract.functions.bind(
            int(buyer_bill_id),
            int(seller_bill_id),
            scope_hash(scope, task_id),
            amount_wei,
            stake_wei,
        )
    )
    events = contract.events.BillsBound().process_receipt(receipt)
    if not events:
        raise WalletLockError("bind() did not emit BillsBound — nothing was bound")
    binding_id = int(events[0]["args"]["bindingId"])
    return {
        "binding_id": binding_id,
        "bind_tx_hash": bind_tx,
        "amount_usdc": float(amount_usdc),
        "stake_usdc": float(stake_usdc),
        "scope_hash": scope_hash(scope, task_id),
    }


def submit_settlement(*, binding_id: int, proof: str) -> dict[str, Any]:
    """Open the dispute window for a bound order on Karma's operational account."""
    if not escrow_enabled():
        raise WalletLockError(disabled_detail())
    w3 = _web3()
    contract = _contract(w3)
    digest = proof_hash(proof)
    receipt, tx = _send_tx(contract.functions.submitSettlement(int(binding_id), digest))
    events = contract.events.SettleSubmitted().process_receipt(receipt)
    pull_after = int(events[0]["args"]["pullAfter"]) if events else 0
    return {"binding_id": int(binding_id), "submit_tx_hash": tx, "proof_hash": digest, "pull_after": pull_after}


def finalize_settlement(*, binding_id: int) -> dict[str, Any]:
    """Execute the pull payer -> payee. Permissionless once the window elapsed."""
    if not escrow_enabled():
        raise WalletLockError(disabled_detail())
    w3 = _web3()
    contract = _contract(w3)
    receipt, tx = _send_tx(contract.functions.finalizeSettlement(int(binding_id)))
    events = contract.events.Settled().process_receipt(receipt)
    paid_usdc = wei_to_usdc(int(events[0]["args"]["amount"])) if events else 0.0
    return {"binding_id": int(binding_id), "finalize_tx_hash": tx, "paid_usdc": paid_usdc}


def finalize_breach(*, binding_id: int) -> dict[str, Any]:
    """Slash the seller stake to the buyer (resolver-only on-chain)."""
    if not escrow_enabled():
        raise WalletLockError(disabled_detail())
    w3 = _web3()
    contract = _contract(w3)
    receipt, tx = _send_tx(contract.functions.finalizeBreach(int(binding_id)))
    events = contract.events.StakeSlashed().process_receipt(receipt)
    slashed_usdc = wei_to_usdc(int(events[0]["args"]["amount"])) if events else 0.0
    return {"binding_id": int(binding_id), "breach_tx_hash": tx, "slashed_usdc": slashed_usdc}