"""Phase 3 — AP2 adapter round-trip and digest stability."""

from __future__ import annotations

from trusted_agent_runtime.ap2_adapter import (
    evidence_digest,
    from_ap2_mandate,
    to_ap2_mandate,
    verify_ap2_digest_consistency,
)
from trusted_agent_runtime.schemas import EvidenceBundle


def _sample_bundle() -> EvidenceBundle:
    return EvidenceBundle(
        bundle_id="bundle-test-001",
        task_id="task-test-001",
        task_contract_hash="a" * 64,
        receipt_hashes=["b" * 64, "c" * 64],
        final_result_hash="c" * 64,
        evidence_storage_refs=[],
        created_at="2026-05-16T12:00:00Z",
        signer="0xpayer",
        signature="0xsig",
    )


def test_evidence_digest_stable():
    bundle = _sample_bundle()
    d1 = evidence_digest(bundle)
    d2 = evidence_digest(bundle)
    assert d1 == d2
    assert len(d1) == 64


def test_ap2_round_trip_preserves_required_fields():
    bundle = _sample_bundle()
    mandate = to_ap2_mandate(
        bundle,
        payer="0xpayer",
        payee="0xpayee",
        token="USDC",
        amount="1000000",
        chain_id=11155111,
        policy_id="policy-1",
        merchant_ref="order-42",
        expires_at="2026-12-31T23:59:59Z",
    )
    parsed = from_ap2_mandate(mandate)
    assert parsed["karma_evidence_digest"] == mandate["karma_evidence_digest"]
    assert parsed["task_id"] == bundle.task_id
    assert parsed["receipt_hashes"] == bundle.receipt_hashes
    ok, _ = verify_ap2_digest_consistency(mandate, recomputed_bundle=bundle)
    assert ok


def test_from_ap2_mandate_rejects_missing_keys():
    try:
        from_ap2_mandate({"ap2_version": "x"})
        assert False, "expected ValueError"
    except ValueError as exc:
        assert "missing keys" in str(exc)
