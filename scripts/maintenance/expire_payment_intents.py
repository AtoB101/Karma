#!/usr/bin/env python3
"""Expire stale payment intents (cron-friendly)."""
from __future__ import annotations

import asyncio
import sys


async def _main() -> int:
    from config.settings import settings
    from db.session import AsyncSessionLocal, init_db
    from services.payment_intent_service import expire_stale_intents

    if not settings.payment_intent_expire_enabled:
        print("SKIP payment_intent_expire_enabled=false")
        return 0
    await init_db()
    async with AsyncSessionLocal() as db:
        n = await expire_stale_intents(db)
        await db.commit()
    print(f"OK expired_count={n}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
