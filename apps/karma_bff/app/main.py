"""Karma BFF ASGI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from apps.karma_bff.app import config
from apps.karma_bff.app.db import connect, init_schema
from apps.karma_bff.app.routes_integration import router as integration_router
from apps.karma_bff.app.routes_public import router as public_router
from apps.karma_bff.app.routes_webhooks import router as webhooks_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    conn = connect(config.database_path())
    init_schema(conn)
    conn.close()
    yield


app = FastAPI(title="Karma BFF", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(integration_router)
app.include_router(webhooks_router)
app.include_router(public_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "karma-bff", "database": config.database_path()}
