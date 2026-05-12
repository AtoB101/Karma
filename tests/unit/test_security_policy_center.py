from __future__ import annotations

import hashlib

import pytest

from services.security_policy_center import (
    activate_security_threshold_policy,
    apply_security_policy_change_request,
    create_security_threshold_policy,
    create_security_policy_change_request,
    get_security_policy_change_request,
    review_security_policy_change_request,
    resolve_security_threshold_policy,
    rollback_security_threshold_policy,
    set_candidate_security_threshold_policy,
)
from core.schemas import (
    SecurityPolicyApprovalDecision,
    SecurityPolicyChangeAction,
)


def _bucket(actor_id: str) -> int:
    digest = hashlib.sha256(actor_id.encode("utf-8")).hexdigest()
    return int(digest[:8], 16) % 100


@pytest.mark.asyncio
async def test_security_policy_center_versioning_and_canary_resolution(db_session):
    policy_v1 = await create_security_threshold_policy(
        db_session,
        config={"failed_auth_threshold": 7},
        note="v1",
        created_by="sec-admin",
    )
    assert policy_v1.version == 1
    active_v1 = await activate_security_threshold_policy(db_session, policy_id=policy_v1.policy_id)
    assert active_v1.status.value == "active"

    policy_v2 = await create_security_threshold_policy(
        db_session,
        config={"failed_auth_threshold": 3},
        note="v2 canary",
        created_by="sec-admin",
        parent_policy_id=policy_v1.policy_id,
    )
    candidate_v2 = await set_candidate_security_threshold_policy(
        db_session,
        policy_id=policy_v2.policy_id,
        rollout_percent=1,
    )
    assert candidate_v2.status.value == "candidate"

    hit_actor = None
    miss_actor = None
    for idx in range(5000):
        actor = f"actor-{idx}"
        if _bucket(actor) == 0 and hit_actor is None:
            hit_actor = actor
        if _bucket(actor) != 0 and miss_actor is None:
            miss_actor = actor
        if hit_actor and miss_actor:
            break
    assert hit_actor is not None and miss_actor is not None

    hit_resolved = await resolve_security_threshold_policy(db_session, actor_id=hit_actor)
    miss_resolved = await resolve_security_threshold_policy(db_session, actor_id=miss_actor)
    assert hit_resolved.policy is not None
    assert miss_resolved.policy is not None
    assert hit_resolved.policy.policy_id == policy_v2.policy_id
    assert hit_resolved.matched_candidate is True
    assert miss_resolved.policy.policy_id == policy_v1.policy_id
    assert miss_resolved.matched_candidate is False

    rolled_back = await rollback_security_threshold_policy(db_session, target_policy_id=policy_v1.policy_id)
    assert rolled_back.policy_id == policy_v1.policy_id
    assert rolled_back.status.value == "active"


@pytest.mark.asyncio
async def test_security_policy_center_api_endpoints(client):
    created = await client.post(
        "/v1/security/policies",
        json={
            "config": {"failed_auth_threshold": 8, "window_minutes": 20},
            "note": "initial policy",
            "created_by": "sec-admin",
            "rollout_percent": 100,
        },
    )
    assert created.status_code == 201
    policy_id = created.json()["policy_id"]

    blocked_activate = await client.post(f"/v1/security/policies/{policy_id}/activate", json={})
    assert blocked_activate.status_code == 409

    draft_two = await client.post(
        "/v1/security/policies",
        json={
            "config": {"failed_auth_threshold": 2, "window_minutes": 15},
            "note": "canary policy",
            "created_by": "sec-admin",
            "parent_policy_id": policy_id,
            "rollout_percent": 100,
        },
    )
    assert draft_two.status_code == 201
    policy_two_id = draft_two.json()["policy_id"]

    dry_run = await client.post(
        "/v1/security/policies/changes/dry-run",
        json={
            "action": "set_candidate",
            "target_policy_id": policy_two_id,
            "rollout_percent": 25,
            "requested_by": "sec-admin",
        },
    )
    assert dry_run.status_code == 200
    assert "summary" in dry_run.json()

    activate_req = await client.post(
        "/v1/security/policies/changes",
        json={
            "action": "activate",
            "target_policy_id": policy_id,
            "requested_by": "sec-admin",
        },
    )
    assert activate_req.status_code == 201
    activate_req_id = activate_req.json()["request_id"]
    first_review = await client.post(
        f"/v1/security/policies/changes/{activate_req_id}/review",
        json={"approver_id": "sec-reviewer-1", "decision": "approve"},
    )
    assert first_review.status_code == 200
    assert first_review.json()["status"] == "pending"
    second_review = await client.post(
        f"/v1/security/policies/changes/{activate_req_id}/review",
        json={"approver_id": "sec-reviewer-2", "decision": "approve"},
    )
    assert second_review.status_code == 200
    assert second_review.json()["status"] == "approved"
    applied_activate = await client.post(f"/v1/security/policies/changes/{activate_req_id}/apply", json={})
    assert applied_activate.status_code == 200
    assert applied_activate.json()["status"] == "applied"

    candidate_req = await client.post(
        "/v1/security/policies/changes",
        json={
            "action": "set_candidate",
            "target_policy_id": policy_two_id,
            "rollout_percent": 25,
            "requested_by": "sec-admin",
        },
    )
    assert candidate_req.status_code == 201
    candidate_req_id = candidate_req.json()["request_id"]
    await client.post(
        f"/v1/security/policies/changes/{candidate_req_id}/review",
        json={"approver_id": "sec-reviewer-1", "decision": "approve"},
    )
    await client.post(
        f"/v1/security/policies/changes/{candidate_req_id}/review",
        json={"approver_id": "sec-reviewer-2", "decision": "approve"},
    )
    applied_candidate = await client.post(f"/v1/security/policies/changes/{candidate_req_id}/apply", json={})
    assert applied_candidate.status_code == 200
    assert applied_candidate.json()["status"] == "applied"

    candidate_list = await client.get("/v1/security/policies?status=candidate&limit=10")
    assert candidate_list.status_code == 200
    assert any(item["policy_id"] == policy_two_id for item in candidate_list.json())

    report = await client.get(
        f"/v1/security/ops/alerts?apply_policy_center=true&policy_id={policy_two_id}&policy_actor_id=actor-1"
    )
    assert report.status_code == 200
    body = report.json()
    assert body["policy_id"] == policy_two_id
    assert body["policy_status"] == "candidate"

    rollback_req = await client.post(
        "/v1/security/policies/changes",
        json={"action": "rollback", "target_rollback_policy_id": policy_id, "requested_by": "sec-admin"},
    )
    assert rollback_req.status_code == 201
    rollback_req_id = rollback_req.json()["request_id"]
    await client.post(
        f"/v1/security/policies/changes/{rollback_req_id}/review",
        json={"approver_id": "sec-reviewer-1", "decision": "approve"},
    )
    await client.post(
        f"/v1/security/policies/changes/{rollback_req_id}/review",
        json={"approver_id": "sec-reviewer-2", "decision": "approve"},
    )
    rollback_applied = await client.post(f"/v1/security/policies/changes/{rollback_req_id}/apply", json={})
    assert rollback_applied.status_code == 200
    assert rollback_applied.json()["status"] == "applied"


@pytest.mark.asyncio
async def test_security_policy_change_request_requires_two_approvals(db_session):
    policy = await create_security_threshold_policy(
        db_session,
        config={"failed_auth_threshold": 5},
        created_by="sec-admin",
    )
    request = await create_security_policy_change_request(
        db_session,
        action=SecurityPolicyChangeAction.ACTIVATE,
        target_policy_id=policy.policy_id,
        requested_by="sec-admin",
    )
    pending = await review_security_policy_change_request(
        db_session,
        request_id=request.request_id,
        approver_id="approver-1",
        decision=SecurityPolicyApprovalDecision.APPROVE,
    )
    assert pending.status.value == "pending"
    with pytest.raises(ValueError, match="must be approved"):
        await apply_security_policy_change_request(db_session, request_id=request.request_id)
    approved = await review_security_policy_change_request(
        db_session,
        request_id=request.request_id,
        approver_id="approver-2",
        decision=SecurityPolicyApprovalDecision.APPROVE,
    )
    assert approved.status.value == "approved"
    applied_request, applied_policy = await apply_security_policy_change_request(
        db_session,
        request_id=request.request_id,
    )
    assert applied_request.status.value == "applied"
    assert applied_policy.status.value == "active"
    loaded = await get_security_policy_change_request(db_session, request_id=request.request_id, include_approvals=True)
    assert len(loaded.approvals) == 2
