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
import threading
import time
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from config.settings import settings
from db.models.orm import AllowanceCommitModel, CapacityModel, EscrowBindingModel
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
# 一条承诺不再贡献责任额度的状态：已撤销 / 链上已关闭。
_NON_LIVE_STATES = (REVOKED, CLOSED)

# 自愈：链上可能比台账先变（用户撤销了承诺却关掉了页面）。同一个身份最多每
# 这么久回链上一次，防止被放弃的账单把锁仓数字撑大。
_RESYNC_INTERVAL_SECONDS = 600

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
#: 自定义错误。不放进 ABI 的话，链上 revert 回给调用方的是一串裸 hex
#: （`('0xcd51b4a1...', '0xcd51b4a1...')`），运维和用户都读不出到底差在哪。
_ABI_ERRORS = [
    {"type": "error", "name": "TokenNotAllowed", "inputs": []},
    {"type": "error", "name": "ZeroAmount", "inputs": []},
    {"type": "error", "name": "ZeroAddress", "inputs": []},
    {"type": "error", "name": "TokenMismatch", "inputs": []},
    {"type": "error", "name": "SameOwner", "inputs": []},
    {"type": "error", "name": "PullFailed", "inputs": []},
    {"type": "error", "name": "CustodyViolation", "inputs": []},
    {"type": "error", "name": "NotSettlementParty", "inputs": []},
    {"type": "error", "name": "NotResolver", "inputs": []},
    {"type": "error", "name": "NotBillOwner", "inputs": [{"name": "billId", "type": "uint256"}]},
    {"type": "error", "name": "NotBillOperator", "inputs": [{"name": "billId", "type": "uint256"}]},
    {"type": "error", "name": "WrongBillState", "inputs": [{"name": "billId", "type": "uint256"}]},
    {"type": "error", "name": "UnknownBinding", "inputs": [{"name": "bindingId", "type": "uint256"}]},
    {"type": "error", "name": "WrongBindingState", "inputs": [{"name": "bindingId", "type": "uint256"}]},
    {"type": "error", "name": "SettleDelayActive", "inputs": [{"name": "settleAfter", "type": "uint256"}]},
    {"type": "error", "name": "ReservationActive", "inputs": [{"name": "reserved", "type": "uint256"}]},
    {
        "type": "error",
        "name": "InsufficientAllowance",
        "inputs": [{"name": "have", "type": "uint256"}, {"name": "need", "type": "uint256"}],
    },
    {
        "type": "error",
        "name": "InsufficientCommitment",
        "inputs": [{"name": "available", "type": "uint256"}, {"name": "need", "type": "uint256"}],
    },
]


ABI = _ABI_FUNCTIONS + _ABI_EVENTS + _ABI_ERRORS
ABI_JSON = json.dumps(ABI)


# ----------------------------------------------------------------- config view


def configured_address() -> str:
    return (settings.allowance_escrow_address or "").strip()


def normalize_address(value: str | None) -> str:
    return (value or "").strip().lower()


def is_current_contract(value: str | None) -> bool:
    """这张账单 / 这条绑定，是不是落在**当前**这台托管合约上。

    账单和绑定都只属于具体某台合约：合约换地址（v2 → v3）之后，旧合约上的
    bill id 拿到新合约里 ``available()`` 直接 revert（UnknownBill）、旧 binding
    id 拿到新合约里 ``getBinding()`` 也是 revert（UnknownBinding）。2026-09-20
    的实测里，前者把 ``/lock`` 打成了 500，后者足以把用户的钱永久卡死。

    新订单**只能**开在当前合约上：旧合约（v2）没有「验证通过才开窗」这道闸
    （``submitSettlement`` 谁都能调），把新单开上去等于把 F9-1 那个洞又打开。
    """
    configured = normalize_address(configured_address())
    return bool(configured) and normalize_address(value) == configured


def bill_contract(row: Any) -> str:
    """这张账单记在哪台合约上（历史行没有地址时按当前合约处理）。"""
    return (getattr(row, "contract_address", "") or "").strip() or configured_address()


def bill_is_spendable(row: Any) -> bool:
    """这张账单能不能被当前这套托管流程花掉。

    没配托管合约（纯台账模式）时不存在「哪台合约」的问题 —— 那种部署里链上授权额
    本身就不存在，看的是台账；配了就必须是**当前**这台：旧合约的账单在新合约里
    根本不存在（``UnknownBill`` revert），而且旧合约没有「验证通过才开窗」那道闸
    （``submitSettlement`` 谁都能调），新单开上去等于把 F9-1 的洞重新打开。
    """
    if not escrow_enabled():
        return True
    return is_current_contract(bill_contract(row))


def binding_contract(row: Any) -> str:
    """这条绑定该去哪台合约上收尾（历史行没有地址时按当前合约处理）。"""
    return (getattr(row, "contract_address", "") or "").strip() or configured_address()


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

# ------------------------------------------------------- revert 可读化


_FRIENDLY_REVERTS = {
    "WrongBindingState": "这条绑定在链上已经不是「待结算」状态（已结算/已取消/已罚没），不能重复执行",
    "UnknownBinding": "链上没有这条绑定",
    "SettleDelayActive": "挑战窗口还没到点，现在还不能划款",
    "InsufficientCommitment": "链上可用锁仓额度不足，请先补足锁仓或提高对该托管合约的授权额",
    "InsufficientAllowance": "钱包对该托管合约的 USDC 授权额不足（可能已被撤销或调低）",
    "WrongBillState": "这张账单已经关闭（被撤销或已用尽），不能再绑定",
    "ReservationActive": "这张账单还被一笔未完成的绑定占着，请先撤销那笔绑定",
    "NotResolver": "只有 Karma 的争议裁决账户可以执行罚没",
    "NotBillOperator": "调用方不是这张账单的授权操作者",
    "NotBillOwner": "调用方不是这张账单的所有者",
    "NotSettlementParty": "调用方不是这一单的结算当事方",
    "SameOwner": "买方和卖方是同一个钱包，不能自己跟自己绑定",
    "TokenMismatch": "买卖双方账单用的不是同一个代币",
    "PullFailed": "划款失败：付款方钱包余额或授权额不足",
    "CustodyViolation": "托管合约不应该持有任何资金（非托管不变量被打破）",
    "ZeroAmount": "金额不能为 0",
    "TokenNotAllowed": "这个代币不在托管合约的白名单里",
}

_REVERT_SELECTORS: dict[str, dict[str, Any]] = {}


def _revert_selector_map() -> dict[str, dict[str, Any]]:
    if not _REVERT_SELECTORS:
        from web3 import Web3

        for entry in _ABI_ERRORS:
            signature = "%s(%s)" % (
                entry["name"],
                ",".join(i["type"] for i in (entry.get("inputs") or [])),
            )
            digest = Web3.keccak(text=signature).hex()
            selector = digest if digest.startswith("0x") else "0x" + digest
            _REVERT_SELECTORS[selector[:10].lower()] = entry
    return _REVERT_SELECTORS


def describe_revert(exc: BaseException) -> str | None:
    """把合约自定义 error 解成 ``名字(参数)``。解不出来返回 None。"""
    raw = getattr(exc, "data", None)
    if not (isinstance(raw, str) and raw.startswith("0x") and len(raw) >= 10):
        raw = None
        for arg in getattr(exc, "args", ()) or ():
            if isinstance(arg, str) and arg.startswith("0x") and len(arg) >= 10:
                raw = arg
                break
    if not raw:
        return None
    entry = _revert_selector_map().get(raw[:10].lower())
    if entry is None:
        return None
    body = raw[10:]
    words = [body[i : i + 64] for i in range(0, len(body), 64)]
    values: list[str] = []
    for index, spec in enumerate(entry.get("inputs") or []):
        word = words[index] if index < len(words) and words[index] else "0" * 64
        kind = str(spec.get("type") or "")
        if kind == "address":
            values.append("0x" + word[-40:])
        elif kind.startswith("uint") or kind.startswith("int"):
            values.append(str(int(word, 16)))
        elif kind == "bool":
            values.append(str(bool(int(word, 16))))
        else:
            values.append("0x" + word)
    return "%s(%s)" % (entry["name"], ", ".join(values))


def chain_error(exc: BaseException) -> "WalletLockError":
    """链上失败 -> 用户看得懂的一句话（附合约原文）。"""
    detail = describe_revert(exc)
    name = detail.split("(", 1)[0] if detail else ""
    friendly = _FRIENDLY_REVERTS.get(name)
    if friendly:
        return WalletLockError(friendly + ("（合约：%s）" % detail if detail else ""))
    if detail:
        return WalletLockError("合约拒绝了这笔交易：%s" % detail)
    return WalletLockError("链上交易失败：%s: %s" % (type(exc).__name__, exc))


def _replay_revert(w3, tx: dict, receipt: Any) -> BaseException:
    """交易已经在链上 revert 了（status=0）：回放一次把 revert 原因捞出来。"""
    replay = {k: v for k, v in dict(tx).items() if k not in ("nonce", "chainId")}
    try:
        w3.eth.call(replay, block_identifier=_field(receipt, "blockNumber"))
    except Exception as exc:  # noqa: BLE001 - 这次失败本身就是要读的信息
        return exc
    return WalletLockError("链上交易被 revert（合约没给出原因）")


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


def _escrow_emitted(receipt: Any, signature: str) -> bool:
    """True when *our* escrow address itself emitted ``signature`` in this receipt."""
    want = configured_address().lower()
    if not want:
        return False
    topic = _topic(signature)
    for log in _field(receipt, "logs", []) or []:
        address = _hexstr(_field(log, "address", "")).lower()
        if address != want:
            continue
        topics = list(_field(log, "topics", []) or [])
        if topics and _hexstr(topics[0]).lower() == topic:
            return True
    return False


def _assert_receipt_target(receipt: Any, *signatures: str) -> None:
    """The transaction must have reached *our* escrow, not some look-alike.

    A plain wallet calls the escrow directly, so ``receipt.to`` *is* the escrow.
    Smart-account wallets (MetaMask Delegation Toolkit, Safe, ERC-4337 bundlers)
    instead route the very same call through a forwarder: ``receipt.to`` becomes
    the forwarder while the escrow is still the contract that emitted the event.
    Accept either shape, but in the forwarded case insist the event came *from our
    address*, so a look-alike contract cannot forge a commitment.
    """
    want = configured_address()
    if not want:
        return
    got = _hexstr(_field(receipt, "to", "")).lower()
    if got and got == want.lower():
        return
    if any(_escrow_emitted(receipt, signature) for signature in signatures):
        return
    raise WalletLockError(
        "this transaction did not reach the Karma escrow — no Karma event was "
        "emitted, so there is nothing to credit"
    )


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
    _assert_receipt_target(receipt, COMMITTED_SIG)
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
    _assert_receipt_target(receipt, REVOKED_SIG)
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
    for row in rows:
        if row.state == REVOKED:
            continue
        # 每条账单去**它自己那台**合约上读。合约换过地址之后，旧账单在新合约里
        # 根本不存在（UnknownBill revert），过去这一步会一直被当成 RPC 抖动。
        contract = _contract(w3, bill_contract(row))
        try:
            bill = contract.functions.getBill(int(row.bill_id)).call()
            reserved_wei = int(bill[5])
            spent_wei = int(bill[6])
            state_code = int(bill[7])
            backed = contract.functions.isBacked(int(row.bill_id)).call()
        except Exception as exc:  # RPC hiccup: keep the last known values
            logger.warning(
                "allowance_sync_failed",
                bill_id=row.bill_id,
                contract=bill_contract(row),
                error=str(exc),
            )
            continue
        row.reserved_usdc = wei_to_usdc(reserved_wei)
        row.spent_usdc = wei_to_usdc(spent_wei)
        row.backed = bool(backed)
        row.state = CLOSED if state_code == 2 else IDLE
        row.last_synced_at = datetime.utcnow()
        row.updated_at = datetime.utcnow()
    await db.flush()
    return rows


# ------------------------------------------------------- aggregate backing

#: 账单共用同一条 ERC-20 授权，合约的 ``isBacked`` 只看「单张账单 ≤ 授权额」。
#: 所以「账单合计 170、授权只有 50」在链上逐张看全都是 backed，真到划款时只划得动 50。
#: 下面这组函数把同一钱包、同一代币下的所有账单放在一起，按最早优先把授权额分下去，
#: 得到「这张账单到底有多少钱是真划得动的」。
_ERC20_ALLOWANCE_ABI = [
    {
        "name": "allowance",
        "type": "function",
        "stateMutability": "view",
        "inputs": [{"name": "owner", "type": "address"}, {"name": "spender", "type": "address"}],
        "outputs": [{"name": "", "type": "uint256"}],
    }
]


def _bill_sort_key(bill_id: str) -> tuple[int, str]:
    """账单号升序 = 承诺时间升序（合约里的自增 id）。"""
    try:
        return (int(bill_id), "")
    except (TypeError, ValueError):
        return (2**63, str(bill_id))


def allocate_allowance(
    bills_oldest_first: list[tuple[str, float]], allowance_usdc: float
) -> dict[str, float]:
    """把**一条**共享授权额按最早优先分配给多张账单。

    返回 ``{bill_id: 真正划得动的金额}``。最后那些分不到的账单拿到 0 —— 它们仍然
    是「open」，但链上划不动，调用方必须把它们当作没有额度。
    """
    remaining = max(0.0, float(allowance_usdc or 0.0))
    secured: dict[str, float] = {}
    for bill_id, live in bills_oldest_first:
        take = min(max(0.0, float(live or 0.0)), remaining)
        secured[str(bill_id)] = round(take, 6)
        remaining = round(remaining - take, 6)
    return secured


def assert_room(role: str, need_usdc: float, secured_usdc: float) -> None:
    """这一单要花的钱，必须真的在链上划得动，否则不该 bind。"""
    need = float(need_usdc or 0.0)
    have = float(secured_usdc or 0.0)
    if need - have > 1e-9:
        raise WalletLockError(
            f"insufficient on-chain backing for the {role} commitment: this order needs "
            f"{need:g} USDC but only {have:g} USDC of the wallet's ERC-20 allowance is "
            f"still free for it. Raise the allowance to the escrow from the {role}'s "
            f"wallet (or release unneeded commitments) and retry."
        )


def _erc20_allowance_wei(w3, token: str, owner: str, spender: str) -> int:
    erc = w3.eth.contract(
        address=w3.to_checksum_address(token), abi=_ERC20_ALLOWANCE_ABI
    )
    return int(
        erc.functions.allowance(
            w3.to_checksum_address(owner), w3.to_checksum_address(spender)
        ).call()
    )


async def backing_report(db: AsyncSession, identity_id: str) -> dict[str, Any]:
    """这个身份记在账上的承诺，链上到底有多少是划得动的。

    与 ``isBacked`` 的区别：``isBacked`` 回答「这一张账单是否 ≤ 授权额」，
    本函数回答「这个钱包所有账单加起来是否 ≤ 授权额」。

    两个标志位必须分开看，调用方靠它们决定「拦」还是「等」：

    * ``enforced``      —— 这个部署真的配了托管合约，链上授权额就是硬约束；
    * ``chain_checked`` —— 授权额**这一次**真的读到了。
      ``enforced and not chain_checked`` 就是 RPC 抖动：读不到链不能声称担保，
      但也不能因为一次网络错误把用户已经锁进来的额度当成 0。

    担保是**按合约**算的：ERC-20 授权发给具体的 spender，账单也只有它自己那台
    合约划得动。所以当前合约上的账单进 ``bills``，旧合约上的进 ``legacy`` ——
    它们仍在链上、仍在用户钱包里，但新订单划不动它们（旧合约连验证闸都没有），
    不能拿来当担保。
    """
    enforced = escrow_enabled()
    rows = await list_commits(db, identity_id)

    def _is_current(contract: str) -> bool:
        """没配托管合约时不存在「哪台合约」的问题（链上授权额本身就不存在），
        一律按当前口径记 —— 与契约缩窄之前的行为一致。"""
        return (not enforced) or is_current_contract(contract)

    groups: dict[tuple[str, str, str], list[AllowanceCommitModel]] = {}
    for row in rows:
        if row.state in _NON_LIVE_STATES:
            continue
        live = max(0.0, float(row.amount_usdc or 0.0) - float(row.spent_usdc or 0.0))
        if live <= 0:
            continue
        groups.setdefault(
            (row.wallet_address, row.token_address, bill_contract(row)), []
        ).append(row)

    report: dict[str, Any] = {
        "allowance_usdc": 0.0,
        "committed_usdc": 0.0,
        "secured_usdc": 0.0,
        "unsecured_usdc": 0.0,
        "enforced": enforced,
        "chain_checked": False,
        "bills": {},
        #: 落在**旧**托管合约上的锁仓：钱还在用户自己钱包里、还在旧合约上记着，
        #: 只是新合约划不动它。如实报出来，前台据此提示「请重新锁仓」。
        "legacy": {"contracts": [], "committed_usdc": 0.0, "secured_usdc": 0.0, "bills": {}},
    }
    live_pairs_by_group: dict[tuple[str, str, str], list[tuple[str, float]]] = {}
    for key, group in groups.items():
        live_pairs_by_group[key] = [
            (str(r.bill_id), max(0.0, float(r.amount_usdc or 0.0) - float(r.spent_usdc or 0.0)))
            for r in sorted(group, key=lambda r: _bill_sort_key(str(r.bill_id)))
        ]
        if _is_current(key[2]):
            report["committed_usdc"] += sum(live for _, live in live_pairs_by_group[key])
        else:
            report["legacy"]["committed_usdc"] += sum(
                live for _, live in live_pairs_by_group[key]
            )
            if key[2] not in report["legacy"]["contracts"]:
                report["legacy"]["contracts"].append(key[2])
    report["committed_usdc"] = round(report["committed_usdc"], 6)
    report["legacy"]["committed_usdc"] = round(report["legacy"]["committed_usdc"], 6)

    if not groups:
        return report

    def _bucket(contract: str) -> dict[str, dict[str, float]]:
        return report["bills"] if _is_current(contract) else report["legacy"]["bills"]

    if not enforced:
        # 这个部署里根本没有托管合约（v2 未启用 / RPC 未配置）：链上不存在
        # 授权额这回事，也就没有「多张账单抢同一条授权」的问题，回落到台账口径
        # amount - spent，并用 chain_checked=False 告诉调用方「这个数不是从链上读来的」。
        for (wallet, token, contract), live_pairs in live_pairs_by_group.items():
            for bill_id, live in live_pairs:
                _bucket(contract)[bill_id] = {
                    "live_usdc": round(live, 6),
                    "secured_usdc": round(live, 6),
                }
        report["secured_usdc"] = report["committed_usdc"]
        report["legacy"]["secured_usdc"] = report["legacy"]["committed_usdc"]
        return report

    w3 = _web3()
    checked = True
    for (wallet, token, contract), live_pairs in live_pairs_by_group.items():
        current = _is_current(contract)
        try:
            allowance = wei_to_usdc(_erc20_allowance_wei(w3, token, wallet, contract))
        except Exception as exc:  # RPC 抖动：这一次不声称担保，绝不放行
            logger.warning(
                "allowance_backing_read_failed",
                wallet=wallet,
                contract=contract,
                current=current,
                error=str(exc),
            )
            if current:
                checked = False
            allowance = 0.0
        secured = allocate_allowance(live_pairs, allowance)
        committed = round(sum(live for _, live in live_pairs), 6)
        secured_total = round(sum(secured.values()), 6)
        for bill_id, live in live_pairs:
            _bucket(contract)[bill_id] = {
                "live_usdc": round(live, 6),
                "secured_usdc": secured[bill_id],
            }
        if current:
            report["allowance_usdc"] += allowance
            report["secured_usdc"] += secured_total
            report["unsecured_usdc"] += round(committed - secured_total, 6)
        else:
            report["legacy"]["secured_usdc"] += secured_total
    report["chain_checked"] = checked
    for key in ("allowance_usdc", "committed_usdc", "secured_usdc", "unsecured_usdc"):
        report[key] = round(report[key], 6)
    report["legacy"]["secured_usdc"] = round(report["legacy"]["secured_usdc"], 6)
    return report


async def secured_usdc_for_bill(db: AsyncSession, identity_id: str, bill_id: str) -> float:
    """单张账单真正划得动的金额（同钱包其他账单先占先得）。"""
    report = await backing_report(db, identity_id)
    entry = (report.get("bills") or {}).get(str(bill_id)) or {}
    return round(float(entry.get("secured_usdc") or 0.0), 6)


async def reconcile_capacity_mirror(db: AsyncSession, identity_id: str) -> dict[str, float]:
    """把 v2 非托管承诺镜像进主身份 ``capacity`` 台账。

    钱从没离开用户自己的钱包，链上只有一条 ERC-20 授权加一条 ``commit()`` 承诺。
    操作台、Runtime Gateway、子身份额度分配读的都是 ``capacity`` 台账，所以这条
    承诺必须被记账，否则用户「锁仓成功」之后，每一个花钱的入口（付款码 / 任务
    合同 / agent request-voucher / 子身份额度）都会看到 0 可用额度而拒绝。

    口径：一条有效承诺对台账的贡献 = **链上真划得动的部分**，即把该钱包对托管合约的
    ERC-20 授权额按最早优先分给各账单后的份额（见 ``backing_report``）。只按
    ``amount - spent`` 记账会虚增可花额度：账单共用一条授权，链上逐张都 backed，
    加起来却划不动。每行记住自己当前贡献了多少
    （``capacity_credited_usdc``），所以这个函数是幂等的 —— 只有差额会被记一次，
    撤销、划转之后重跑也只会把台账修回链上的真实状态。
    """
    rows = await list_commits(db, identity_id)
    if not rows:
        return {"credited_usdc": 0.0, "delta_usdc": 0.0, "unsecured_usdc": 0.0}

    # 只把链上真划得动的部分记进台账。链上已关闭 / 已划光的账单贡献 0（revoke() 关掉的
    # 是整笔未使用额度；spent == amount 本来就算 0）——这一点由 backing_report 负责。
    report = await backing_report(db, identity_id)
    secured_by_bill = {
        str(bill_id): round(float(entry.get("secured_usdc") or 0.0), 6)
        for bill_id, entry in (report.get("bills") or {}).items()
    }
    credited_total = 0.0
    for row in rows:
        credited_total += float(row.capacity_credited_usdc or 0.0)
    unsecured_total = round(float(report.get("unsecured_usdc") or 0.0), 6)

    # committed == 0 意味着根本没有活着的账单（都已撤销 / 已关闭）：那不是
    # 「读不到链」，而是「本来就没东西要担保」，照常把台账归零。
    chain_unreadable = (
        report.get("enforced")
        and not report.get("chain_checked")
        and float(report.get("committed_usdc") or 0.0) > 0.0
    )
    if chain_unreadable:
        # 配了托管合约却这一次读不到链（RPC 抖动）：台账保持原样。
        # 读不到链不能放行新额度，但更不能把用户已经锁进来的额度清成 0 ——
        # 链读回来之后下一次对账会自己纠偏。
        return {
            "credited_usdc": round(credited_total, 6),
            "delta_usdc": 0.0,
            "unsecured_usdc": unsecured_total,
        }

    live_total = 0.0
    for row in rows:
        live_total += secured_by_bill.get(str(row.bill_id), 0.0)
    live_total = round(live_total, 6)

    cap = await db.get(CapacityModel, identity_id)
    if cap is None:
        cap = CapacityModel(identity_id=identity_id, updated_at=datetime.utcnow())
        db.add(cap)
        await db.flush()

    # 台账要修的不只是「链上担保变了多少」，还有「池子和担保对不上」。
    #
    # 池子（可用 + 预留 + 在途 + …）里有一部分不是链上担保撑出来的 —— 运营方直接
    # 发放的内部额度（见 ``api/routes/capacity.py``）也在同一个池子里。修台账时要把
    # 链上担保补进去，但不能把内部额度一起抹掉，也不能把链上担保叠两次。
    #
    # 分界线取 ``max(上一轮记下的担保, 这一次读到的担保)``：池子绝不允许低于链上担保，
    # 所以**低于**它的那一段只能是错账（补回来），**高过**它又高过链上担保的那一段才是
    # 内部额度（留着）。只按「上一轮记下的担保」划线，会把「链上已经担保、台账还没记」
    # 的那一段当成内部额度，再把链上担保叠一次 —— 虚增出链上划不动的可用额度。
    #
    # 老实现更窄，只补 `live_total - 上一轮担保`：池子被别的东西改小过（历史 bug、人工
    # 修库）时，差额口径看不出这个缺口，用户的可用额度会永远少一截。
    pool = (
        float(cap.available_credits or 0.0)
        + float(cap.reserved_credits or 0.0)
        + float(cap.in_progress_credits or 0.0)
        + float(cap.confirmed_progress_credits or 0.0)
        + float(cap.disputed_credits or 0.0)
        + float(cap.pending_settlement_credits or 0.0)
    )
    backed = max(credited_total, live_total)
    internal = max(0.0, round(pool - backed, 6))
    delta = round(live_total + internal - pool, 6)

    for row in rows:
        row.capacity_credited_usdc = secured_by_bill.get(str(row.bill_id), 0.0)
        row.updated_at = datetime.utcnow()

    if abs(delta) < 1e-9:
        await db.flush()
        return {"credited_usdc": live_total, "delta_usdc": 0.0, "unsecured_usdc": unsecured_total}

    cap.available_credits = float(cap.available_credits or 0.0) + delta
    if cap.available_credits < 0.0:
        # 已经被订单占用的额度不能倒扣成负数：差额留在责任桶里。
        cap.available_credits = 0.0
    active = (
        cap.available_credits
        + float(cap.reserved_credits or 0.0)
        + float(cap.in_progress_credits or 0.0)
        + float(cap.confirmed_progress_credits or 0.0)
        + float(cap.disputed_credits or 0.0)
        + float(cap.pending_settlement_credits or 0.0)
    )
    cap.total_bill_credits = active
    cap.total_locked_usdc = max(float(cap.total_locked_usdc or 0.0) + delta, active)
    cap.updated_at = datetime.utcnow()

    await db.flush()
    logger.info(
        "escrow_capacity_mirror_reconciled",
        identity_id=identity_id,
        delta_usdc=delta,
        credited_usdc=live_total,
        unsecured_usdc=unsecured_total,
    )
    return {"credited_usdc": live_total, "delta_usdc": delta, "unsecured_usdc": unsecured_total}


async def reconcile_all_capacity_mirrors(
    db: AsyncSession, *, limit: int = 100
) -> list[dict[str, Any]]:
    """Periodic self-heal for every identity that holds a live commitment.

    Runs on the auto-settlement tick, so a commitment claimed before this code
    existed, a manual DB fix-up, or a pull that landed while the API was down all
    converge back to the chain's truth within one interval.
    """
    stmt = (
        select(
            AllowanceCommitModel.identity_id,
            func.max(AllowanceCommitModel.last_synced_at),
        )
        .where(AllowanceCommitModel.state != REVOKED)
        .group_by(AllowanceCommitModel.identity_id)
        .limit(limit)
    )
    holders = list((await db.execute(stmt)).all())
    resync_before = datetime.utcnow() - timedelta(seconds=_RESYNC_INTERVAL_SECONDS)
    changed: list[dict[str, Any]] = []
    for identity_id, last_synced in holders:
        try:
            if last_synced is None or last_synced < resync_before:
                await sync_commits(db, identity_id)
            result = await reconcile_capacity_mirror(db, identity_id)
        except Exception as exc:  # noqa: BLE001 - bookkeeping must never stop the loop
            logger.warning(
                "escrow_capacity_mirror_failed", identity_id=identity_id, error=str(exc)
            )
            continue
        if abs(float(result.get("delta_usdc") or 0.0)) > 1e-9:
            changed.append({"identity_id": identity_id, **result})
    return changed


# ----------------------------------------------------- server-side settlement


# ------------------------------------------------------- operator nonce safety
#
# The operator signs two transactions back to back (bind, then submitSettlement).
# A load-balanced public RPC can still report the pre-bind nonce a moment after
# the bind receipt has been accepted, and the second transaction then died with
# "nonce too low" — *after* the first one had already reserved the buyer's money
# on-chain. These helpers make that impossible: a process-wide lock serialises
# sends, and the nonce signed is max(chain, last-signed + 1), so a lagging RPC
# can never hand back a stale one.
_SEND_LOCK = threading.Lock()
_LAST_NONCE: dict[str, int] = {}


def _chain_nonce(w3: Any, address: str, tag: str) -> int:
    try:
        return int(w3.eth.get_transaction_count(address, tag))
    except Exception:  # a flaky RPC must not stop us signing
        return 0


def _reserve_nonce(w3: Any, address: str) -> int:
    """Next nonce this process may sign with, never going backwards."""
    key = str(address).lower()
    chain_nonce = max(_chain_nonce(w3, address, tag) for tag in ("latest", "pending"))
    nonce = max(chain_nonce, _LAST_NONCE.get(key, -1) + 1)
    _LAST_NONCE[key] = nonce
    return nonce


def _forget_nonce(address: str) -> None:
    """Drop the cached nonce so the next send re-reads the chain (retry path)."""
    _LAST_NONCE.pop(str(address).lower(), None)


def _is_stale_nonce(exc: Exception) -> bool:
    """True only when the node *rejected* the transaction outright.

    "already known" is deliberately excluded: that transaction is already in the
    mempool, so signing a second one with a higher nonce would pay twice.
    """
    text = str(exc).lower()
    return "nonce too low" in text or "nonce has already been used" in text


def _send_tx(fn, account=None):
    """Sign and send with Karma's own operational account, then wait for it."""
    w3 = _web3()
    account = account or _operator_account()
    chain_id = int(settings.testnet_chain_id or 0) or w3.eth.chain_id
    cap_wei = int(max(0.0, float(settings.settlement_max_gas_price_gwei or 0.0)) * 1e9)

    last_error: Exception | None = None
    with _SEND_LOCK:  # nonce read + broadcast is one critical section
        for attempt in (1, 2):
            overrides: dict[str, Any] = {
                "from": account.address,
                "nonce": _reserve_nonce(w3, account.address),
                "chainId": chain_id,
            }
            if cap_wei:
                try:
                    quoted = int(w3.eth.gas_price or 0)
                except Exception:  # a flaky RPC must never block a settlement
                    quoted = 0
                # Never bid above the ceiling: the operator account is small on purpose.
                if not quoted or quoted > cap_wei:
                    overrides["maxFeePerGas"] = cap_wei
                    overrides["maxPriorityFeePerGas"] = min(cap_wei, 300_000_000)
            try:
                tx = fn.build_transaction(overrides)
            except Exception as exc:  # revert 常在预估 gas 这一步就炸出来
                _forget_nonce(account.address)
                raise chain_error(exc) from exc
            signed = account.sign_transaction(tx)
            raw = getattr(signed, "raw_transaction", None) or signed.rawTransaction
            try:
                tx_hash = w3.eth.send_raw_transaction(raw)
            except Exception as exc:
                last_error = exc
                if attempt == 1 and _is_stale_nonce(exc):
                    # Do NOT drop the reservation here: _reserve_nonce then hands
                    # out last_signed + 1, so the retry cannot repeat the nonce the
                    # node just rejected. Forgetting it would read the same lagging
                    # chain nonce back and fail in exactly the same way.
                    time.sleep(0.5)
                    continue
                _forget_nonce(account.address)
                raise
            receipt = w3.eth.wait_for_transaction_receipt(tx_hash, timeout=120)
            if _field(receipt, "status") is not None and int(_field(receipt, "status")) != 1:
                raise chain_error(_replay_revert(w3, tx, receipt))
            hx = _hexstr(getattr(receipt, "transactionHash", tx_hash))
            if not hx.startswith("0x"):
                hx = "0x" + hx
            return receipt, hx
    raise WalletLockError(f"could not send the settlement transaction: {last_error}")


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
    contract_address: str | None = None,
) -> dict[str, Any]:
    """Bind a buyer commitment to a seller stake and submit the proof.

    Runs on Karma's operational account, which the buyer named as ``operator``
    when committing — that is what removes the per-order signature. It can only
    ever *record* an obligation: the money moves later, from the buyer's wallet,
    and only while the buyer's own allowance stands.

    ``contract_address`` 是这个订单落在哪台托管合约上：**新单只允许开在当前
    合约**（旧合约没有 resolver-only 的验证闸），所以调用方传的是账单自己的
    合约，必须与当前配置一致才会走到这里。
    """
    if not escrow_enabled():
        raise WalletLockError(disabled_detail())
    w3 = _web3()
    contract = _contract(w3, contract_address)
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


def submit_settlement(
    *, binding_id: int, proof: str, contract_address: str | None = None
) -> dict[str, Any]:
    """Open the dispute window for a bound order on Karma's operational account.

    ``contract_address`` 默认当前合约；绑定开在旧合约上时（合约升级过）必须传它
    自己那台，否则新合约不认识这个 binding id。
    """
    if not escrow_enabled():
        raise WalletLockError(disabled_detail())
    w3 = _web3()
    contract = _contract(w3, contract_address)
    digest = proof_hash(proof)
    receipt, tx = _send_tx(contract.functions.submitSettlement(int(binding_id), digest))
    pull_after = int(parse_settle_submitted(receipt)["pull_after"])
    return {"binding_id": int(binding_id), "submit_tx_hash": tx, "proof_hash": digest, "pull_after": pull_after}


def finalize_settlement(
    *, binding_id: int, contract_address: str | None = None
) -> dict[str, Any]:
    """Execute the pull payer -> payee. Permissionless once the window elapsed.

    ``contract_address`` 默认当前合约 —— 收尾旧合约上的绑定要显式传它自己那台，
    否则一次合约升级就能把这笔钱永久卡死（新合约 UnknownBinding revert）。
    """
    if not escrow_enabled():
        raise WalletLockError(disabled_detail())
    w3 = _web3()
    contract = _contract(w3, contract_address)
    receipt, tx = _send_tx(contract.functions.finalizeSettlement(int(binding_id)))
    paid_usdc = wei_to_usdc(int(parse_settled(receipt)["amount_wei"]))
    return {"binding_id": int(binding_id), "finalize_tx_hash": tx, "paid_usdc": paid_usdc}


_BINDING_FIELDS = [
    c["name"] for c in next(f for f in _ABI_FUNCTIONS if f.get("name") == "getBinding")["outputs"][0]["components"]
]


def binding_state(*, binding_id: int, contract_address: str | None = None) -> int | None:
    """读合约自己记的绑定状态 —— 唯一的事实来源。

    用来对账「我们没等到回执、但交易其实上链了」的那一单：receipt 等待超时
    只说明我们没看见，不代表链上没有发生。链说了算。

    ``contract_address`` 默认当前合约；旧绑定必须传它自己那台，否则新合约不认识
    这个 binding id（``UnknownBinding`` revert）。
    """
    if not escrow_enabled():
        return None
    w3 = _web3()
    contract = _contract(w3, contract_address)
    raw = contract.functions.getBinding(int(binding_id)).call()
    return int(dict(zip(_BINDING_FIELDS, raw, strict=False))["state"])


def bill_available(*, bill_id: int, contract_address: str | None = None) -> float | None:
    """链上这张账单还剩多少可用（合约的 ``amount - reserved - spent``）。

    台账（``allowance_commits``）是回执回写出来的，结算完要等一次 sync 才追上链；
    两个结算挨得近的时候，台账会**高估**可用额度。挑账单这种事必须以链为准 ——
    否则就会在 bind 那一步吃到 InsufficientCommitment，用户看到的是一串 hex。

    ``contract_address`` 默认是当前合约；账单不属于那台合约时合约会 revert
    （``UnknownBill``），这里按「查不到 = 没有额度」返回 ``None``，绝不把一次
    合约 revert 抛成 500 —— 旧合约的账单不该让新合约的接单流程炸掉。
    """
    if not escrow_enabled():
        return None
    w3 = _web3()
    contract = _contract(w3, contract_address)
    try:
        return wei_to_usdc(int(contract.functions.available(int(bill_id)).call()))
    except Exception as exc:  # 不属于这台合约 / RPC 抖动：都当「划不动」
        logger.warning(
            "allowance_bill_available_failed",
            bill_id=bill_id,
            contract=(contract_address or configured_address()),
            error=str(exc)[:200],
        )
        return None


def finalize_breach(
    *, binding_id: int, contract_address: str | None = None
) -> dict[str, Any]:
    """Slash the seller stake to the buyer (resolver-only on-chain)."""
    if not escrow_enabled():
        raise WalletLockError(disabled_detail())
    w3 = _web3()
    contract = _contract(w3, contract_address)
    receipt, tx = _send_tx(contract.functions.finalizeBreach(int(binding_id)))
    slashed_usdc = wei_to_usdc(int(parse_slashed(receipt)["amount_wei"]))
    return {"binding_id": int(binding_id), "breach_tx_hash": tx, "slashed_usdc": slashed_usdc}


def cancel_binding(
    *, binding_id: int, contract_address: str | None = None
) -> dict[str, Any]:
    """Release an orphaned reservation (e.g. a bind whose caller died).

    Any party — or their operator — may cancel while nothing has been submitted,
    so a reservation can never be stranded by a crashed process.
    """
    if not escrow_enabled():
        raise WalletLockError(disabled_detail())
    w3 = _web3()
    contract = _contract(w3, contract_address)
    receipt, tx = _send_tx(contract.functions.cancelBinding(int(binding_id)))
    return {"binding_id": int(binding_id), "cancel_tx_hash": tx, "status": int(_field(receipt, "status", 1) or 1)}


def open_and_submit_order(
    *,
    buyer_bill_id: str,
    seller_bill_id: str,
    amount_usdc: float,
    stake_usdc: float,
    scope: str,
    task_id: str,
    proof: str,
    contract_address: str | None = None,
) -> dict[str, Any]:
    """``bind`` then ``submitSettlement``, releasing the reservation if submit fails.

    A bind that lands followed by a submit that does not would leave the buyer's
    allowance reserved with nothing pointing at it — the orphan we previously had
    to release by hand. Cancelling on failure keeps chain and database in step.
    """
    bound = open_order(
        buyer_bill_id=buyer_bill_id,
        seller_bill_id=seller_bill_id,
        amount_usdc=amount_usdc,
        stake_usdc=stake_usdc,
        scope=scope,
        task_id=task_id,
        contract_address=contract_address,
    )
    binding_id = int(bound["binding_id"])
    try:
        submitted = submit_settlement(
            binding_id=binding_id, proof=proof, contract_address=contract_address
        )
    except Exception:
        try:
            cancel_binding(binding_id=binding_id, contract_address=contract_address)
            logger.warning("escrow_bind_rolled_back", binding_id=binding_id)
        except Exception as cancel_exc:  # nothing else we can do; make it loud
            logger.error(
                "escrow_bind_orphaned",
                binding_id=binding_id,
                cancel_error=str(cancel_exc),
            )
        raise
    return {**bound, **submitted, "binding_id": binding_id}
