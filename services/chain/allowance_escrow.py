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

# Every event Karma reads, with its real field names: the ABI below is derived
# from this one table, so a name/signature mismatch is impossible.
EVENT_FIELDS: dict[str, list[tuple[str, str, bool]]] = {
    "BillCommitted": [
        ("billId", "uint256", True),
        ("owner", "address", True),
        ("operator", "address", True),
        ("token", "address", False),
        ("amount", "uint256", False),
    ],
    "BillRevoked": [
        ("billId", "uint256", True),
        ("owner", "address", True),
        ("unspent", "uint256", False),
    ],
    "BillsBound": [
        ("bindingId", "uint256", True),
        ("buyerBillId", "uint256", False),
        ("sellerBillId", "uint256", False),
        ("scopeHash", "bytes32", False),
        ("amount", "uint256", False),
        ("stakeAmount", "uint256", False),
    ],
    "SettleSubmitted": [
        ("bindingId", "uint256", True),
        ("proofHash", "bytes32", False),
        ("pullAfter", "uint256", False),
    ],
    "Settled": [
        ("bindingId", "uint256", True),
        ("from", "address", False),
        ("to", "address", False),
        ("token", "address", False),
        ("amount", "uint256", False),
    ],
    "StakeSlashed": [
        ("bindingId", "uint256", True),
        ("from", "address", False),
        ("to", "address", False),
        ("token", "address", False),
        ("amount", "uint256", False),
    ],
}


def event_signature(name: str) -> str:
    return name + "(" + ",".join(typ for _, typ, _ in EVENT_FIELDS[name]) + ")"


EVENTS = [event_signature(name) for name in EVENT_FIELDS]

COMMITTED_SIG = event_signature("BillCommitted")
REVOKED_SIG = event_signature("BillRevoked")
BOUND_SIG = event_signature("BillsBound")
SUBMITTED_SIG = event_signature("SettleSubmitted")
SETTLED_SIG = event_signature("Settled")
SLASHED_SIG = event_signature("StakeSlashed")

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
        "name": "cancelBinding",
        "type": "function",
        "stateMutability": "nonpayable",
        "inputs": [{"name": "bindingId", "type": "uint256"}],
        "outputs": [],
    },
    {
        "name": "getBinding",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "bindingId", "type": "uint256"}],
        "outputs": [
            {
                "name": "",
                "type": "tuple",
                "components": [
                    {"name": "bindingId", "type": "uint256"},
                    {"name": "buyerBillId", "type": "uint256"},
                    {"name": "sellerBillId", "type": "uint256"},
                    {"name": "scopeHash", "type": "bytes32"},
                    {"name": "amount", "type": "uint256"},
                    {"name": "stakeAmount", "type": "uint256"},
                    {"name": "state", "type": "uint8"},
                    {"name": "createdAt", "type": "uint256"},
                    {"name": "settleAfter", "type": "uint256"},
                    {"name": "proofHash", "type": "bytes32"},
                    {"name": "closedAt", "type": "uint256"},
                ],
            }
        ],
    },    {
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
        "name": "checkNoCustody",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "token", "type": "address"}],
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


_ABI_EVENTS = [
    {
        "name": name,
        "type": "event",
        "anonymous": False,
        "inputs": [
            {"name": field, "type": typ, "indexed": indexed}
            for field, typ, indexed in fields
        ],
    }
    for name, fields in EVENT_FIELDS.items()
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
    want = _topic(COMMITTED_SIG)
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
    want = _topic(REVOKED_SIG)
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

def _logs_matching(receipt: Any, signature: str) -> list[Any]:
    want = _topic(signature)
    out = []
    for log in _field(receipt, "logs", []) or []:
        topics = list(_field(log, "topics", []) or [])
        if topics and _hexstr(topics[0]).lower() == want:
            out.append(log)
    return out


def _words_of(log: Any) -> list[str]:
    return _data_words(_field(log, "data", "0x"))


def parse_bills_bound(receipt: Any) -> dict[str, Any]:
    """Read ``BillsBound`` without trusting ABI field names.

    The first version of ``open_order`` indexed ``args["bindingId"]`` and the
    ABI's auto-generated names made that a KeyError *after* the bind transaction
    had already landed — leaving an on-chain reservation with no local record.
    Decoding raw words means the transaction and the record can never diverge.
    """
    logs = _logs_matching(receipt, BOUND_SIG)
    if not logs:
        raise WalletLockError("bind() did not emit BillsBound — nothing was bound")
    log = logs[0]
    topics = list(_field(log, "topics", []) or [])
    words = _words_of(log)
    if len(words) < 5:
        raise WalletLockError("BillsBound log is malformed")
    return {
        "binding_id": _topic_int(topics[1]),
        "buyer_bill_id": _word_to_int(words[0]),
        "seller_bill_id": _word_to_int(words[1]),
        "scope_hash": "0x" + words[2],
        "amount_wei": _word_to_int(words[3]),
        "stake_wei": _word_to_int(words[4]),
    }


def parse_settle_submitted(receipt: Any) -> dict[str, Any]:
    logs = _logs_matching(receipt, SUBMITTED_SIG)
    if not logs:
        raise WalletLockError("submitSettlement() did not emit SettleSubmitted")
    topics = list(_field(logs[0], "topics", []) or [])
    words = _words_of(logs[0])
    return {
        "binding_id": _topic_int(topics[1]),
        "proof_hash": "0x" + (words[0] if words else ""),
        "pull_after": _word_to_int(words[1]) if len(words) > 1 else 0,
    }


def parse_settled(receipt: Any) -> dict[str, Any]:
    logs = _logs_matching(receipt, SETTLED_SIG)
    if not logs:
        raise WalletLockError("finalizeSettlement() did not emit Settled")
    topics = list(_field(logs[0], "topics", []) or [])
    words = _words_of(logs[0])
    return {
        "binding_id": _topic_int(topics[1]),
        "from": "0x" + words[0][-40:].lower(),
        "to": "0x" + words[1][-40:].lower(),
        "token": "0x" + words[2][-40:].lower(),
        "amount_wei": _word_to_int(words[3]),
    }


def parse_slashed(receipt: Any) -> dict[str, Any]:
    logs = _logs_matching(receipt, SLASHED_SIG)
    if not logs:
        raise WalletLockError("finalizeBreach() did not emit StakeSlashed")
    topics = list(_field(logs[0], "topics", []) or [])
    words = _words_of(logs[0])
    return {
        "binding_id": _topic_int(topics[1]),
        "from": "0x" + words[0][-40:].lower(),
        "to": "0x" + words[1][-40:].lower(),
        "token": "0x" + words[2][-40:].lower(),
        "amount_wei": _word_to_int(words[3]),
    }

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
    overrides: dict[str, Any] = {
        "from": account.address,
        "nonce": w3.eth.get_transaction_count(account.address),
        "chainId": chain_id,
    }
    cap_wei = int(max(0.0, float(settings.settlement_max_gas_price_gwei or 0.0)) * 1e9)
    if cap_wei:
        try:
            quoted = int(w3.eth.gas_price or 0)
        except Exception:  # a flaky RPC must never block a settlement
            quoted = 0
        # Never bid above the ceiling: the operator account is small on purpose.
        if not quoted or quoted > cap_wei:
            overrides["maxFeePerGas"] = cap_wei
            overrides["maxPriorityFeePerGas"] = min(cap_wei, 300_000_000)
    tx = fn.build_transaction(overrides)
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
    bound = parse_bills_bound(receipt)
    binding_id = int(bound["binding_id"])
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
    pull_after = int(parse_settle_submitted(receipt)["pull_after"])
    return {"binding_id": int(binding_id), "submit_tx_hash": tx, "proof_hash": digest, "pull_after": pull_after}


def finalize_settlement(*, binding_id: int) -> dict[str, Any]:
    """Execute the pull payer -> payee. Permissionless once the window elapsed."""
    if not escrow_enabled():
        raise WalletLockError(disabled_detail())
    w3 = _web3()
    contract = _contract(w3)
    receipt, tx = _send_tx(contract.functions.finalizeSettlement(int(binding_id)))
    paid_usdc = wei_to_usdc(int(parse_settled(receipt)["amount_wei"]))
    return {"binding_id": int(binding_id), "finalize_tx_hash": tx, "paid_usdc": paid_usdc}


def finalize_breach(*, binding_id: int) -> dict[str, Any]:
    """Slash the seller stake to the buyer (resolver-only on-chain)."""
    if not escrow_enabled():
        raise WalletLockError(disabled_detail())
    w3 = _web3()
    contract = _contract(w3)
    receipt, tx = _send_tx(contract.functions.finalizeBreach(int(binding_id)))
    slashed_usdc = wei_to_usdc(int(parse_slashed(receipt)["amount_wei"]))
    return {"binding_id": int(binding_id), "breach_tx_hash": tx, "slashed_usdc": slashed_usdc}


def cancel_binding(*, binding_id: int) -> dict[str, Any]:
    """Release an orphaned reservation (e.g. a bind whose caller died).

    Any party — or their operator — may cancel while nothing has been submitted,
    so a reservation can never be stranded by a crashed process.
    """
    if not escrow_enabled():
        raise WalletLockError(disabled_detail())
    w3 = _web3()
    contract = _contract(w3)
    receipt, tx = _send_tx(contract.functions.cancelBinding(int(binding_id)))
    return {"binding_id": int(binding_id), "cancel_tx_hash": tx, "status": int(_field(receipt, "status", 1) or 1)}