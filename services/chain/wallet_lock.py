"""On-chain wallet locks - verify ``KarmaBilateral.lock()`` receipts, credit the ledger.

Security model
--------------
* The backend never holds, asks for, or transmits a private key, seed phrase or
  mnemonic. Users sign their own ``approve`` + ``lock`` transactions in their
  wallet; this module only *reads* the resulting receipt.
* The credited amount comes from the on-chain ``BillMinted`` event, never from
  the request body, so a client cannot inflate its own credits.
* One bill can be credited exactly once: ``chain_locks`` is keyed by bill id and
  the lock tx hash is unique, so replaying the same transaction is a no-op.
* The minted bill must belong to the wallet signed in for this identity (SIWE),
  so merely observing someone else's lock transaction buys nothing.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Iterable

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import CapacityModel, ChainLockModel
from services.capacity_ledger import assert_can_release_locked_funds

logger = structlog.get_logger(__name__)

# keccak256("BillMinted(uint256,address,address,uint256)")
BILL_MINTED_TOPIC = "0xaeea31ae994ffb59a2beedbf74196f7e404a487119d6c88fdecd397f0347bc70"
# keccak256("BillBurned(uint256,address,uint256,string)")
BILL_BURNED_TOPIC = "0xf66bfe685f0ddfdf9187ffb2739cd480c025d7555be8ef7c98b9d06c4cb1ddbf"


class WalletLockError(ValueError):
    """A user-facing rejection while verifying an on-chain lock or withdrawal."""


@dataclass(frozen=True)
class BillEvent:
    bill_id: int
    owner: str
    token_address: str
    amount_wei: int
    tx_hash: str
    block_number: int | None = None
    reason: str = ""


# ---------------------------------------------------------------- config view


def token_decimals() -> int:
    try:
        return int(settings.settlement_token_decimals)
    except (TypeError, ValueError):
        return 6


def wei_to_usdc(amount_wei: int) -> float:
    return int(amount_wei) / float(10 ** token_decimals())


def usdc_to_wei(amount_usdc: float) -> int:
    return int(round(float(amount_usdc) * (10 ** token_decimals())))


def _missing_chain_config() -> list[str]:
    missing: list[str] = []
    if not settings.chain_wallet_lock_enabled:
        missing.append("CHAIN_WALLET_LOCK_ENABLED")
    if not (settings.karma_bilateral_address or "").strip():
        missing.append("KARMA_BILATERAL_ADDRESS")
    if not (settings.erc20_token_address or "").strip():
        missing.append("ERC20_TOKEN_ADDRESS")
    if not (settings.testnet_rpc_url or "").strip():
        missing.append("TESTNET_RPC_URL")
    return missing


def chain_lock_enabled() -> bool:
    return not _missing_chain_config()


def disabled_detail() -> str:
    missing = _missing_chain_config()
    if not missing:
        return ""
    return "on-chain lock is not configured: " + ", ".join(missing)


def chain_config() -> dict[str, Any]:
    """Everything the console needs to build approve/lock/unlock calldata."""
    return {
        "enabled": chain_lock_enabled(),
        "settlement_mode": settings.settlement_mode,
        "chain_id": int(settings.testnet_chain_id or 0),
        "contract_address": (settings.karma_bilateral_address or "").strip(),
        "token_address": (settings.erc20_token_address or "").strip(),
        "token_decimals": token_decimals(),
        "token_symbol": "USDC",
        "explorer_url": (settings.chain_explorer_url or "").strip(),
        "missing_config": _missing_chain_config(),
    }


# ------------------------------------------------------------ receipt decode


def _field(obj: Any, key: str, default: Any = None) -> Any:
    if obj is None:
        return default
    if isinstance(obj, dict):
        value = obj.get(key, default)
    else:
        value = getattr(obj, key, default)
    return value


def _hexstr(value: Any) -> str:
    if isinstance(value, (bytes, bytearray)):
        return "0x" + bytes(value).hex()
    text = str(value or "").strip().lower()
    if text and not text.startswith("0x"):
        text = "0x" + text
    return text


def _hex_bytes(value: Any) -> bytes:
    text = _hexstr(value)
    text = text[2:] if text.startswith("0x") else text
    if not text:
        return b""
    if len(text) % 2:
        text = "0" + text
    try:
        return bytes.fromhex(text)
    except ValueError:
        return b""


def _hex_int(value: Any) -> int:
    if isinstance(value, int):
        return value
    text = str(value or "0x0").strip()
    if not text:
        return 0
    return int(text, 16) if text.startswith("0x") else int(text)


def _topic_address(topic: Any) -> str:
    text = _hexstr(topic)[2:]
    return "0x" + text[-40:].lower() if text else ""


def _decode_string_at(data: bytes, offset: int) -> str:
    if offset < 0 or offset + 32 > len(data):
        return ""
    length = int.from_bytes(data[offset:offset + 32], "big")
    if length <= 0 or offset + 32 + length > len(data):
        return ""
    return data[offset + 32:offset + 32 + length].decode("utf-8", "replace")


def _receipt_status(receipt: Any) -> int:
    status = _field(receipt, "status")
    if status is None:
        return 1
    return int(status)


def _assert_receipt_ok(receipt: Any, *, contract_address: str, action: str) -> str:
    if _receipt_status(receipt) != 1:
        raise WalletLockError(f"{action} transaction reverted on-chain (receipt status != 1)")
    contract = (contract_address or "").strip().lower()
    to = str(_field(receipt, "to", "") or "").strip().lower()
    if contract and to != contract:
        raise WalletLockError(f"{action} transaction was not sent to the Karma contract ({contract})")
    return contract


def _iter_logs(receipt: Any, contract: str) -> Iterable[tuple[list[str], bytes]]:
    for log in _field(receipt, "logs", []) or []:
        topics = [_hexstr(t) for t in (_field(log, "topics", []) or [])]
        address = str(_field(log, "address", "") or "").strip().lower()
        if contract and address != contract:
            continue
        yield topics, _hex_bytes(_field(log, "data", "0x"))


def decode_bill_minted(
    receipt: Any,
    *,
    contract_address: str,
    expected_token: str | None = None,
) -> BillEvent:
    """Read the ``BillMinted`` event out of a ``lock()`` receipt."""
    contract = _assert_receipt_ok(receipt, contract_address=contract_address, action="lock")
    for topics, data in _iter_logs(receipt, contract):
        if not topics or topics[0] != BILL_MINTED_TOPIC or len(topics) < 3 or len(data) < 64:
            continue
        token_address = "0x" + data[12:32].hex()
        if expected_token and token_address.lower() != str(expected_token).strip().lower():
            raise WalletLockError(
                "bill was minted in an unexpected token "
                f"({token_address}) — expected the configured USDC contract"
            )
        return BillEvent(
            bill_id=_hex_int(topics[1]),
            owner=_topic_address(topics[2]),
            token_address=token_address,
            amount_wei=int.from_bytes(data[32:64], "big"),
            tx_hash=_hexstr(_field(receipt, "transactionHash", "")),
            block_number=_field(receipt, "blockNumber"),
        )
    raise WalletLockError("no BillMinted event found in this transaction — not a Karma lock()")


def decode_bill_burned(
    receipt: Any,
    *,
    contract_address: str,
    expected_reason: str | None = "unlocked",
) -> BillEvent:
    """Read the ``BillBurned`` event out of an ``unlock()`` receipt."""
    contract = _assert_receipt_ok(receipt, contract_address=contract_address, action="unlock")
    for topics, data in _iter_logs(receipt, contract):
        if not topics or topics[0] != BILL_BURNED_TOPIC or len(topics) < 3 or len(data) < 64:
            continue
        amount_wei = int.from_bytes(data[0:32], "big")
        reason_offset = int.from_bytes(data[32:64], "big")
        reason = _decode_string_at(data, reason_offset)
        if expected_reason and reason and reason != expected_reason:
            raise WalletLockError(
                f"bill was burned by '{reason}', not withdrawn — the funds left a binding"
            )
        return BillEvent(
            bill_id=_hex_int(topics[1]),
            owner=_topic_address(topics[2]),
            token_address="",
            amount_wei=amount_wei,
            tx_hash=_hexstr(_field(receipt, "transactionHash", "")),
            block_number=_field(receipt, "blockNumber"),
            reason=reason,
        )
    raise WalletLockError("no BillBurned event found in this transaction — not a Karma unlock()")


# ------------------------------------------------------------------- web3 io


def _web3():
    if not (settings.testnet_rpc_url or "").strip():
        raise WalletLockError(disabled_detail() or "TESTNET_RPC_URL not set")
    from web3 import Web3

    return Web3(Web3.HTTPProvider(settings.testnet_rpc_url, request_kwargs={"timeout": 20}))


def fetch_receipt(tx_hash: str) -> Any:
    w3 = _web3()
    try:
        receipt = w3.eth.get_transaction_receipt(tx_hash)
    except Exception as exc:  # TransactionNotFound / connection problems
        raise WalletLockError(
            "transaction receipt is not available yet — mine and retry in a few seconds"
        ) from exc
    if receipt is None:
        raise WalletLockError("transaction is not mined yet — retry in a few seconds")
    return receipt


# ---------------------------------------------------------------- ledger glue


async def _ensure_capacity(db: AsyncSession, identity_id: str) -> CapacityModel:
    row = await db.get(CapacityModel, identity_id)
    if row is not None:
        return row
    row = CapacityModel(
        identity_id=identity_id,
        profile_id=None,
        total_locked_usdc=0.0,
        total_bill_credits=0.0,
        available_credits=0.0,
        reserved_credits=0.0,
        in_progress_credits=0.0,
        confirmed_progress_credits=0.0,
        disputed_credits=0.0,
        pending_settlement_credits=0.0,
        burned_credits=0.0,
        released_credits=0.0,
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    return row


async def _credit_capacity(db: AsyncSession, identity_id: str, amount_usdc: float) -> CapacityModel:
    row = await _ensure_capacity(db, identity_id)
    row.total_locked_usdc += amount_usdc
    row.total_bill_credits += amount_usdc
    row.available_credits += amount_usdc
    row.updated_at = datetime.utcnow()
    return row


async def _debit_capacity(db: AsyncSession, identity_id: str, amount_usdc: float) -> CapacityModel:
    row = await _ensure_capacity(db, identity_id)
    from core.schemas import CapacityState

    before = CapacityState(
        identity_id=row.identity_id,
        profile_id=row.profile_id,
        total_locked_usdc=row.total_locked_usdc,
        total_bill_credits=row.total_bill_credits,
        available_credits=row.available_credits,
        reserved_credits=row.reserved_credits,
        in_progress_credits=row.in_progress_credits,
        confirmed_progress_credits=row.confirmed_progress_credits,
        disputed_credits=row.disputed_credits,
        pending_settlement_credits=row.pending_settlement_credits,
        burned_credits=row.burned_credits,
        released_credits=row.released_credits,
    )
    try:
        assert_can_release_locked_funds(before, amount_usdc)
    except ValueError as exc:
        raise WalletLockError(str(exc)) from exc
    row.available_credits -= amount_usdc
    row.total_bill_credits -= amount_usdc
    row.total_locked_usdc -= amount_usdc
    row.released_credits += amount_usdc
    row.updated_at = datetime.utcnow()
    return row


async def _find_by_tx(db: AsyncSession, tx_hash: str) -> ChainLockModel | None:
    result = await db.execute(select(ChainLockModel).where(ChainLockModel.lock_tx_hash == tx_hash))
    return result.scalar_one_or_none()


async def list_locks(db: AsyncSession, identity_id: str) -> list[ChainLockModel]:
    result = await db.execute(
        select(ChainLockModel)
        .where(ChainLockModel.identity_id == identity_id)
        .order_by(ChainLockModel.created_at.desc())
    )
    return list(result.scalars().all())


def _wallets_of(identity_id: str) -> set[str]:
    """Wallets SIWE proved for this identity (and its master identity, if any)."""
    from services.identity_gateway import store

    found: set[str] = set()
    ident = store.get_by_id(identity_id)
    if ident is not None:
        found.add(str(getattr(ident, "wallet", "") or "").strip().lower())
        parent_id = getattr(ident, "parent_identity_id", None)
        if parent_id:
            parent = store.get_by_id(str(parent_id))
            if parent is not None:
                found.add(str(getattr(parent, "wallet", "") or "").strip().lower())
    return {w for w in found if w}


async def allowed_wallets(db: AsyncSession, identity_id: str) -> set[str]:
    """Wallets allowed to own a bill credited to ``identity_id``."""
    from services.identity_wallet_binding import get_bound_wallet

    wallets = _wallets_of(identity_id)
    bound = await get_bound_wallet(db, identity_id)
    if bound:
        wallets.add(str(bound).strip().lower())
    return wallets


def _assert_owner_allowed(event: BillEvent, wallets: set[str]) -> None:
    if not wallets:
        raise WalletLockError(
            "cannot verify wallet ownership for this identity — connect the wallet in "
            "the Console (SIWE) and retry"
        )
    if event.owner.lower() not in wallets:
        raise WalletLockError(
            "this lock belongs to a wallet that is not signed in for this identity"
        )


# --------------------------------------------------------------- public writes


async def claim_lock_bill(
    db: AsyncSession,
    *,
    identity_id: str,
    tx_hash: str,
    wallets: set[str] | None = None,
) -> ChainLockModel:
    """Verify a ``lock()`` receipt and credit it to ``identity_id`` exactly once."""
    if not chain_lock_enabled():
        raise WalletLockError(disabled_detail())
    tx = (tx_hash or "").strip().lower()
    if not tx.startswith("0x") or len(tx) != 66:
        raise WalletLockError("tx_hash must be a 32-byte 0x-prefixed hex string")

    existing = await _find_by_tx(db, tx)
    if existing is not None:
        return existing

    allowed = wallets if wallets is not None else await allowed_wallets(db, identity_id)
    receipt = fetch_receipt(tx)
    event = decode_bill_minted(
        receipt,
        contract_address=settings.karma_bilateral_address,
        expected_token=settings.erc20_token_address,
    )
    _assert_owner_allowed(event, allowed)
    if event.amount_wei <= 0:
        raise WalletLockError("bill amount is zero — nothing to credit")

    same_bill = await db.get(ChainLockModel, str(event.bill_id))
    if same_bill is not None:
        return same_bill

    amount_usdc = wei_to_usdc(event.amount_wei)
    row = ChainLockModel(
        bill_id=str(event.bill_id),
        identity_id=identity_id,
        wallet_address=event.owner.lower(),
        chain_id=int(settings.testnet_chain_id or 0),
        contract_address=str(settings.karma_bilateral_address or "").strip().lower(),
        token_address=event.token_address.lower(),
        amount_wei=str(event.amount_wei),
        amount_usdc=amount_usdc,
        lock_tx_hash=tx,
        block_number=int(event.block_number) if event.block_number is not None else None,
        state="locked",
        created_at=datetime.utcnow(),
        updated_at=datetime.utcnow(),
    )
    db.add(row)
    try:
        await db.flush()
    except IntegrityError:
        await db.rollback()
        again = await _find_by_tx(db, tx)
        if again is not None:
            return again
        raise WalletLockError("this bill or transaction was already credited") from None

    await _credit_capacity(db, identity_id, amount_usdc)
    await db.flush()
    logger.info(
        "chain_lock_credited",
        identity_id=identity_id,
        bill_id=event.bill_id,
        amount_usdc=amount_usdc,
        tx_hash=tx,
    )
    return row


async def claim_unlock(
    db: AsyncSession,
    *,
    identity_id: str,
    bill_id: str,
    tx_hash: str,
    wallets: set[str] | None = None,
) -> ChainLockModel:
    """Verify an ``unlock()`` receipt and release the matching ledger credits."""
    if not chain_lock_enabled():
        raise WalletLockError(disabled_detail())
    tx = (tx_hash or "").strip().lower()
    if not tx.startswith("0x") or len(tx) != 66:
        raise WalletLockError("tx_hash must be a 32-byte 0x-prefixed hex string")

    row = await db.get(ChainLockModel, str(bill_id))
    if row is None or row.identity_id != identity_id:
        raise WalletLockError("no on-chain lock is recorded for this bill on this identity")
    if row.state != "locked":
        raise WalletLockError("this bill is already released")

    allowed = wallets if wallets is not None else await allowed_wallets(db, identity_id)
    receipt = fetch_receipt(tx)
    event = decode_bill_burned(receipt, contract_address=settings.karma_bilateral_address)
    _assert_owner_allowed(event, allowed)
    if event.bill_id != int(row.bill_id):
        raise WalletLockError("this transaction burned a different bill")

    await _debit_capacity(db, identity_id, row.amount_usdc)
    row.state = "released"
    row.unlock_tx_hash = tx
    row.updated_at = datetime.utcnow()
    await db.flush()
    logger.info(
        "chain_lock_released",
        identity_id=identity_id,
        bill_id=row.bill_id,
        tx_hash=tx,
    )
    return row
