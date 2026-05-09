"""Minimal JSON-RPC helpers for NonCustodialAgentPayment + ERC20 (Phase 3)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from eth_account import Account
from eth_account.signers.local import LocalAccount
from web3 import Web3
from web3.types import TxReceipt

_PKG = Path(__file__).resolve().parent


def _load_abi(name: str) -> list:
    with open(_PKG / "abis" / name, encoding="utf-8") as f:
        return json.load(f)


def connect_web3() -> Web3:
    url = os.environ.get("TESTNET_RPC_URL", "").strip()
    if not url:
        raise SystemExit("Missing TESTNET_RPC_URL")
    w3 = Web3(Web3.HTTPProvider(url))
    if not w3.is_connected():
        raise SystemExit("Could not connect to TESTNET_RPC_URL")
    return w3


def karma_payment(w3: Web3):
    raw = os.environ.get("NONCUSTODIAL_AGENT_PAYMENT_ADDRESS", "").strip()
    if not raw:
        raise SystemExit("Missing NONCUSTODIAL_AGENT_PAYMENT_ADDRESS")
    return w3.eth.contract(address=Web3.to_checksum_address(raw), abi=_load_abi("non_custodial_agent_payment_min.json"))


def erc20_token(w3: Web3, token: str | None = None):
    raw = (token or os.environ.get("ERC20_TOKEN_ADDRESS", "")).strip()
    if not raw:
        raise SystemExit("Missing ERC20_TOKEN_ADDRESS")
    return w3.eth.contract(address=Web3.to_checksum_address(raw), abi=_load_abi("erc20_min.json"))


def account_from_env(var: str) -> LocalAccount:
    key = os.environ.get(var, "").strip()
    if not key:
        raise SystemExit(f"Missing {var}")
    return Account.from_key(key)


def _fill_gas(w3: Web3, tx: dict[str, Any]) -> dict[str, Any]:
    est = w3.eth.estimate_gas(tx)
    tx["gas"] = int(est * 1.25)
    return tx


def sign_send_wait(w3: Web3, acct: LocalAccount, tx: dict[str, Any]) -> TxReceipt:
    tx.setdefault("chainId", w3.eth.chain_id)
    tx.setdefault("value", 0)
    tx.setdefault("nonce", w3.eth.get_transaction_count(acct.address))
    tx = _fill_gas(w3, tx)
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    return w3.eth.wait_for_transaction_receipt(h, 600)


def send_contract_tx(w3: Web3, acct: LocalAccount, tx: dict[str, Any]) -> TxReceipt:
    tx["from"] = acct.address
    return sign_send_wait(w3, acct, tx)


def approve_max(w3: Web3, token_c, owner: LocalAccount, spender: str) -> TxReceipt:
    max_u = 2**256 - 1
    tx = token_c.functions.approve(Web3.to_checksum_address(spender), max_u).build_transaction({"from": owner.address})
    return send_contract_tx(w3, owner, tx)


def lock_party(w3: Web3, karma_c, acct: LocalAccount, token: str, amount: int) -> TxReceipt:
    tx = karma_c.functions.lockFunds(Web3.to_checksum_address(token), amount).build_transaction({"from": acct.address})
    return send_contract_tx(w3, acct, tx)


def bill_id_from_create_receipt(karma_c, receipt: TxReceipt) -> int:
    entries = karma_c.events.BillCreated().process_receipt(receipt)
    if not entries:
        raise RuntimeError("BillCreated not found in receipt")
    return int(entries[0]["args"]["billId"])


def tx_writeback_record(
    w3: Web3,
    *,
    step: str,
    receipt: TxReceipt,
    contract_address: str,
    settlement_status: str,
    trace_id: str = "",
    extra: dict[str, Any] | None = None,
) -> dict[str, Any]:
    ok = receipt.status == 1
    row: dict[str, Any] = {
        "step": step,
        "tx_hash": Web3.to_hex(receipt.transactionHash),
        "chain_id": int(w3.eth.chain_id),
        "contract_address": Web3.to_checksum_address(contract_address),
        "block_number": int(receipt.blockNumber),
        "settlement_status": settlement_status,
        "onchain_status": "success" if ok else "failed",
    }
    if trace_id:
        row["trace_id"] = trace_id
    if extra:
        row.update({k: v for k, v in extra.items() if v is not None})
    return row


def append_tx_log(path: Path, row: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row, sort_keys=True) + "\n"
    with open(path, "a", encoding="utf-8") as f:
        f.write(line)
