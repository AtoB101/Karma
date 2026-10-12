"""``scripts/maintenance/register_service_actor.py`` 的纯逻辑回归。

不是应用代码，但它的判断决定了「白名单里的服务账号挂在谁名下」——
判错了 A4e 会红/绿颠倒，改坏了要等到线上那一刻才知道（CI 的 ops-scripts 作业跑它）。
"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from scripts.maintenance.register_service_actor import (  # noqa: E402
    SERVICE_ACTOR_META_SOURCE,
    SERVICE_ACTOR_PUBLIC_KEY,
    plan_service_actor,
    service_actor_fields,
)

OWNER = "kid_5f0aa8ccf7483983a8a2a5a9"


def test_plan_creates_when_nothing_exists():
    action, why = plan_service_actor(
        actor="ops-arbitrator", owner_identity_id=OWNER, identity_exists=False, agent_owner=None
    )
    assert action == "create"
    assert OWNER in why


def test_plan_skips_when_actor_is_itself_an_identity():
    action, _ = plan_service_actor(
        actor="ops-admin", owner_identity_id=OWNER, identity_exists=True, agent_owner=None
    )
    assert action == "skip"


def test_plan_adopts_an_agent_that_has_no_owner():
    action, _ = plan_service_actor(
        actor="ops-arbitrator", owner_identity_id=OWNER, identity_exists=False, agent_owner=""
    )
    assert action == "adopt"


def test_plan_adopts_an_agent_owned_by_someone_else():
    action, why = plan_service_actor(
        actor="ops-arbitrator",
        owner_identity_id=OWNER,
        identity_exists=False,
        agent_owner="kid_somebody_else",
    )
    assert action == "adopt"
    assert "kid_somebody_else" in why


def test_plan_is_idempotent_for_the_right_owner():
    action, _ = plan_service_actor(
        actor="ops-arbitrator", owner_identity_id=OWNER, identity_exists=False, agent_owner=OWNER
    )
    assert action == "skip"


def test_service_actor_fields_are_accountable_and_carry_no_secrets():
    fields = service_actor_fields("ops-arbitrator", OWNER)
    assert fields["agent_id"] == "ops-arbitrator"
    assert fields["owner_identity_id"] == OWNER
    assert fields["onboarding_meta"]["source"] == SERVICE_ACTOR_META_SOURCE
    assert fields["public_key"] == SERVICE_ACTOR_PUBLIC_KEY
    # 这条记录里不许出现任何像密钥的东西：密钥只活在发布机的 .env。
    blob = repr(fields)
    for needle in ("secret", "private_key", "mnemonic", "karma_ops-"):
        assert needle not in blob
