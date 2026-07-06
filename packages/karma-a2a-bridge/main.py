import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from a2a_server import router as a2a_router, set_agent_card, get_agent_card
from card_builder import build_agent_card
from registry_client import RegistryClient
import config

registry = RegistryClient(base_url=config.REGISTRY_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    card = build_agent_card(
        agent_id=config.AGENT_ID,
        name=config.AGENT_NAME,
        description=config.AGENT_DESCRIPTION,
        capabilities=config.AGENT_CAPABILITIES,
        endpoint=config.AGENT_ENDPOINT,
        icon_url=config.AGENT_ICON_URL,
    )
    set_agent_card(card)

    registered = registry.register(card)
    print(f"[A2A] Registered to {config.REGISTRY_URL}: {registered}")

    async def heartbeat_loop():
        while True:
            await asyncio.sleep(config.HEARTBEAT_INTERVAL)
            ok = registry.heartbeat(config.AGENT_ID)
            if not ok:
                print(f"[A2A] Heartbeat failed for {config.AGENT_ID}")

    task = asyncio.create_task(heartbeat_loop())
    yield
    task.cancel()
    registry.unregister(config.AGENT_ID)
    print(f"[A2A] Unregistered {config.AGENT_ID}")


app = FastAPI(title="Karma A2A Bridge", version="0.1.0", lifespan=lifespan)
app.include_router(a2a_router)


@app.get("/health")
async def health():
    return {"status": "ok", "agent_id": config.AGENT_ID}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
