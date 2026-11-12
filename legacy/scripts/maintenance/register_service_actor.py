#!/usr/bin/env python3
"""运维通道：给白名单里的「服务账号 actor」补一条可归属的 agents 记录。

为什么要有这个脚本
------------------
闸门 ``A4e``（``scripts/public-beta-security-gate.sh``）判的是「白名单里点名的每个 actor
都能归属到一条真实身份记录」。``A4c`` 只保证它有自己的一把钥匙 —— 可钥匙背后如果查无
此人，用这把钥匙做的事在审计里落到一串没人认领的字符串：
``services/identity_actor.resolve_actor_identity_id`` 找不到 agent 记录时，会把 actor
原样当成身份号返回，并写进 ``owner_identity_id`` / ``created_by`` 这类归属字段。

服务账号（``ops-admin`` / ``ops-arbitrator`` / ``ops-governance`` 这种）不是真人身份，
但它们必须挂在**责任人名下**：给 actor 建一条 agents 记录，``owner_identity_id`` 指向
持有并对这把钥匙负责的那个真实身份。这样 ``actor → 责任人`` 是一条能查的链，
而不是一个空挂的名字。

用法（在服务器 / 容器里）：

    python -m scripts.maintenance.register_service_actor --list
    python -m scripts.maintenance.register_service_actor --actor ops-arbitrator \
        --owner kid_5f0aa8ccf7483983a8a2a5a9 --dry-run
    python -m scripts.maintenance.register_service_actor --actor ops-arbitrator \
        --owner kid_5f0aa8ccf7483983a8a2a5a9 --apply

幂等：actor 自己已经是 ``identity_profiles`` 里的一条身份时直接 SKIP（它本来就归属得到
自己）；已有 agents 记录时只补 ``owner_identity_id``，不重建、不动别的字段。
``--apply`` 才落库，默认 ``--dry-run``。
"""
from __future__ import annotations

import argparse
import asyncio
import re
from datetime import datetime

#: 这条 agents 记录是怎么来的（onboarding_meta.source），便于事后分辨。
SERVICE_ACTOR_META_SOURCE = "service_actor_ledger"
#: 服务账号不是钱包主人，public_key 只作占位 —— 与 ``identity_reputation`` 的桩口径一致。
SERVICE_ACTOR_PUBLIC_KEY = "service-actor-ledger"

_ACTOR_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,63}$")


def plan_service_actor(*, actor: str, owner_identity_id: str,
                       identity_exists: bool, agent_owner):
    """决定对某个 actor 做什么。纯函数，便于单测（不碰库）。

    ``identity_exists`` —— actor 自己已经是 ``identity_profiles`` 的一条身份；
    ``agent_owner``    —— ``None`` 表示没有 agents 记录，``""`` 表示有记录但没挂 owner，
                          否则是当前的 ``owner_identity_id``。
    返回 ``(action, why)``，action ∈ {create, adopt, skip}。
    """
    if identity_exists:
        return ("skip", "%s is already an identity_profiles record" % actor)
    if agent_owner is None:
        return ("create", "create an agents row for %s owned by %s" % (actor, owner_identity_id))
    if (agent_owner or "").strip() == owner_identity_id:
        return ("skip", "agents row for %s is already owned by %s" % (actor, owner_identity_id))
    return (
        "adopt",
        "set agents.owner_identity_id for %s: %r -> %s" % (actor, agent_owner, owner_identity_id),
    )


def service_actor_fields(actor: str, owner_identity_id: str) -> dict:
    """服务账号那条 agents 记录的字段。**不含任何密钥材料。**

    密钥（``AUTH_API_KEYS`` 里的 secret）只活在发布机的 ``.env`` 里，不落库、不进仓库；
    这里建的是一条归属记录，不是一把钥匙。
    """
    tail = actor[-8:] if len(actor) > 8 else actor
    return {
        "agent_id": actor,
        "name": "karma-service-%s" % tail,
        "role": "client",
        "public_key": SERVICE_ACTOR_PUBLIC_KEY,
        "endpoint_url": None,
        "capabilities": [],
        "is_active": True,
        "identity_class": None,
        "owner_identity_id": owner_identity_id,
        "boundary_hash": None,
        "p1_ready": False,
        "onboarding_meta": {"source": SERVICE_ACTOR_META_SOURCE},
    }


async def _main() -> int:
    parser = argparse.ArgumentParser(description="register a service-account actor under a real owner identity")
    parser.add_argument("--actor", help="the privileged actor id, e.g. ops-arbitrator")
    parser.add_argument("--owner", help="the responsible identity_id, e.g. kid_5f0aa8ccf7483983a8a2a5a9")
    parser.add_argument("--list", action="store_true", help="list agents rows that look like service accounts")
    parser.add_argument("--dry-run", action="store_true", help="only print what would happen (default)")
    parser.add_argument("--apply", action="store_true", help="actually write to the database")
    args = parser.parse_args()

    from sqlalchemy import select

    from db.models.orm import AgentModel, IdentityProfileModel
    from db.session import AsyncSessionLocal, init_db

    await init_db()
    async with AsyncSessionLocal() as db:
        if args.list or not args.actor:
            rows = (
                await db.execute(select(AgentModel).where(AgentModel.agent_id.like("ops-%")))
            ).scalars().all()
            for row in rows:
                print(
                    "%-18s owner=%s role=%s active=%s source=%s"
                    % (
                        row.agent_id,
                        row.owner_identity_id or "-",
                        row.role,
                        row.is_active,
                        (row.onboarding_meta or {}).get("source", "-"),
                    )
                )
            print("count=%d" % len(rows))
            return 0

        actor = args.actor.strip()
        owner = (args.owner or "").strip()
        if not _ACTOR_RE.match(actor):
            print("ERR  --actor %r is not a valid actor id" % actor)
            return 2
        if not owner:
            print("ERR  --owner is required (the responsible identity_id)")
            return 2
        if not args.apply and not args.dry_run:
            print("REFUSE  neither --dry-run nor --apply given; pass --apply to write")
            return 2

        owner_row = await db.get(IdentityProfileModel, owner)
        if owner_row is None:
            print("ERR  owner identity %r does not exist in identity_profiles" % owner)
            print("     pick a real identity_id - the actor must be accountable to it")
            return 2

        identity_row = await db.get(IdentityProfileModel, actor)
        agent_row = await db.get(AgentModel, actor)
        action, why = plan_service_actor(
            actor=actor,
            owner_identity_id=owner,
            identity_exists=identity_row is not None,
            agent_owner=None if agent_row is None else agent_row.owner_identity_id,
        )
        print("%-6s %s" % (action.upper(), why))
        if action == "skip":
            return 0
        if not args.apply:
            print("DRY-RUN  nothing written (pass --apply to write)")
            return 0

        if action == "create":
            db.add(AgentModel(registered_at=datetime.utcnow(), **service_actor_fields(actor, owner)))
        else:
            agent_row.owner_identity_id = owner
        await db.commit()
        print("OK  %s now resolves to identity %s via the agents table" % (actor, owner))
        print("REMINDER  下次跑 scripts/public-beta-security-gate.sh，A4e 应不再点这个 actor 的名")
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
