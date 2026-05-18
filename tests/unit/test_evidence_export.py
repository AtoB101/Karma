"""Phase 3 — SD-JWT export verification."""

from __future__ import annotations

from services.evidence_export import export_sd_jwt_disclosure, verify_sd_jwt_export
from trusted_agent_runtime.schemas import EvidenceBundle


def test_sd_jwt_export_roundtrip():
    bundle = EvidenceBundle(
        bundle_id="b1",
        task_id="t1",
        task_contract_hash="d" * 64,
        receipt_hashes=["e" * 64],
        final_result_hash="e" * 64,
        evidence_storage_refs=[],
        created_at="2026-05-16T00:00:00Z",
        signer="0x1",
        signature="",
    )
    token = export_sd_jwt_disclosure(
        bundle,
        payer="0xa",
        payee="0xb",
        token="USDC",
        amount="1",
        chain_id=1,
        policy_id="p",
        merchant_ref="m",
        expires_at="2027-01-01T00:00:00Z",
    )
    ok, payload, detail = verify_sd_jwt_export(token)
    assert ok, detail
    assert payload["merchant_ref"] == "m"
