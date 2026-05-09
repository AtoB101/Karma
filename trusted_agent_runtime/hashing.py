from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(obj: dict[str, Any]) -> bytes:
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_bytes32_hex(data: bytes) -> str:
    """Lowercase 64-char hex (32-byte digest), suitable as a bytes32-style commitment off-chain."""
    return hashlib.sha256(data).hexdigest()


def karma_proof_hash_pointer(bundle_digest_hex: str) -> str:
    """Maps bundle digest into a compact `proofHash` string for `NonCustodialAgentPayment.createBill`."""
    return f"karma-ta:v1/sha256/{bundle_digest_hex.lower()}"
