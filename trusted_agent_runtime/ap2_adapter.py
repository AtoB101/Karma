"""AP2 Mandate ↔ Karma Evidence Bundle mapping (Phase 3).

Maps Google AP2-style Intent / Cart / Payment mandates to Karma evidence digests.
Public schema excludes private risk scores (see docs/AP2_EVIDENCE_PROFILE-zh.md).
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, is_dataclass
from datetime import datetime
from typing import Any, Mapping

from trusted_agent_runtime.hashing import canonical_json_bytes, sha256_hex
from trusted_agent_runtime.schemas import EvidenceBundle as TaEvidenceBundle

AP2_SCHEMA_VERSION = "agents-to-payments/ap2-mandate/v1"
KARMA_EVIDENCE_SCHEMA = "karma.ta.evidence_bundle.v1"
REQUIRED_AP2_TOP_KEYS = frozenset(
    {"ap2_version", "intent_mandate", "cart_mandate", "payment_mandate", "karma_evidence_digest"}
)
REQUIRED_INTENT_KEYS = frozenset({"intent_id", "user_goal_hash", "created_at"})
REQUIRED_CART_KEYS = frozenset({"cart_id", "merchant_ref", "line_item_hashes"})
REQUIRED_PAYMENT_KEYS = frozenset(
    {"payment_mandate_id", "payer", "payee", "token", "amount", "chain_id", "policy_id", "expires_at"}
)


def _utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _bundle_canonical_dict(bundle: Any) -> dict[str, Any]:
    if hasattr(bundle, "to_canonical_dict"):
        return bundle.to_canonical_dict()
    if is_dataclass(bundle):
        return TaEvidenceBundle(**asdict(bundle)).to_canonical_dict()  # type: ignore[arg-type]
    if isinstance(bundle, Mapping):
        return dict(bundle)
    if hasattr(bundle, "model_dump"):
        return _core_bundle_to_ta_dict(bundle)
    raise TypeError(f"unsupported bundle type: {type(bundle)!r}")


def _core_bundle_to_ta_dict(bundle: Any) -> dict[str, Any]:
    """Map core.schemas.EvidenceBundle into trusted-agent canonical layout."""
    data = bundle.model_dump(mode="json")
    return {
        "bundle_id": data["bundle_id"],
        "created_at": (
            data["created_at"]
            if isinstance(data["created_at"], str)
            else data["created_at"].isoformat().replace("+00:00", "Z")
        ),
        "evidence_storage_refs": list(data.get("storage_path") and [data["storage_path"]] or []),
        "final_result_hash": data["final_result_hash"],
        "receipt_hashes": list(data["receipt_hashes"]),
        "schema_version": KARMA_EVIDENCE_SCHEMA,
        "signature": data.get("agent_signature") or "",
        "signer": "",
        "task_contract_hash": data["task_contract_hash"],
        "task_id": data["task_id"],
    }


def evidence_digest(bundle: Any) -> str:
    """Stable SHA-256 hex over canonical bundle bytes (evidence_hash / digestSha256)."""
    return sha256_hex(canonical_json_bytes(_bundle_canonical_dict(bundle)))


def ap2_mandate_digest(mandate: Mapping[str, Any]) -> str:
    """Digest over AP2 mandate excluding detached signatures and self-referential digest."""
    skip = frozenset({"mandate_signature", "mandate_digest"})
    payload = {k: mandate[k] for k in sorted(mandate.keys()) if k not in skip}
    return sha256_hex(canonical_json_bytes(payload))


def to_ap2_mandate(
    bundle: Any,
    *,
    payer: str,
    payee: str,
    token: str,
    amount: str,
    chain_id: int,
    policy_id: str,
    merchant_ref: str,
    expires_at: str,
    intent_id: str | None = None,
    cart_id: str | None = None,
    payment_mandate_id: str | None = None,
    user_goal_hash: str | None = None,
) -> dict[str, Any]:
    """Export Karma evidence bundle as AP2 three-layer mandate JSON."""
    canonical = _bundle_canonical_dict(bundle)
    digest = evidence_digest(bundle)
    task_id = str(canonical.get("task_id") or "")
    bundle_id = str(canonical.get("bundle_id") or task_id)
    goal_hash = user_goal_hash or sha256_hex(task_id.encode("utf-8"))
    line_hashes = list(canonical.get("receipt_hashes") or [])

    mandate: dict[str, Any] = {
        "ap2_version": AP2_SCHEMA_VERSION,
        "intent_mandate": {
            "intent_id": intent_id or f"intent-{bundle_id[:16]}",
            "user_goal_hash": goal_hash,
            "created_at": canonical.get("created_at") or _utc_now_iso(),
            "human_present": False,
        },
        "cart_mandate": {
            "cart_id": cart_id or f"cart-{bundle_id[:16]}",
            "merchant_ref": merchant_ref,
            "line_item_hashes": line_hashes,
            "task_contract_hash": canonical.get("task_contract_hash"),
        },
        "payment_mandate": {
            "payment_mandate_id": payment_mandate_id or f"pay-{bundle_id[:16]}",
            "payer": payer,
            "payee": payee,
            "token": token,
            "amount": str(amount),
            "chain_id": int(chain_id),
            "policy_id": policy_id,
            "expires_at": expires_at,
        },
        "karma_evidence_digest": digest,
        "karma_bundle_id": bundle_id,
        "karma_task_id": task_id,
        "karma_schema_version": canonical.get("schema_version", KARMA_EVIDENCE_SCHEMA),
    }
    mandate["mandate_digest"] = ap2_mandate_digest(mandate)
    return mandate


def from_ap2_mandate(mandate: Mapping[str, Any]) -> dict[str, Any]:
    """
    Parse AP2 mandate into Karma-side fields for bundle reconstruction / verification.

    Returns a dict with keys suitable for EvidenceBundle construction (trusted-agent shape).
    """
    missing = REQUIRED_AP2_TOP_KEYS - set(mandate.keys())
    if missing:
        raise ValueError(f"AP2 mandate missing keys: {sorted(missing)}")

    intent = mandate["intent_mandate"]
    cart = mandate["cart_mandate"]
    payment = mandate["payment_mandate"]
    for label, req, obj in (
        ("intent_mandate", REQUIRED_INTENT_KEYS, intent),
        ("cart_mandate", REQUIRED_CART_KEYS, cart),
        ("payment_mandate", REQUIRED_PAYMENT_KEYS, payment),
    ):
        sub_missing = req - set(obj.keys())
        if sub_missing:
            raise ValueError(f"{label} missing keys: {sorted(sub_missing)}")

    digest = str(mandate["karma_evidence_digest"])
    if not _is_hex64(digest):
        raise ValueError("karma_evidence_digest must be 64-char lowercase hex")

    bundle_id = str(mandate.get("karma_bundle_id") or cart.get("cart_id", ""))
    task_id = str(mandate.get("karma_task_id") or intent.get("intent_id", ""))

    return {
        "bundle_id": bundle_id,
        "task_id": task_id,
        "task_contract_hash": str(cart.get("task_contract_hash") or hashlib.sha256(task_id.encode()).hexdigest()),
        "receipt_hashes": list(cart.get("line_item_hashes") or []),
        "final_result_hash": (
            list(cart.get("line_item_hashes") or [""])[-1]
            if cart.get("line_item_hashes")
            else digest
        ),
        "evidence_storage_refs": [],
        "created_at": str(intent.get("created_at") or _utc_now_iso()),
        "signer": str(payment.get("payer", "")),
        "signature": str(mandate.get("mandate_signature") or ""),
        "schema_version": str(mandate.get("karma_schema_version") or KARMA_EVIDENCE_SCHEMA),
        "trace_id": "",
        "karma_evidence_digest": digest,
        "payment_mandate": dict(payment),
        "merchant_ref": str(cart.get("merchant_ref", "")),
    }


def verify_ap2_digest_consistency(mandate: Mapping[str, Any], *, recomputed_bundle: Any | None = None) -> tuple[bool, str]:
    """
    Return (ok, detail). When recomputed_bundle is provided, re-hash and compare to mandate digest.
    """
    expected = str(mandate.get("karma_evidence_digest", ""))
    if recomputed_bundle is not None:
        actual = evidence_digest(recomputed_bundle)
        if actual != expected.lower():
            return False, f"bundle digest mismatch: expected={expected} actual={actual}"
    declared = str(mandate.get("mandate_digest", ""))
    if declared:
        recomputed = ap2_mandate_digest(mandate)
        if recomputed != declared.lower():
            return False, f"mandate_digest mismatch: expected={declared} actual={recomputed}"
    return True, "ok"


def _is_hex64(value: str) -> bool:
    if len(value) != 64:
        return False
    try:
        int(value, 16)
    except ValueError:
        return False
    return value == value.lower()
