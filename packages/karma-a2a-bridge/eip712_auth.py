"""EIP-712 signing for A2A Bridge write operations.

Reuses the same EIP-712 domain/encoding style as on-chain Karma auth
(AuthTokenManager / KarmaAttestationGateway): name+version+chainId+verifyingContract,
``\\x19\\x01`` digest, ECDSA recover.

Privileged VerifierRegistry methods are intentionally NOT exposed as A2A skills;
agents discover attestation capability addresses only.
"""
from __future__ import annotations

import os
import re
import time
from typing import Any

from eth_account import Account
from eth_account.messages import encode_typed_data
from eth_utils import to_checksum_address

DOMAIN_NAME = "KarmaA2A"
DOMAIN_VERSION = "1"

_HEX_ADDR = re.compile(r"^0x[0-9a-fA-F]{40}$")

# opType values for write endpoints
OP_CREATE = "create"
OP_CONFIRM = "confirm"
OP_SUBMIT = "submit"
OP_CANCEL = "cancel"
OP_HANDOFF = "handoff"


def require_eip712() -> bool:
    """Default on; set A2A_REQUIRE_EIP712=0 for local demos only."""
    return os.getenv("A2A_REQUIRE_EIP712", "1").strip().lower() not in {"0", "false", "no", "off"}


def chain_id() -> int:
    return int(os.getenv("A2A_EIP712_CHAIN_ID", os.getenv("KARMA_CHAIN_ID", "11155111")))


def verifying_contract() -> str:
    """Prefer Bilateral settlement contract — aligns with on-chain verifyingContract usage."""
    return os.getenv(
        "A2A_EIP712_VERIFYING_CONTRACT",
        os.getenv("KARMA_CONTRACT_ADDRESS", "0x0000000000000000000000000000000000000000"),
    )


def _normalize_address(addr: str) -> str:
    a = (addr or "").strip()
    if not _HEX_ADDR.match(a):
        raise ValueError("agent/wallet must be a 0x-prefixed 20-byte address")
    return to_checksum_address(a)


def build_a2a_task_typed_data(
    *,
    task_id: str,
    op_type: str,
    agent: str,
    requester_id: str,
    amount_micro: int,
    nonce: int,
    deadline: int,
    chain_id_: int | None = None,
    verifying_contract_: str | None = None,
) -> dict[str, Any]:
    agent_cs = _normalize_address(agent)
    vc = verifying_contract_ or verifying_contract()
    if not _HEX_ADDR.match(vc):
        raise ValueError("verifying_contract must be a 0x-prefixed address")
    return {
        "types": {
            "EIP712Domain": [
                {"name": "name", "type": "string"},
                {"name": "version", "type": "string"},
                {"name": "chainId", "type": "uint256"},
                {"name": "verifyingContract", "type": "address"},
            ],
            "A2ATaskOp": [
                {"name": "taskId", "type": "string"},
                {"name": "opType", "type": "string"},
                {"name": "agent", "type": "address"},
                {"name": "requesterId", "type": "string"},
                {"name": "amountMicro", "type": "uint256"},
                {"name": "nonce", "type": "uint256"},
                {"name": "deadline", "type": "uint256"},
            ],
        },
        "primaryType": "A2ATaskOp",
        "domain": {
            "name": DOMAIN_NAME,
            "version": DOMAIN_VERSION,
            "chainId": int(chain_id_ if chain_id_ is not None else chain_id()),
            "verifyingContract": to_checksum_address(vc),
        },
        "message": {
            "taskId": task_id,
            "opType": op_type,
            "agent": agent_cs,
            "requesterId": requester_id or "",
            "amountMicro": int(amount_micro),
            "nonce": int(nonce),
            "deadline": int(deadline),
        },
    }


def sign_a2a_task_op(
    *,
    private_key: str | bytes,
    task_id: str,
    op_type: str,
    agent: str | None = None,
    requester_id: str = "",
    amount_micro: int = 0,
    nonce: int,
    deadline: int,
    chain_id_: int | None = None,
    verifying_contract_: str | None = None,
) -> str:
    acct = Account.from_key(private_key)
    agent_addr = agent or acct.address
    data = build_a2a_task_typed_data(
        task_id=task_id,
        op_type=op_type,
        agent=agent_addr,
        requester_id=requester_id,
        amount_micro=amount_micro,
        nonce=nonce,
        deadline=deadline,
        chain_id_=chain_id_,
        verifying_contract_=verifying_contract_,
    )
    signed = Account.sign_message(encode_typed_data(full_message=data), private_key)
    sig = signed.signature.hex()
    return sig if sig.startswith("0x") else "0x" + sig


def verify_a2a_task_op(
    *,
    signature: str,
    task_id: str,
    op_type: str,
    agent: str,
    requester_id: str = "",
    amount_micro: int = 0,
    nonce: int,
    deadline: int,
    chain_id_: int | None = None,
    verifying_contract_: str | None = None,
    now: int | None = None,
) -> str:
    """Verify signature; returns checksum recovered address. Raises ValueError on failure."""
    ts = int(now if now is not None else time.time())
    if int(deadline) < ts:
        raise ValueError("A2A EIP-712 signature expired")
    agent_cs = _normalize_address(agent)
    data = build_a2a_task_typed_data(
        task_id=task_id,
        op_type=op_type,
        agent=agent_cs,
        requester_id=requester_id,
        amount_micro=amount_micro,
        nonce=nonce,
        deadline=deadline,
        chain_id_=chain_id_,
        verifying_contract_=verifying_contract_,
    )
    recovered = Account.recover_message(encode_typed_data(full_message=data), signature=signature)
    if recovered.lower() != agent_cs.lower():
        raise ValueError(f"A2A EIP-712 signer mismatch: expected {agent_cs}, got {recovered}")
    return recovered
