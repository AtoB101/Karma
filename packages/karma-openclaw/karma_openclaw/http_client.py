"""Shared HTTP helpers for Karma public API and Runtime Gateway."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx


def runtime_base_url() -> str:
    return os.environ.get("KARMA_RUNTIME_URL", "http://localhost:8000").strip().rstrip("/")


def api_key() -> str | None:
    k = os.environ.get("KARMA_API_KEY", "").strip()
    return k or None


def runtime_key() -> str | None:
    k = os.environ.get("KARMA_RUNTIME_KEY", "").strip()
    return k or None


def api_headers() -> dict[str, str]:
    h: dict[str, str] = {"Content-Type": "application/json"}
    key = api_key()
    if key:
        h["X-Karma-Api-Key"] = key
    return h


def runtime_headers() -> dict[str, str]:
    h = api_headers()
    rk = runtime_key()
    if not rk:
        raise RuntimeError("KARMA_RUNTIME_KEY is not set")
    h["X-Karma-Runtime-Key"] = rk
    return h


async def api_get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.get(f"{runtime_base_url()}{path}", headers=api_headers())
        r.raise_for_status()
        if r.headers.get("content-type", "").startswith("application/json"):
            return r.json()
        return r.text


def _merge_headers(extra: dict[str, str] | None = None) -> dict[str, str]:
    h = api_headers()
    if extra:
        h.update(extra)
    return h


async def api_post(
    path: str,
    body: Any,
    *,
    idempotency_key: str | None = None,
    extra_headers: dict[str, str] | None = None,
) -> Any:
    headers = _merge_headers(extra_headers)
    if idempotency_key:
        headers["Idempotency-Key"] = idempotency_key
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{runtime_base_url()}{path}",
            headers=headers,
            content=json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        )
        r.raise_for_status()
        return r.json()


async def api_put(path: str, body: Any) -> Any:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.put(
            f"{runtime_base_url()}{path}",
            headers=api_headers(),
            content=json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        )
        r.raise_for_status()
        return r.json()


async def runtime_post(path: str, body: Any) -> Any:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.post(
            f"{runtime_base_url()}{path}",
            headers=runtime_headers(),
            content=json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8"),
        )
        r.raise_for_status()
        return r.json()


async def runtime_get(path: str) -> Any:
    async with httpx.AsyncClient(timeout=120.0) as client:
        r = await client.get(f"{runtime_base_url()}{path}", headers=runtime_headers())
        r.raise_for_status()
        return r.json()
