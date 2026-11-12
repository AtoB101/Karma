#!/usr/bin/env python3
"""运维通道：给某个身份开「治理角色」档案（verifier / arbitrator）。

为什么要有这个脚本
------------------
``verifier`` 能复核别人的主体认证与开发者实名，``arbitrator`` 能裁争议 —— 这两个角色
是**治理权**，不能让任何人自助开通（API 侧默认拒绝，见 config/settings.py 的
``GOVERNANCE_VERIFIER_IDS``）。授权动作只允许在服务器上、由有服务器权限的人执行，
所以它是脚本而不是接口。

用法（在服务器 / 容器里）：

    python -m scripts.maintenance.grant_governance_role --list
    python -m scripts.maintenance.grant_governance_role --identity kid_xxx --class verifier \
        --display-name "运营复核岗"

注意：一个身份**永远不能复核自己提交的**主体认证 / 开发者实名（路由层硬拦），
所以平台自己那家主体，必须由另一个身份的 verifier 档案来复核。
"""
from __future__ import annotations

import argparse
import asyncio
import uuid
from datetime import datetime


async def _main() -> int:
    parser = argparse.ArgumentParser(description="grant a governance role profile (ops only)")
    parser.add_argument("--identity", help="owner_identity_id, e.g. kid_5f0aa8ccf7483983a8a2a5a9")
    parser.add_argument("--class", dest="klass", default="verifier", choices=("verifier", "arbitrator"))
    parser.add_argument("--display-name", default=None)
    parser.add_argument("--list", action="store_true", help="list existing governance profiles")
    parser.add_argument("--revoke", action="store_true", help="set status=disabled instead of create")
    args = parser.parse_args()

    from sqlalchemy import select

    from db.models.orm import IdentityRoleProfile
    from db.session import AsyncSessionLocal, init_db

    await init_db()
    async with AsyncSessionLocal() as db:
        if args.list or not args.identity:
            rows = (
                await db.execute(
                    select(IdentityRoleProfile).where(
                        IdentityRoleProfile.class_.in_(("verifier", "arbitrator"))
                    )
                )
            ).scalars().all()
            for row in rows:
                print(
                    "%-8s owner=%s status=%s profile_id=%s name=%s"
                    % (row.class_, row.owner_identity_id, row.status, row.profile_id, row.display_name or "-")
                )
            print("count=%d" % len(rows))
            return 0

        identity_id = args.identity.strip()
        existing = (
            await db.execute(
                select(IdentityRoleProfile).where(
                    IdentityRoleProfile.owner_identity_id == identity_id,
                    IdentityRoleProfile.class_ == args.klass,
                )
            )
        ).scalars().first()

        if args.revoke:
            if existing is None:
                print("SKIP no %s profile for %s" % (args.klass, identity_id))
                return 1
            existing.status = "disabled"
            existing.updated_at = datetime.utcnow()
            await db.commit()
            print("OK revoked profile_id=%s" % existing.profile_id)
            return 0

        if existing is not None:
            print("SKIP already exists profile_id=%s status=%s" % (existing.profile_id, existing.status))
            return 0

        row = IdentityRoleProfile(
            profile_id=str(uuid.uuid4()),
            owner_identity_id=identity_id,
            class_=args.klass,
            kyc_status="none",
            visibility="public",
            display_name=args.display_name or ("运营复核岗" if args.klass == "verifier" else "仲裁岗"),
            kyc_payload={},
            status="active",
        )
        db.add(row)
        await db.commit()
        print("OK created profile_id=%s owner=%s class=%s" % (row.profile_id, identity_id, args.klass))
        print(
            "REMINDER 这个身份现在可以复核**别人**的提交。若还要允许它自助新建治理角色，"
            "把 %s 加进 .env 的 GOVERNANCE_VERIFIER_IDS。" % identity_id
        )
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))