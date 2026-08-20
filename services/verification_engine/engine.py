"""VerificationEngine — core trust gate for MiniApp settlement.

Verification PASS is required before Bilateral settle / finalize.
Does NOT live in karma8 economy surface.
"""
from __future__ import annotations

import hashlib
import json
import secrets
import time
from dataclasses import dataclass, field
from enum import Enum
from threading import Lock
from typing import Any


class VerificationStatus(str, Enum):
    PENDING = "PENDING"
    PASS = "PASS"
    FAIL = "FAIL"
    RISK_HOLD = "RISK_HOLD"


@dataclass
class VerificationRun:
    run_id: str
    order_id: str
    status: VerificationStatus
    reasons: list[str] = field(default_factory=list)
    evidence_hash: str | None = None
    intent_hash: str | None = None
    created_at: int = 0
    decided_at: int | None = None
    details: dict[str, Any] = field(default_factory=dict)


_LOCK = Lock()
_RUNS: dict[str, VerificationRun] = {}
_BY_ORDER: dict[str, str] = {}


def _digest(obj: Any) -> str:
    raw = json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def run_verification(
    *,
    order_id: str,
    intent: dict[str, Any],
    evidence: dict[str, Any],
    risk_flags: list[str] | None = None,
) -> VerificationRun:
    """Evaluate whether evidence proves the agreed intent outcome."""
    reasons: list[str] = []
    status = VerificationStatus.PASS

    if not order_id:
        raise ValueError("order_id required")
    if not intent:
        reasons.append("intent_missing")
        status = VerificationStatus.FAIL
    if not evidence:
        reasons.append("evidence_missing")
        status = VerificationStatus.FAIL

    intent_hash = _digest(intent) if intent else None
    evidence_hash = _digest(evidence) if evidence else None

    # Agreement checks (public-safe, deterministic)
    expected_proof = (intent or {}).get("expected_proof_hash") or (intent or {}).get("proof_hash")
    got_proof = (evidence or {}).get("proof_hash") or (evidence or {}).get("expected_proof_hash")
    if expected_proof and got_proof and str(expected_proof) != str(got_proof):
        reasons.append("proof_hash_mismatch")
        status = VerificationStatus.FAIL

    expected_amount = (intent or {}).get("amount_usdc")
    got_amount = (evidence or {}).get("amount_usdc")
    if expected_amount is not None and got_amount is not None and str(expected_amount) != str(got_amount):
        reasons.append("amount_mismatch")
        status = VerificationStatus.FAIL

    # Never trust client-only telegram ids as proof of delivery
    if evidence and evidence.get("trust_frontend_tg_id") is True:
        reasons.append("frontend_tg_id_not_trusted")
        status = VerificationStatus.FAIL

    # Merchant self-attestation alone is insufficient when marked
    if evidence and evidence.get("merchant_self_only") is True and not evidence.get("independent_attestation"):
        reasons.append("merchant_self_attestation_insufficient")
        status = VerificationStatus.FAIL

    flags = list(risk_flags or []) + list((evidence or {}).get("risk_flags") or [])
    if status == VerificationStatus.PASS and flags:
        status = VerificationStatus.RISK_HOLD
        reasons.extend([f"risk:{f}" for f in flags])

    if status == VerificationStatus.PASS and not reasons:
        reasons.append("agreement_and_evidence_ok")

    run = VerificationRun(
        run_id="vr_" + secrets.token_hex(10),
        order_id=order_id,
        status=status,
        reasons=reasons,
        evidence_hash=evidence_hash,
        intent_hash=intent_hash,
        created_at=int(time.time()),
        decided_at=int(time.time()),
        details={"risk_flags": flags},
    )
    with _LOCK:
        _RUNS[run.run_id] = run
        _BY_ORDER[order_id] = run.run_id
    return run


def get_run(run_id: str) -> VerificationRun | None:
    with _LOCK:
        return _RUNS.get(run_id)


def latest_for_order(order_id: str) -> VerificationRun | None:
    with _LOCK:
        rid = _BY_ORDER.get(order_id)
        return _RUNS.get(rid) if rid else None


def assert_pass_for_settle(order_id: str) -> VerificationRun:
    """Hard gate: settle/finalize forbidden unless latest verification is PASS."""
    run = latest_for_order(order_id)
    if not run:
        raise PermissionError("verification required before settle")
    if run.status != VerificationStatus.PASS:
        raise PermissionError(f"verification not PASS (status={run.status.value})")
    return run


def reset_for_tests() -> None:
    with _LOCK:
        _RUNS.clear()
        _BY_ORDER.clear()
