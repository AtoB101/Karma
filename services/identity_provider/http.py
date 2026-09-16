"""
Karma — 适配层出网的那几个调用（单独一层，方便离线测试替换）。

适配器只在这里碰网络：测试里把这几个函数换成假的，就能把「服务商说什么」这件事
完整地跑一遍，不需要真的去连阿里云 / 腾讯云 / Persona。
"""
from __future__ import annotations

from typing import Any

import httpx

from services.identity_provider.base import ProviderError

DEFAULT_TIMEOUT_SECONDS = 10.0


def _fail(action: str, exc: Exception) -> ProviderError:
    return ProviderError(502, f"identity provider call failed ({action}): {exc}")


async def post_form(url: str, data: dict[str, Any], *, timeout: float = DEFAULT_TIMEOUT_SECONDS) -> dict:
    """表单 POST（阿里云 RPC 风格）。"""
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, data=data)
    except Exception as exc:  # noqa: BLE001 — 网络层任何异常都归一到 502
        raise _fail("post_form", exc) from exc
    if response.status_code >= 400:
        raise ProviderError(502, f"identity provider returned HTTP {response.status_code} (post_form)")
    try:
        return response.json()
    except Exception as exc:  # noqa: BLE001
        raise _fail("post_form json", exc) from exc


async def post_json(
    url: str,
    payload: dict[str, Any],
    headers: dict[str, str] | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(url, json=payload, headers=headers or {})
    except Exception as exc:  # noqa: BLE001
        raise _fail("post_json", exc) from exc
    if response.status_code >= 400:
        raise ProviderError(
            502, f"identity provider returned HTTP {response.status_code} (post_json)"
        )
    try:
        return response.json()
    except Exception as exc:  # noqa: BLE001
        raise _fail("post_json json", exc) from exc


async def get_json(
    url: str, headers: dict[str, str] | None = None, *, timeout: float = DEFAULT_TIMEOUT_SECONDS
) -> dict:
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.get(url, headers=headers or {})
    except Exception as exc:  # noqa: BLE001
        raise _fail("get_json", exc) from exc
    if response.status_code >= 400:
        raise ProviderError(
            502, f"identity provider returned HTTP {response.status_code} (get_json)"
        )
    try:
        return response.json()
    except Exception as exc:  # noqa: BLE001
        raise _fail("get_json json", exc) from exc
