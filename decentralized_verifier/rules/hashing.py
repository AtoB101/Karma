"""
Karma Decentralized Verification — Canonical Hashing
=====================================================
Pure functions for SHA-256 hashing of JSON-serializable objects.
Used by all verifier nodes for deterministic evidence verification.

No private dependencies. No DB access. No network calls.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any


def canonical_json_bytes(obj: dict[str, Any]) -> bytes:
    """Serialize a dict to canonical JSON bytes (sorted keys, no whitespace)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":")).encode("utf-8")


def sha256_hex(data: bytes) -> str:
    """SHA-256 digest as 64-char lowercase hex."""
    return hashlib.sha256(data).hexdigest()


def evidence_hash(bundle_dict: dict[str, Any]) -> str:
    """Compute the canonical evidence hash for a bundle dict."""
    return sha256_hex(canonical_json_bytes(bundle_dict))


def receipt_hash(receipt_dict: dict[str, Any]) -> str:
    """Compute the canonical receipt hash for a receipt dict."""
    return sha256_hex(canonical_json_bytes(receipt_dict))


def task_contract_hash(task_dict: dict[str, Any]) -> str:
    """Compute the canonical task contract hash."""
    return sha256_hex(canonical_json_bytes(task_dict))


def proof_hash_bytes32(bundle_dict: dict[str, Any]) -> bytes:
    """Canonical bytes32 `proofHash` committed by `KarmaBilateral.settle` / `settleWithTEE`.

    The on-chain `proofHash` is a bytes32. This function defines its canonical
    value as the raw 32-byte SHA-256 of the canonical evidence bundle, so the
    off-chain evidence package and the on-chain commitment are one object:

        proofHash (bytes32) = SHA256(canonical_json_bytes(bundle_dict))

    Note: SHA-256 is used (not keccak256) because it is the evidence layer's
    zero-dependency digest, and its 32-byte output is exactly a bytes32.
    """
    return hashlib.sha256(canonical_json_bytes(bundle_dict)).digest()


def proof_hash_hex(bundle_dict: dict[str, Any]) -> str:
    """`0x`-prefixed hex form of :func:`proof_hash_bytes32` for JSON/log output."""
    return "0x" + proof_hash_bytes32(bundle_dict).hex()


def karma_proof_hash_pointer(bundle_digest_hex: str) -> str:
    """Map bundle digest into a compact proofHash string for on-chain reference."""
    return f"karma-ta:v1/sha256/{bundle_digest_hex.lower()}"
