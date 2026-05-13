"""Unit tests for evidence bundle / verify payload limits."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi import HTTPException

from config.settings import settings
from core.schemas import EvidenceBundle, TaskContract, TaskStatus
from services.evidence_bundle_limits import (
    enforce_limits_for_bundle_post,
    enforce_limits_for_verify_request,
)


def _minimal_bundle(**kwargs) -> EvidenceBundle:
    h = "a" * 64
    base = dict(
        task_id="task-limit-1",
        task_contract_hash=h,
        receipt_ids=["r1"],
        receipt_hashes=[h],
        final_result_hash=h,
        total_steps=1,
        successful_steps=1,
        failed_steps=0,
        total_duration_ms=1,
        settlement_status=TaskStatus.DELIVERED,
    )
    base.update(kwargs)
    return EvidenceBundle(**base)


def _minimal_contract(task_id: str = "task-limit-1") -> TaskContract:
    return TaskContract(
        task_id=task_id,
        client_agent_id="buyer-1",
        worker_agent_id="seller-1",
        title="t",
        description="d",
        expected_output_schema={"type": "object"},
        expected_step_count=1,
        escrow_amount=1.0,
        deadline_at=datetime.utcnow() + timedelta(hours=1),
    )


def test_bundle_post_rejects_receipt_id_hash_length_mismatch():
    b = _minimal_bundle(receipt_ids=["a", "b"], receipt_hashes=["a" * 64])
    with pytest.raises(HTTPException) as ei:
        enforce_limits_for_bundle_post(b)
    assert ei.value.status_code == 400


def test_bundle_post_rejects_too_many_receipts():
    orig = settings.evidence_bundle_max_receipt_entries
    try:
        settings.evidence_bundle_max_receipt_entries = 4
        h = "b" * 64
        b = _minimal_bundle(
            receipt_ids=["1", "2", "3", "4", "5"],
            receipt_hashes=[h, h, h, h, h],
        )
        with pytest.raises(HTTPException) as ei:
            enforce_limits_for_bundle_post(b)
        assert ei.value.status_code == 400
        assert "exceeds maximum" in ei.value.detail
    finally:
        settings.evidence_bundle_max_receipt_entries = orig


def test_bundle_post_rejects_oversized_json():
    orig = settings.evidence_bundle_max_json_bytes
    try:
        settings.evidence_bundle_max_json_bytes = 256
        b = _minimal_bundle(storage_path="x" * 500)
        with pytest.raises(HTTPException) as ei:
            enforce_limits_for_bundle_post(b)
        assert ei.value.status_code == 413
    finally:
        settings.evidence_bundle_max_json_bytes = orig


def test_verify_rejects_oversized_combined_json():
    orig = settings.verify_max_combined_json_bytes
    try:
        settings.verify_max_combined_json_bytes = 400
        b = _minimal_bundle(storage_path="p" * 300)
        c = _minimal_contract()
        with pytest.raises(HTTPException) as ei:
            enforce_limits_for_verify_request(b, c)
        assert ei.value.status_code == 413
    finally:
        settings.verify_max_combined_json_bytes = orig
