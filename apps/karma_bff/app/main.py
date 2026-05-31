"""Karma BFF ASGI entrypoint."""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from apps.karma_bff.app import config
from apps.karma_bff.app.db import connect, init_schema
from apps.karma_bff.app.middleware_security import RateLimitMiddleware, SecurityHeadersMiddleware
from apps.karma_bff.app.routes_integration import router as integration_router
from apps.karma_bff.app.routes_bilateral import router as bilateral_router
from apps.karma_bff.app.routes_public import router as public_router
from apps.karma_bff.app.routes_webhooks import router as webhooks_router


@asynccontextmanager
async def lifespan(_: FastAPI):
    conn = connect(config.database_path())
    init_schema(conn)
    conn.close()
    yield


app = FastAPI(title="Karma BFF", version="0.1.1", lifespan=lifespan)

hosts = config.trusted_hosts()
if hosts:
    app.add_middleware(TrustedHostMiddleware, allowed_hosts=hosts)

app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    public_per_min=config.rate_limit_public_per_minute(),
    integration_per_min=config.rate_limit_integration_per_minute(),
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=config.cors_allow_origins(),
    allow_methods=["GET", "POST", "HEAD", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "X-Karma-Timestamp",
        "X-Karma-Signature",
        "Idempotency-Key",
        "Authorization",
    ],
    allow_credentials=False,
    max_age=600,
)

app.include_router(integration_router)
app.include_router(bilateral_router)
app.include_router(webhooks_router)
app.include_router(public_router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "service": "karma-bff", "database": config.database_path()}
