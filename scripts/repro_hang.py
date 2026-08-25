"""Repro with lifespan enabled, dump task stacks on hang."""
import asyncio
import os
import sys

sys.path.insert(0, ".")
os.environ.setdefault("KARMA_ENV", "dev")
os.environ.setdefault("TELEGRAM_BOT_TOKEN", "x:y")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///./karma_local.db")

from httpx import ASGITransport, AsyncClient

import api.app as appmod


async def dump_tasks():
    for task in asyncio.all_tasks():
        st = task.get_stack(limit=10)
        frames = " <- ".join(
            f"{f.f_code.co_filename.split('/')[-1]}:{f.f_lineno}:{f.f_code.co_name}" for f in st
        )
        print(f"TASK {task.get_name()}: {frames or '<no frames>'}")


async def main():
    async with appmod.app.router.lifespan_context(appmod.app):
        transport = ASGITransport(app=appmod.app)
        async with AsyncClient(transport=transport, base_url="http://t", timeout=20) as c:
            task = asyncio.ensure_future(c.post("/v1/telegram/session", json={}))
            try:
                r = await asyncio.wait_for(asyncio.shield(task), timeout=12)
                print("status:", r.status_code, r.text[:150])
            except asyncio.TimeoutError:
                print("HUNG — task stacks:")
                await dump_tasks()
                task.cancel()
                try:
                    await task
                except Exception:
                    pass


asyncio.run(main())
print("DONE")
