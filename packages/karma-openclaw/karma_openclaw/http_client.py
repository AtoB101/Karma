"""Shared HTTP helpers for Karma public API and Runtime Gateway."""

from __future__ import annotations

import json
import os
from typing import Any

import httpx

from karma_openclaw.agent_binding import (
    agent_key_from_env,
    runtime_key_id,
    sign_runtime_request,
)


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


# 这把钥匙要不要带签名，只有服务端说了算：绑了 agent 公钥的钥匙少一个签名就 401，
# 没绑的钥匙带上签名反而 403。所以第一次调用之前先探一次 /runtime/permissions
# （读路径不落调用记录），结果缓存在进程里。主人刚在操作台输完匹配码时，探到
# 「要签名」就等于绑定已经生效 —— 见 refresh_signing_mode / _runtime_request。
_SIGNING_MODE: bool | None = None


def signing_mode() -> bool | None:
    """True / False = 探明了；None = 还没探过。"""
    return _SIGNING_MODE


def _set_signing_mode(value: bool) -> None:
    global _SIGNING_MODE
    _SIGNING_MODE = value


def reset_signing_mode() -> None:
    """换钥匙 / 换绑之后调用：下一次请求重新探一次。"""
    global _SIGNING_MODE
    _SIGNING_MODE = None


def runtime_headers(*, method: str = "GET", path: str = "", body: bytes = b"") -> dict[str, str]:
    """Runtime Key 请求头。探明这把钥匙绑了公钥时，顺带带上逐请求签名。

    签名消息由 karma_openclaw.agent_binding 构造，与服务端
    services.runtime_wallet.build_agent_request_message 逐字对齐。
    """
    h = api_headers()
    rk = runtime_key()
    if not rk:
        raise RuntimeError("KARMA_RUNTIME_KEY is not set")
    h["X-Karma-Runtime-Key"] = rk
    key = agent_key_from_env()
    if key is None or _SIGNING_MODE is not True:
        return h
    h.update(
        sign_runtime_request(
            key=key, key_id=runtime_key_id(rk), method=method, path=path, body=body
        )
    )
    return h


def _signature_required(resp: httpx.Response) -> bool:
    """服务端是不是在说「这把钥匙要签名」？用它判断绑定刚刚生效。"""
    try:
        detail = resp.json().get("detail")
    except Exception:  # noqa: BLE001
        return False
    return isinstance(detail, str) and "X-Karma-Agent-Signature" in detail


async def refresh_signing_mode() -> bool:
    """探一次 /runtime/permissions（读路径，不落调用记录），判断要不要签名。

    200 + key_binding=agent_pending → 还没激活，先不签（签了反而 403）；
    200 + key_binding=service → 不记名钥匙，签不签都花不了钱；
    401「X-Karma-Agent-Signature header is required」→ 绑定已生效，从这一刻起
    每个请求都要签名 —— 主人刚输完匹配码时就是这个信号。
    """
    rk = runtime_key()
    if not rk:
        raise RuntimeError("KARMA_RUNTIME_KEY is not set")
    if agent_key_from_env() is None:
        _set_signing_mode(False)
        return False
    headers = api_headers()
    headers["X-Karma-Runtime-Key"] = rk
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(f"{runtime_base_url()}/runtime/permissions", headers=headers)
    _set_signing_mode(bool(resp.status_code == 401 and _signature_required(resp)))
    return bool(_SIGNING_MODE)


def _detail_of(resp: httpx.Response) -> str:
    try:
        payload = resp.json()
    except Exception:  # noqa: BLE001
        return (resp.text or "")[:300]
    if isinstance(payload, dict) and payload.get("detail"):
        return str(payload["detail"])[:300]
    return (resp.text or "")[:300]


async def _runtime_request(method: str, path: str, payload: bytes = b"") -> httpx.Response:
    """所有 /runtime 请求都从这里走：该签名就签名，绑定刚生效时自动补签重试一次。"""
    if _SIGNING_MODE is None:
        await refresh_signing_mode()
    url = f"{runtime_base_url()}{path}"
    content = payload or None
    async with httpx.AsyncClient(timeout=120.0) as client:
        signed = runtime_headers(method=method, path=path, body=payload)
        resp = await client.request(method, url, headers=signed, content=content)
        must_retry_with_signature = resp.status_code == 401 and _signature_required(resp)
        if must_retry_with_signature and _SIGNING_MODE is not True:
            # 主人刚在操作台输完匹配码：这次探到「要签名」了，补上签名重发一次。
            _set_signing_mode(True)
            resp = await client.request(
                method,
                url,
                headers=runtime_headers(method=method, path=path, body=payload),
                content=content,
            )
    return resp


def _runtime_json(resp: httpx.Response) -> Any:
    """把服务端原话带进异常 —— agent 要靠这段 detail 认出「钥匙还没激活」。"""
    if resp.is_error:
        raise httpx.HTTPStatusError(
            f"{resp.status_code} from runtime gateway: {_detail_of(resp)}",
            request=resp.request,
            response=resp,
        )
    return resp.json()


def runtime_json_body(body: Any) -> bytes:
    """请求体字节 —— 签名算的就是这几个字节，别在别处再序列化一遍。"""
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


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
    return _runtime_json(await _runtime_request("POST", path, runtime_json_body(body)))


async def runtime_get(path: str) -> Any:
    return _runtime_json(await _runtime_request("GET", path))
