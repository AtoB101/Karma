"""Canonical `proofHash` string format for `NonCustodialAgentPayment.createBill` (Trusted Agent hybrid).

On-chain type is ``string``; the public stack uses a deterministic UTF-8 pointer so operators
and scripts can validate env/config before burning gas.

Expected shape (case-sensitive prefix, **lowercase** 64-hex digest tail)::

    karma-ta:v1/sha256/<64 hex chars>

Common mistakes: ``0x`` prefix on the digest tail, wrong separator (``/`` vs ``_``),
uppercase hex in the tail, trailing whitespace/newlines, or passing a raw **bytes32**
hex string (``0x…``) instead of the karma-ta pointer.
"""

from __future__ import annotations

import re
from typing import Final

_PREFIX: Final = "karma-ta:v1/sha256/"
_PATTERN = re.compile(r"^karma-ta:v1/sha256/[0-9a-f]{64}$")


def normalize_karma_proof_hash(proof_hash: str) -> str:
    """Lowercase the digest tail when the string is already a karma-ta pointer."""
    s = proof_hash.strip()
    if not s.startswith(_PREFIX):
        return s
    head, tail = s[: len(_PREFIX)], s[len(_PREFIX) :]
    return head + tail.lower()


def is_canonical_karma_proof_hash(proof_hash: str) -> bool:
    s = normalize_karma_proof_hash(proof_hash)
    return bool(_PATTERN.fullmatch(s))


def validate_karma_proof_hash_for_create_bill(proof_hash: str) -> tuple[bool, str]:
    """
    Returns (ok, message). When ``ok`` is False, ``message`` is a short operator-facing hint.
    """
    raw = proof_hash
    s = raw.strip()
    if s != raw:
        return False, "proofHash has leading/trailing whitespace — strip before export (see .env quoting)."

    if s.startswith("0x") and len(s) == 66:
        return (
            False,
            "proofHash looks like a raw bytes32 hex string; createBill expects a UTF-8 **pointer** string, "
            f"typically `{_PREFIX}<64-hex>` from hybrid artifacts (not 0x…).",
        )

    if not s.startswith("karma-ta:"):
        return (
            False,
            f"proofHash must start with `{_PREFIX}` for Trusted-Agent bundle alignment "
            "(or use a deliberate non-karma pointer such as ipfs://… and skip hybrid checks).",
        )

    if not s.startswith(_PREFIX):
        return False, f"proofHash must use prefix `{_PREFIX}` (got prefix {s[:24]!r}…)."

    tail = s[len(_PREFIX) :]
    if tail.startswith("0x"):
        return False, "Remove `0x` from the digest tail; use 64 bare hex characters after the slash."

    if len(tail) != 64:
        return False, f"Digest tail must be exactly 64 hex chars (got length {len(tail)})."

    if not re.fullmatch(r"[0-9a-fA-F]{64}", tail):
        return False, "Digest tail must be hexadecimal [0-9a-f] (use lowercase for canonical tooling)."

    if not _PATTERN.fullmatch(normalize_karma_proof_hash(s)):
        return False, "proofHash failed canonical pattern after normalization."

    return True, "OK"


def assert_canonical_karma_proof_hash(proof_hash: str) -> str:
    """Return normalized proof hash or raise ValueError with a multi-line hint."""
    ok, msg = validate_karma_proof_hash_for_create_bill(proof_hash)
    if not ok:
        raise ValueError(
            msg
            + "\n\nExpected: karma-ta:v1/sha256/<64 lowercase hex>\n"
            + "Generate: run `python3 scripts/testnet_full_flow.py --output-dir <dir>` and copy "
            + "`hybrid_settlement_result.json` → `karma_proof_hash` into `KARMA_PROOF_HASH`."
        )
    return normalize_karma_proof_hash(proof_hash)
