"""G12：验证者质押金库（入场闸门 / 在任现算 / 退出冷却 / 挑战判负罚没 80-20）。

这些用例考的是**后果**，不是字段：押金不足登记不进去、锁仓被划走出不了证、
冷却期内抢不出钱、挑战判负当场停用且台账按 80/20 分账、重复裁决不重复扣款。
"""
from __future__ import annotations

from datetime import datetime

import pytest
from sqlalchemy import select

from db.models.orm import CapacityModel, IdentityProfileModel
from decentralized_verifier.models import (
    Attestation,
    BondSlash,
    Challenge,
    VerifierNode,
)

OWNER = "id-owner-g12"
OWNER_WALLET = "0x00000000000000000000000000000000000000A1"
NODE_WALLET = "0x00000000000000000000000000000000000000B1"


async def _make_owner(db, *, identity_id: str = OWNER, wallet: str = OWNER_WALLET, locked: float = 500.0):
    db.add(
        IdentityProfileModel(
            identity_id=identity_id,
            display_id="Karma-ID-G12",
            legal_identity_status="verified",
            status="active",
            bound_wallet_address=wallet,
            created_at=datetime.utcnow(),
            updated_at=datetime.utcnow(),
        )
    )
    db.add(CapacityModel(identity_id=identity_id, total_locked_usdc=locked))
    await db.commit()


async def _set_locked(db, locked: float, *, identity_id: str = OWNER):
    row = await db.get(CapacityModel, identity_id)
    row.total_locked_usdc = locked
    await db.commit()


# ─────────────────────────────────────────────── 入场闸门（P1）

@pytest.mark.anyio
async def test_register_owner_node_requires_backed_bond(client, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "verifier_min_bond_usdc", 100.0)
    monkeypatch.setattr(settings, "verifier_require_backed_bond", True)
    await _make_owner(db_session, locked=500.0)

    resp = await client.post(
        "/v1/verifiers/register",
        json={
            "wallet_address": OWNER_WALLET,
            "stake_amount": 100.0,
            "owner_identity_id": OWNER,
            "endpoint_url": "https://n1.karma.test",
        },
    )
    assert resp.status_code == 201, resp.text
    data = resp.json()
    assert data["owner_identity_id"] == OWNER
    assert data["bond_state"] == "active"


@pytest.mark.anyio
async def test_register_owner_node_rejected_without_locked_backing(client, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "verifier_min_bond_usdc", 100.0)
    monkeypatch.setattr(settings, "verifier_require_backed_bond", True)
    await _make_owner(db_session, locked=0.0)

    resp = await client.post(
        "/v1/verifiers/register",
        json={
            "wallet_address": OWNER_WALLET,
            "stake_amount": 100.0,
            "owner_identity_id": OWNER,
        },
    )
    assert resp.status_code == 409, resp.text
    assert "not backed" in resp.text


@pytest.mark.anyio
async def test_register_owner_node_rejects_foreign_wallet(client, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "verifier_min_bond_usdc", 100.0)
    await _make_owner(db_session, locked=500.0)

    resp = await client.post(
        "/v1/verifiers/register",
        json={
            "wallet_address": NODE_WALLET,
            "stake_amount": 100.0,
            "owner_identity_id": OWNER,
        },
    )
    assert resp.status_code == 403, resp.text
    assert "does not match" in resp.text


@pytest.mark.anyio
async def test_register_requires_owner_when_owner_mode_on(client, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "verifier_require_owner_identity", True)

    resp = await client.post(
        "/v1/verifiers/register",
        json={"wallet_address": NODE_WALLET, "stake_amount": 100.0},
    )
    assert resp.status_code == 422, resp.text


# ─────────────────────────────────────────────── 在任现算（P2）

@pytest.mark.anyio
async def test_attestation_blocked_when_locked_backing_pulled(client, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "verifier_min_bond_usdc", 100.0)
    monkeypatch.setattr(settings, "verifier_require_backed_bond", True)
    await _make_owner(db_session, locked=500.0)

    node = VerifierNode(
        wallet_address=OWNER_WALLET,
        stake_amount=100.0,
        owner_identity_id=OWNER,
        is_active=True,
    )
    db_session.add(node)
    await db_session.commit()

    ok = await client.post(
        "/v1/verifiers/attestations",
        json={
            "task_id": "task-g12-ok",
            "verifier_id": node.id,
            "decision": "ATTESTED_OK",
            "checks_passed": 1,
            "checks_total": 1,
        },
    )
    assert ok.status_code == 201, ok.text

    # 锁仓被划走（含罚没）→ 下一次出证当场 403，不看缓存快照。
    await _set_locked(db_session, 0.0)
    blocked = await client.post(
        "/v1/verifiers/attestations",
        json={
            "task_id": "task-g12-blocked",
            "verifier_id": node.id,
            "decision": "ATTESTED_OK",
            "checks_passed": 1,
            "checks_total": 1,
        },
    )
    assert blocked.status_code == 403, blocked.text
    # 报错文本按产品口径说人话（中文），所以只断言「确实点到了这个身份」。
    assert OWNER in blocked.text


# ─────────────────────────────────────────────── 退出冷却（P3）

@pytest.mark.anyio
async def test_unstake_cooldown_blocks_and_then_releases(client, db_session, monkeypatch):
    from config.settings import settings

    monkeypatch.setattr(settings, "verifier_unbond_cooldown_hours", 72)

    reg = await client.post(
        "/v1/verifiers/register",
        json={"wallet_address": NODE_WALLET, "stake_amount": 120.0},
    )
    assert reg.status_code == 201, reg.text
    node_id = reg.json()["id"]

    req = await client.post(f"/v1/verifiers/{node_id}/unstake", json={})
    assert req.status_code == 200, req.text
    assert req.json()["unbond_requested_at"] is not None
    assert req.json()["unbond_amount"] == 120.0

    early = await client.post(f"/v1/verifiers/{node_id}/unstake/finalize", json={})
    assert early.status_code == 409, early.text
    assert "cooldown" in early.text

    monkeypatch.setattr(settings, "verifier_unbond_cooldown_hours", 0)
    done = await client.post(f"/v1/verifiers/{node_id}/unstake/finalize", json={})
    assert done.status_code == 200, done.text
    assert done.json()["stake_amount"] == 0.0
    assert done.json()["is_active"] is False


@pytest.mark.anyio
async def test_unstake_rejects_more_than_bond(client, db_session):
    reg = await client.post(
        "/v1/verifiers/register",
        json={"wallet_address": NODE_WALLET, "stake_amount": 50.0},
    )
    node_id = reg.json()["id"]
    resp = await client.post(f"/v1/verifiers/{node_id}/unstake", json={"amount": 999.0})
    assert resp.status_code == 422, resp.text


# ─────────────────────────────────────────────── 判负罚没 80/20（P4）

async def _seed_challenge(db, *, task_id: str, node: VerifierNode) -> Challenge:
    db.add(
        Attestation(
            task_id=task_id,
            verifier_id=node.id,
            decision="ATTESTED_OK",
            checks_passed=1,
            checks_total=1,
        )
    )
    challenge = Challenge(task_id=task_id, status="OPEN", quorum_size=3)
    db.add(challenge)
    await db.commit()
    return challenge


@pytest.mark.anyio
async def test_upheld_challenge_slashes_verifier_and_splits_80_20(client_sec, db_session):
    node = VerifierNode(
        wallet_address=NODE_WALLET, stake_amount=200.0, is_active=True, reputation_score=80.0
    )
    db_session.add(node)
    await db_session.commit()

    challenge = await _seed_challenge(db_session, task_id="task-g12-upheld", node=node)

    victim = "0x00000000000000000000000000000000000000C1"
    resp = await client_sec.post(
        f"/v1/verifiers/challenges/{challenge.id}/resolve",
        json={
            "resolution": "attestation proven false",
            "status": "UPHELD",
            "victim_wallet_address": victim,
        },
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["status"] == "UPHELD"

    await db_session.refresh(node)
    assert node.is_active is False, "a slashed node below the floor must be deactivated"
    assert node.stake_amount == 0.0
    assert node.slash_unsettled == 200.0

    rows = (await db_session.execute(
        select(BondSlash)
    )).scalars().all()
    assert len(rows) == 1
    row = rows[0]
    assert row.subject_kind == "verifier_node"
    assert row.subject_id == node.id
    assert row.amount == 200.0
    assert row.victim_amount == 160.0, "80% to the victim"
    assert row.pool_amount == 40.0, "20% to the slash pool"
    assert row.victim_wallet_address == victim
    assert row.status == "pending", "no tx hash → must NOT pretend to be settled"

    listed = await client_sec.get("/v1/verifiers/slashes")
    assert listed.status_code == 200, listed.text
    body = listed.json()
    assert body["total"] == 1
    assert body["pool_total"] == 40.0
    assert body["vault_configured"] is False


@pytest.mark.anyio
async def test_upheld_challenge_is_idempotent(client_sec, db_session):
    node = VerifierNode(wallet_address=NODE_WALLET, stake_amount=200.0, is_active=True)
    db_session.add(node)
    await db_session.commit()
    challenge = await _seed_challenge(db_session, task_id="task-g12-idem", node=node)

    first = await client_sec.post(
        f"/v1/verifiers/challenges/{challenge.id}/resolve",
        json={"resolution": "partial penalty", "status": "UPHELD", "slash_amount": 50.0},
    )
    assert first.status_code == 200, first.text
    await db_session.refresh(node)
    assert node.stake_amount == 150.0

    # 把挑战退回 OPEN 再裁一次 —— 台账按来源唯一，第二次是幂等 no-op。
    challenge.status = "OPEN"
    await db_session.commit()
    second = await client_sec.post(
        f"/v1/verifiers/challenges/{challenge.id}/resolve",
        json={"resolution": "partial penalty again", "status": "UPHELD", "slash_amount": 50.0},
    )
    assert second.status_code == 200, second.text

    await db_session.refresh(node)
    assert node.stake_amount == 150.0, "repeat verdict must not double-charge"
    rows = (await db_session.execute(select(BondSlash))).scalars().all()
    assert len(rows) == 1


@pytest.mark.anyio
async def test_upheld_without_victim_routes_everything_to_pool(client_sec, db_session):
    node = VerifierNode(wallet_address=NODE_WALLET, stake_amount=100.0, is_active=True)
    db_session.add(node)
    await db_session.commit()
    challenge = await _seed_challenge(db_session, task_id="task-g12-novictim", node=node)

    resp = await client_sec.post(
        f"/v1/verifiers/challenges/{challenge.id}/resolve",
        json={"resolution": "no identifiable victim", "status": "UPHELD"},
    )
    assert resp.status_code == 200, resp.text

    rows = (await db_session.execute(select(BondSlash))).scalars().all()
    assert len(rows) == 1
    assert rows[0].victim_amount == 0.0
    assert rows[0].pool_amount == 100.0, "no victim → the whole slash stays in the pool"


@pytest.mark.anyio
async def test_overturned_challenge_has_no_penalty(client_sec, db_session):
    node = VerifierNode(wallet_address=NODE_WALLET, stake_amount=100.0, is_active=True)
    db_session.add(node)
    await db_session.commit()
    challenge = await _seed_challenge(db_session, task_id="task-g12-overturned", node=node)

    resp = await client_sec.post(
        f"/v1/verifiers/challenges/{challenge.id}/resolve",
        json={"resolution": "original attestation stands", "status": "OVERTURNED"},
    )
    assert resp.status_code == 200, resp.text

    await db_session.refresh(node)
    assert node.is_active is True
    assert node.stake_amount == 100.0
    rows = (await db_session.execute(select(BondSlash))).scalars().all()
    assert rows == []
