from __future__ import annotations

from core.audit.trail import DecisionAuditEntry, DecisionAuditTrail


def test_audit_trail_append_and_query(tmp_path):
    log_path = tmp_path / "audit.log"
    trail = DecisionAuditTrail(str(log_path))

    trail.append(
        DecisionAuditEntry(
            event_type="verification",
            task_id="task-1",
            request_hash="abc",
            policy_version="policy-v1",
            decision="release",
            confidence=0.92,
            notes="[policy=policy-v1] ok",
        )
    )
    trail.append(
        DecisionAuditEntry(
            event_type="settlement_apply",
            task_id="task-2",
            request_hash="def",
            policy_version="policy-v1",
            decision="released",
            confidence=0.92,
        )
    )

    task_1_entries = trail.list_by_task("task-1")
    assert len(task_1_entries) == 1
    assert task_1_entries[0]["task_id"] == "task-1"
    assert task_1_entries[0]["policy_version"] == "policy-v1"
    assert task_1_entries[0]["decision"] == "release"

