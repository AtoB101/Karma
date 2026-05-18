"""
Karma Public API — FastAPI Application
"""
from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from prometheus_client import Counter, Histogram, make_asgi_app

from config.settings import settings
from api.middleware.auth import get_current_agent_id, require_auth_if_enabled, resolve_agent_id_from_auth_headers
from api.middleware.rate_limit import rate_limit
from services.security_monitoring import SecurityMonitoringEventType, record_security_event
from db.session import init_db
from api.routes import (
    agents,
    auth,
    contracts,
    receipts,
    bundles,
    settlement,
    reputation,
    verify,
    capacity,
    vouchers,
    progress,
    identities,
    arbitration,
    responsibility,
    security,
    admin_controls,
    runtime_gateway,
    openclaw,
    payment_codes,
    trade,
    x402,
    payment_intents,
    evidence,
)

logger = structlog.get_logger(__name__)
security_audit_logger = structlog.get_logger("security.audit")
SENSITIVE_WRITE_PREFIXES = (
    "/v1/settlement/",
    "/v1/trade/",
    "/v1/payment-codes",
    "/v1/arbitration/",
    "/v1/vouchers/",
    "/v1/verify",
    "/v1/progress/",
    "/v1/capacity/",
    "/v1/receipts",
    "/v1/bundles",
    "/v1/responsibility/",
    "/v1/security/",
    "/v1/admin/",
    "/v1/contracts/",
    "/v1/agents/",
    "/v1/identities/",
    "/runtime/",
)
STATE_TRANSITION_SEGMENTS = (
    "/lock",
    "/start",
    "/submit",
    "/fail",
    "/partial",
    "/regret",
    "/dispute",
    "/auto-arbitrate",
    "/execute",
    "/accept",
    "/cancel",
    "/retry",
    "/requeue",
    "/maintenance/",
)

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
    # Prevent shared-cache storage of authenticated API payloads (CDN / browser back/forward cache).
    if request.url.path.startswith("/v1/") or request.url.path.startswith("/runtime/"):
        response.headers.setdefault("Cache-Control", "private, no-store")
    return response


def _is_sensitive_write(path: str, method: str) -> bool:
    if method.upper() not in {"POST", "PUT", "PATCH", "DELETE"}:
        return False
    return any(path.startswith(prefix) for prefix in SENSITIVE_WRITE_PREFIXES)


def _is_state_transition_write(path: str) -> bool:
    return any(segment in path for segment in STATE_TRANSITION_SEGMENTS)


def _route_group_for_path(path: str) -> str:
    if path.startswith("/v1/auth"):
        return "auth"
    if path.startswith("/runtime"):
        return "runtime"
    if path.startswith("/v1/verify"):
        return "verification"
    if path.startswith("/v1/settlement"):
        return "settlement"
    if path.startswith("/v1/arbitration"):
        return "arbitration"
    if path.startswith("/v1/responsibility"):
        return "responsibility"
    if path.startswith("/v1/vouchers"):
        return "vouchers"
    if path.startswith("/v1/capacity"):
        return "capacity"
    if path.startswith("/v1/progress"):
        return "progress"
    return "other"


@app.middleware("http")
async def security_write_rate_limit_middleware(request: Request, call_next) -> Response:
    path = request.url.path
    method = request.method.upper()
    if _is_sensitive_write(path, method):
        limit_key = "state_transition" if _is_state_transition_write(path) else "write_sensitive"
        try:
            await rate_limit(request, limit_key)
        except HTTPException as exc:
            return JSONResponse(
                status_code=exc.status_code,
                content={"detail": exc.detail},
                headers=exc.headers or {},
            )
    return await call_next(request)


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


@app.middleware("http")
async def security_audit_middleware(request: Request, call_next) -> Response:
    response = await call_next(request)
    path = request.url.path
    method = request.method.upper()
    route_group = _route_group_for_path(path)
    actor_id = resolve_agent_id_from_auth_headers(
        authorization=request.headers.get("Authorization"),
        api_key=request.headers.get("X-Karma-Api-Key"),
    )
    actor_label = actor_id or "anonymous"
    if _is_sensitive_write(path, method):
        security_audit_logger.info(
            "security_write_audit",
            method=method,
            path=path,
            route_group=route_group,
            status=response.status_code,
            actor_id=actor_id,
            request_id=response.headers.get("X-Request-Id"),
        )
    if path.startswith("/v1/") and response.status_code == 401:
        record_security_event(
            SecurityMonitoringEventType.FAILED_AUTH,
            metadata={
                "path": path,
                "method": method,
                "status": response.status_code,
                "actor_id": actor_label,
                "route_group": route_group,
            },
        )
    if path.startswith("/v1/") and response.status_code == 429:
        record_security_event(
            SecurityMonitoringEventType.RATE_LIMIT_EXCEEDED,
            metadata={
                "path": path,
                "method": method,
                "status": response.status_code,
                "actor_id": actor_label,
                "route_group": route_group,
            },
        )
    if path == "/v1/verify" and method == "POST":
        record_security_event(
            SecurityMonitoringEventType.VERIFY_REQUEST,
            metadata={
                "path": path,
                "method": method,
                "status": response.status_code,
                "actor_id": actor_label,
                "route_group": route_group,
            },
        )
        if response.status_code in {502, 503}:
            record_security_event(
                SecurityMonitoringEventType.PRIVATE_RUNTIME_ERROR,
                metadata={
                    "path": path,
                    "method": method,
                    "status": response.status_code,
                    "actor_id": actor_label,
                    "route_group": route_group,
                },
            )
    return response


# Prometheus metrics endpoint
metrics_app = make_asgi_app()
app.mount("/metrics", metrics_app)

# Routers
app.include_router(runtime_gateway.router, prefix="/runtime", tags=["Runtime Gateway"])
app.include_router(auth.router,       prefix="/v1/auth",       tags=["Auth"])
_protected_dependencies = [Depends(require_auth_if_enabled)]
_security_always_auth = [Depends(get_current_agent_id)]
app.include_router(agents.router,     prefix="/v1/agents",     tags=["Agents"], dependencies=_protected_dependencies)
app.include_router(contracts.router,  prefix="/v1/contracts",  tags=["Contracts"], dependencies=_protected_dependencies)
app.include_router(identities.router, prefix="/v1/identities", tags=["Identities"], dependencies=_protected_dependencies)
app.include_router(arbitration.router, prefix="/v1/arbitration", tags=["Arbitration"], dependencies=_protected_dependencies)
app.include_router(responsibility.router, prefix="/v1/responsibility", tags=["Responsibility"], dependencies=_protected_dependencies)
app.include_router(capacity.router,   prefix="/v1/capacity",   tags=["Capacity"], dependencies=_protected_dependencies)
app.include_router(vouchers.router,   prefix="/v1/vouchers",   tags=["Vouchers"], dependencies=_protected_dependencies)
app.include_router(
    payment_codes.router,
    prefix="/v1/payment-codes",
    tags=["PaymentCodes"],
    dependencies=_protected_dependencies,
)
app.include_router(
    trade.router,
    prefix="/v1/trade",
    tags=["Trade"],
    dependencies=_protected_dependencies,
)
app.include_router(
    x402.router,
    prefix="/v1/x402",
    tags=["X402"],
    dependencies=_protected_dependencies,
)
app.include_router(
    payment_intents.router,
    prefix="/v1/payment-intents",
    tags=["PaymentIntents"],
    dependencies=_protected_dependencies,
)
app.include_router(
    evidence.router,
    prefix="/v1/evidence",
    tags=["Evidence"],
    dependencies=_protected_dependencies,
)
app.include_router(progress.router,   prefix="/v1/progress",   tags=["Progress"], dependencies=_protected_dependencies)
app.include_router(receipts.router,   prefix="/v1/receipts",   tags=["Receipts"], dependencies=_protected_dependencies)
app.include_router(bundles.router,    prefix="/v1/bundles",    tags=["Bundles"], dependencies=_protected_dependencies)
app.include_router(verify.router,     prefix="/v1/verify",     tags=["Verification"], dependencies=_protected_dependencies)
app.include_router(settlement.router, prefix="/v1/settlement", tags=["Settlement"], dependencies=_protected_dependencies)
app.include_router(reputation.router, prefix="/v1/reputation", tags=["Reputation"], dependencies=_protected_dependencies)
app.include_router(security.router,   prefix="/v1/security",   tags=["Security"], dependencies=_security_always_auth)
app.include_router(admin_controls.router, prefix="/v1/admin", tags=["Admin"], dependencies=_security_always_auth)
app.include_router(openclaw.router, prefix="/v1/openclaw", tags=["OpenClaw"], dependencies=_protected_dependencies)


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
        "verify_auth": {
            "enforcement": bool(settings.auth_enforce_protected_routes),
            "post_verify_requires_credentials_when_enforcement_on": True,
            "note": "When auth enforcement is off, POST /v1/verify accepts anonymous actor label anonymous-verify.",
        },
        "runtime_gateway_prefix": "/runtime",
        "security_and_admin_auth": {
            "always_requires_credentials": True,
            "path_prefixes": ["/v1/security", "/v1/admin"],
            "note": (
                "Bearer JWT or X-Karma-Api-Key is required for these route trees even when "
                "AUTH_ENFORCE_PROTECTED_ROUTES is false."
            ),
        },
        "execution_receipt_timestamp_guards": {
            "strict_recent_timestamps": bool(settings.receipt_strict_recent_timestamps),
            "max_past_hours_when_strict": int(settings.receipt_max_past_hours_strict),
            "progress_receipt_max_past_hours": int(settings.receipt_max_past_hours),
            "note": (
                "When strict_recent_timestamps is true, execution receipt started_at/ended_at may not be older "
                "than max_past_hours_when_strict. Progress receipts still use progress_receipt_max_past_hours "
                "(receipt_max_past_hours) for long-window flows such as timeout confirmation."
            ),
        },
        "settlement_guards": {
            "lock_requires_pending": bool(settings.settlement_lock_requires_pending),
            "requires_success_execution_receipt_for_seller_release": bool(
                settings.settlement_requires_success_execution_receipt_for_seller_release
            ),
            "block_buyer_worker_payment_cycle": bool(settings.settlement_block_buyer_worker_payment_cycle),
        },
    }
