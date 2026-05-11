"""
Karma Public API — FastAPI Application
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from prometheus_client import Counter, Histogram, make_asgi_app

from config.settings import settings
from db.session import init_db
from api.routes import (
    agents, auth, contracts, receipts,
    bundles, settlement, reputation, verify,
)

logger = structlog.get_logger(__name__)

# Prometheus metrics
REQUEST_COUNT = Counter(
    "karma_http_requests_total",
    "Total HTTP requests",
    ["method", "path", "status"],
)
REQUEST_LATENCY = Histogram(
    "karma_http_request_duration_seconds",
    "HTTP request latency",
    ["method", "path"],
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("karma_api_starting", env=settings.app_env)
    await init_db()
    yield
    logger.info("karma_api_shutdown")


app = FastAPI(
    title="Karma Trust Protocol API",
    description="Verifiable Agent Execution Runtime",
    version="0.1.0",
    lifespan=lifespan,
    docs_url="/docs",
    redoc_url="/redoc",
)

_origins = settings.cors_allow_origins_list()
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_methods=["*"],
    allow_headers=["*"],
    allow_credentials=False,
)


@app.middleware("http")
async def security_headers_middleware(request: Request, call_next) -> Response:
    response = await call_next(request)
    response.headers.setdefault("X-Content-Type-Options", "nosniff")
    response.headers.setdefault("X-Frame-Options", "DENY")
    response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
    return response


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next) -> Response:
    request_id = str(uuid.uuid4())[:8]
    start = time.perf_counter()

    log = logger.bind(
        request_id=request_id,
        method=request.method,
        path=request.url.path,
    )
    log.info("request_start")

    response = await call_next(request)
    elapsed = time.perf_counter() - start

    REQUEST_COUNT.labels(
        method=request.method,
        path=request.url.path,
        status=response.status_code,
    ).inc()
    REQUEST_LATENCY.labels(
        method=request.method,
        path=request.url.path,
    ).observe(elapsed)

    log.info("request_end", status=response.status_code, duration_ms=round(elapsed * 1000))
    response.headers["X-Request-Id"] = request_id
    return response


# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Routers
app.include_router(auth.router,       prefix="/v1/auth",       tags=["Auth"])
app.include_router(agents.router,     prefix="/v1/agents",     tags=["Agents"])
app.include_router(contracts.router,  prefix="/v1/contracts",  tags=["Contracts"])
app.include_router(receipts.router,   prefix="/v1/receipts",   tags=["Receipts"])
app.include_router(bundles.router,    prefix="/v1/bundles",    tags=["Bundles"])
app.include_router(verify.router,     prefix="/v1/verify",     tags=["Verification"])
app.include_router(settlement.router, prefix="/v1/settlement", tags=["Settlement"])
app.include_router(reputation.router, prefix="/v1/reputation", tags=["Reputation"])


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}


@app.get("/v1/info")
async def info():
    return {
        "name": "Karma Trust Protocol",
        "version": "0.1.0",
        "docs": "/docs",
        "schemas": "/v1/schemas",
    }
