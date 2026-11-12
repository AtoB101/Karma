"""证据包签名绑定（P0-5）回归。

2026-09-17 复核实测：任何身份都能给别人的任务建证据包（201），
``agent_signature`` 可以是 NULL，而且全项目**没有任何证据包验签函数**。
这里锁住三件事：

1. 规范载荷唯一、稳定（构建方与服务端逐字节一致）；
2. 用规范载荷签出来的包，服务端验得过；改一个字段就验不过；
3. 占位签名只在非生产放行，生产永不接受。
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta

import pytest

from config.settings import settings
from core.evidence.bundle_builder import (
    EvidenceBundleBuilder,
    evidence_bundle_signing_bytes,
    evidence_bundle_signing_dict,
)
from core.hooks.hook_layer import InMemoryReceiptStore
from core.schemas import EvidenceBundle, ExecutionReceipt, TaskContract, ToolStatus
from services.receipt_guard import (
    evidence_bundle_signature_acceptable,
    evidence_bundle_signature_required,
    verify_evidence_bundle_signature,
)
from services.signing import signing_service


def _bundle(**over) -> EvidenceBundle:
    fields = dict(
        task_id="task-bundle-sig-001",
        task_contract_hash="a" * 64,
        receipt_ids=["r1", "r2"],
        receipt_hashes=["b" * 64, "c" * 64],
        final_result_hash="d" * 64,
        total_steps=2,
        successful_steps=2,
        failed_steps=0,
        total_duration_ms=120,
        created_at=datetime(2026, 9, 17, 7, 0, 0),
    )
    fields.update(over)
    return EvidenceBundle(**fields)


def _signed(**over) -> EvidenceBundle:
    bundle = _bundle(**over)
    bundle.agent_signature = signing_service.sign_bytes(evidence_bundle_signing_bytes(bundle))
    return bundle


# --- 1. 规范载荷 -------------------------------------------------------------

def test_canonical_payload_is_stable_and_sorted():
    bundle = _bundle()
    first = evidence_bundle_signing_bytes(bundle)
    second = evidence_bundle_signing_bytes(_bundle())
    assert first == second
    assert first == json.dumps(
        evidence_bundle_signing_dict(bundle),
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode()
    assert set(evidence_bundle_signing_dict(bundle)) == {
        "task_id",
        "contract_hash",
        "receipt_hashes",
        "final_result_hash",
        "total_steps",
        "successful_steps",
        "created_at",
    }


@pytest.mark.asyncio
async def test_builder_signature_verifies_on_the_server():
    """构建方签出来的包，服务端必须验得过 —— 这是"证据链可信"的地基。"""
    store = InMemoryReceiptStore()
    now = datetime.utcnow()
    for step in (1, 2):
        await store.save(
            ExecutionReceipt(
                task_id="task-bundle-sig-builder",
                agent_id="worker-001",
                step_index=step,
                tool_name=f"tool.{step}",
                input_hash="a" * 64,
                output_hash="b" * 64,
                started_at=now,
                ended_at=now + timedelta(milliseconds=50),
                duration_ms=50,
                status=ToolStatus.SUCCESS,
            )
        )
    contract = TaskContract(
        task_id="task-bundle-sig-builder",
        client_agent_id="client-001",
        title="sig",
        description="sig",
        expected_output_schema={},
        expected_step_count=2,
        escrow_amount=10.0,
        deadline_at=now + timedelta(hours=1),
    )
    bundle = await EvidenceBundleBuilder(
        receipt_store=store, signer=signing_service
    ).build(contract, {"output": "final"})

    assert bundle.agent_signature
    assert verify_evidence_bundle_signature(bundle) is True
    assert evidence_bundle_signature_acceptable(bundle) is True


# --- 2. 篡改与占位 -----------------------------------------------------------

def test_signature_detects_any_field_change():
    signed = _signed()
    assert verify_evidence_bundle_signature(signed) is True
    for field, value in (
        ("total_steps", 3),
        ("successful_steps", 1),
        ("final_result_hash", "e" * 64),
        ("task_contract_hash", "f" * 64),
        ("receipt_hashes", ["b" * 64]),
        ("task_id", "task-bundle-sig-002"),
    ):
        tampered = signed.model_copy(deep=True)
        setattr(tampered, field, value)
        assert verify_evidence_bundle_signature(tampered) is False, field
        assert evidence_bundle_signature_acceptable(tampered) is False, field


def test_unsigned_bundle_is_never_acceptable():
    assert verify_evidence_bundle_signature(_bundle()) is False


def test_placeholder_signatures_are_dev_only(monkeypatch):
    bundle = _bundle()
    bundle.agent_signature = "sig-fake"
    assert evidence_bundle_signature_acceptable(bundle) is True
    assert verify_evidence_bundle_signature(bundle) is False

    monkeypatch.setattr(settings, "app_env", "production")
    assert evidence_bundle_signature_acceptable(bundle) is False


def test_random_string_is_rejected_even_in_development():
    """非生产也不能"随便编一个字符串"就过关（这正是 P0-5 的原缺陷）。"""
    bundle = _bundle()
    bundle.agent_signature = "runtime-sdk"
    assert evidence_bundle_signature_acceptable(bundle) is False


def test_signature_requirement_follows_settings(monkeypatch):
    monkeypatch.setattr(settings, "receipt_require_signature", True)
    monkeypatch.setattr(settings, "openclaw_relax_delivery_signatures", False)
    monkeypatch.setattr(settings, "app_env", "production")
    assert evidence_bundle_signature_required() is True

    monkeypatch.setattr(settings, "receipt_require_signature", False)
    assert evidence_bundle_signature_required() is False
