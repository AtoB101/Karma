#!/usr/bin/env python3
"""运维通道：平台自举审批一份主身份认证（证件 + 刷脸）。

为什么要有这个脚本
------------------
路由层写死「一个身份不能复核自己」（services/identity_verification.py 的状态机红线），
这对多主体平台是对的：复核岗和被复核人是两个人。

但平台起步阶段只有一个身份，它同时也是自己唯一的复核岗 —— 于是它永远停在 pending，
永远拿不到身份卡，操作台的所有业务闸门都打不开。这个脚本就是那个「平台自己签字」的
出口，它**只在服务器上**存在，不走任何 HTTP 接口。

它不是橡皮图章，三条硬性前置：
1. 本人必须先在操作台真实提交过证件 + 刷脸（identity_verifications 有 pending 行）；
2. 提交里必须有 doc_digest 与 face_digest（少一个都不行）；
3. 必须写明审批理由，理由会落进 review_note，审批人固定记作 platform:bootstrap。

正式上线后应换成第三方实名 / 活体服务回调（阿里云、腾讯云这类），由服务商判定后自动置位，
这个脚本只作为「服务商还没接进来」这段时间的过渡通道。

用法（在服务器 / 容器里）：

    python -m scripts.maintenance.approve_identity_verification --list
    python -m scripts.maintenance.approve_identity_verification \
        --identity kid_xxx --reason "平台自举：本人提交的证件与刷脸已人工核对"

    # 只想看会发生什么，不落库：
    python -m scripts.maintenance.approve_identity_verification \
        --identity kid_xxx --reason "..." --dry-run
"""
from __future__ import annotations

import argparse
import asyncio
from datetime import datetime


async def _main() -> int:
    parser = argparse.ArgumentParser(description="bootstrap-approve a master identity verification (ops only)")
    parser.add_argument("--identity", help="identity_id, e.g. kid_5f0aa8ccf7483983a8a2a5a9")
    parser.add_argument("--reason", default=None, help="为什么批准这一份（必填，会落进 review_note）")
    parser.add_argument("--list", action="store_true", help="列出已有的认证记录")
    parser.add_argument("--dry-run", action="store_true", help="只校验，不写库")
    args = parser.parse_args()

    from sqlalchemy import select

    from db.models.orm import IdentityVerificationModel
    from db.session import AsyncSessionLocal, init_db
    from services.identity_activation import activation_of
    from services.identity_verification import (
        BOOTSTRAP_REVIEWER_ID,
        IdentityVerificationError,
        assert_can_bootstrap_approve,
        mark_verified,
    )

    await init_db()
    async with AsyncSessionLocal() as db:
        if args.list or not args.identity:
            rows = (
                await db.execute(select(IdentityVerificationModel))
            ).scalars().all()
            for row in rows:
                print(
                    "identity=%s status=%s level=%s doc=%s face=%s reviewer=%s"
                    % (
                        row.identity_id,
                        row.status,
                        row.level,
                        "yes" if (row.doc_digest or "").strip() else "no",
                        "yes" if (row.face_digest or "").strip() else "no",
                        row.reviewer_identity_id or "-",
                    )
                )
            print("count=%d" % len(rows))
            return 0

        identity_id = args.identity.strip()
        row = await db.get(IdentityVerificationModel, identity_id)

        try:
            assert_can_bootstrap_approve(row, reason=args.reason or "")
        except IdentityVerificationError as exc:
            print("REFUSED %s: %s" % (exc.status, exc.message))
            return 1

        if args.dry_run:
            print("DRY-RUN would approve identity=%s (status=%s)" % (identity_id, row.status))
            return 0

        mark_verified(row, reviewer_identity_id=BOOTSTRAP_REVIEWER_ID, note=args.reason)
        row.updated_at = datetime.utcnow()
        await db.commit()

        print("OK approved identity=%s reviewer=%s" % (identity_id, BOOTSTRAP_REVIEWER_ID))
        print("audit reviewer=%s identity=%s reason=%s" % (BOOTSTRAP_REVIEWER_ID, identity_id, args.reason))
        print("activation=%s" % (await activation_of(db, identity_id)))
        return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))