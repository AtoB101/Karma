"""Security headers + coarse rate limits (process-local; use edge gateway in production)."""

from __future__ import annotations

import time
from collections import defaultdict, deque
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse, Response


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        resp = await call_next(request)
        resp.headers["X-Content-Type-Options"] = "nosniff"
        resp.headers["X-Frame-Options"] = "DENY"
        resp.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
        resp.headers["Permissions-Policy"] = "accelerometer=(), camera=(), geolocation=(), microphone=(), payment=()"
        # API responses should not be cached at shared proxies by default
        if request.url.path.startswith(("/v1/", "/public/", "/health")):
            resp.headers["Cache-Control"] = "no-store"
        return resp


def _client_key(request: Request) -> str:
    """Best-effort client id; put BFF behind a trusted reverse proxy for real client IP."""
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()[:128]
    if request.client:
        return request.client.host
    return "unknown"


class RateLimitMiddleware(BaseHTTPMiddleware):
    """Sliding-window per (route_class, client). Not distributed — supplement with CDN/WAF."""

    def __init__(self, app, public_per_min: int = 120, integration_per_min: int = 300) -> None:
        super().__init__(app)
        self._public = public_per_min
        self._integration = integration_per_min
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._max_keys = 8000

    def _prune(self, key: str, window_sec: float = 60.0) -> None:
        dq = self._hits[key]
        now = time.time()
        while dq and now - dq[0] > window_sec:
            dq.popleft()

    def _allow(self, key: str, limit: int) -> bool:
        if len(self._hits) > self._max_keys:
            # crude shrink: drop half oldest keys (by key arbitrary)
            for k in list(self._hits.keys())[: self._max_keys // 2]:
                self._hits.pop(k, None)
        self._prune(key)
        dq = self._hits[key]
        now = time.time()
        if len(dq) >= limit:
            return False
        dq.append(now)
        return True

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        path = request.url.path
        ip = _client_key(request)
        if path.startswith("/public/") or path == "/health":
            lim = self._public if path.startswith("/public/") else min(self._public, 300)
            key = f"p:{ip}"
            if not self._allow(key, lim):
                return JSONResponse({"error": "rate_limited", "detail": "public tier"}, status_code=429)
        elif path.startswith("/v1/integration") or path.startswith("/v1/webhooks"):
            parts = path.split("/")
            bucket = parts[3] if len(parts) > 3 else "root"
            key = f"i:{ip}:{bucket}"
            if not self._allow(key, self._integration):
                return JSONResponse({"error": "rate_limited", "detail": "integration tier"}, status_code=429)
        return await call_next(request)
