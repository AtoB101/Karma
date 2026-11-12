"""
KarmaRuntime — minimal async HTTP client for the public ``/runtime`` gateway.

Uses only a Runtime Key (never wallet private keys). See ``docs/runtime-key-guide.md``.
"""
from __future__ import annotations

import hashlib
import hmac
import inspect
import json
import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, TypeVar

import httpx

T = TypeVar("T")


def _sha256_hex(data: Any) -> str:
    if isinstance(data, bytes):
        raw = data
    elif isinstance(data, str):
        raw = data.encode()
    else:
        raw = json.dumps(data, sort_keys=True, separators=(",", ":"), default=str).encode()
    return hashlib.sha256(raw).hexdigest()


def _verify_hmac(*, body_text: str, signature_header: str | None, secret: str) -> None:
    if not secret:
        return
    if not signature_header or not signature_header.startswith("sha256="):
        raise RuntimeError("missing or invalid X-Karma-Response-Signature header")
    digest = signature_header.split("=", 1)[1]
    expected = hmac.new(secret.encode(), body_text.encode("utf-8"), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(digest, expected):
        raise RuntimeError("response HMAC verification failed")


class KarmaRuntime:
    """
    Agent-facing client for ``/runtime`` endpoints.

    This class never handles wallet private keys or mnemonic phrases.
    """

    def __init__(
        self,
        *,
        runtime_key: str,
        runtime_url: str = "https://runtime.karma.network",
        expected_chain_id: int | None = None,
        timeout: float = 120.0,
        app_secret_for_hmac: str | None = None,
    ):
        self.runtime_key = runtime_key.strip()
        self.runtime_url = runtime_url.rstrip("/")
        if self.runtime_url.startswith("http://") and "localhost" not in self.runtime_url:
            if "127.0.0.1" not in self.runtime_url:
                raise ValueError("runtime_url must use https except for localhost development")
        self.expected_chain_id = expected_chain_id
        self.timeout = timeout
        self._app_secret_for_hmac = (
            app_secret_for_hmac
            if app_secret_for_hmac is not None
            else (os.environ.get("KARMA_APP_SECRET") or "")
        )
        self._headers = {
            "X-Karma-Runtime-Key": self.runtime_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }
        self._submitted_receipt_ids: set[str] = set()
        self._receipt_steps: dict[str, int] = {}
        self._cached_identity: str | None = None

    @classmethod
    def from_env(cls) -> "KarmaRuntime":
        key = (os.environ.get("KARMA_RUNTIME_KEY") or "").strip()
        url = (os.environ.get("KARMA_RUNTIME_URL") or "https://runtime.karma.network").strip()
        if not key:
            raise ValueError("KARMA_RUNTIME_KEY is not set")
        chain_raw = os.environ.get("KARMA_EXPECTED_CHAIN_ID", "").strip()
        chain = int(chain_raw) if chain_raw.isdigit() else None
        return cls(runtime_key=key, runtime_url=url, expected_chain_id=chain)

    def _parse_response(self, resp: httpx.Response) -> Any:
        text = resp.text
        try:
            data = json.loads(text) if text else None
        except json.JSONDecodeError as exc:
            raise RuntimeError("runtime response is not valid JSON") from exc
        if resp.is_error:
            detail = data.get("detail") if isinstance(data, dict) else data
            raise RuntimeError(f"HTTP {resp.status_code}: {detail}")
        sig = resp.headers.get("X-Karma-Response-Signature")
        if self._app_secret_for_hmac and sig:
            _verify_hmac(body_text=text, signature_header=sig, secret=self._app_secret_for_hmac)
        return data

    async def _identity(self) -> str:
        if self._cached_identity:
            return self._cached_identity
        p = await self.get_permissions()
        self._cached_identity = str(p.get("karma_identity_id") or "")
        return self._cached_identity

    async def verify_key(self) -> dict[str, Any]:
        return await self.get_permissions()

    async def get_permissions(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            r = await http.get(f"{self.runtime_url}/runtime/permissions", headers=self._headers)
        data = self._parse_response(r)
        if not isinstance(data, dict):
            raise RuntimeError("unexpected permissions payload")
        if self.expected_chain_id is not None and int(data.get("chain_id") or 0) != int(
            self.expected_chain_id
        ):
            raise RuntimeError("chain_id mismatch between SDK expectation and runtime permissions")
        return data

    async def get_capacity(self) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            r = await http.get(f"{self.runtime_url}/runtime/capacity", headers=self._headers)
        return self._parse_response(r)

    async def request_voucher(self, voucher: dict[str, Any], *, client_nonce: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            r = await http.post(
                f"{self.runtime_url}/runtime/request-voucher",
                headers=self._headers,
                json={"client_nonce": client_nonce, "voucher": voucher},
            )
        return self._parse_response(r)

    async def submit_receipt(self, receipt: dict[str, Any]) -> dict[str, Any]:
        rid = str(receipt.get("receipt_id") or "")
        if rid in self._submitted_receipt_ids:
            raise RuntimeError(f"duplicate receipt submission blocked locally: {rid}")
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            r = await http.post(
                f"{self.runtime_url}/runtime/submit-receipt",
                headers=self._headers,
                json=receipt,
            )
        out = self._parse_response(r)
        if rid:
            self._submitted_receipt_ids.add(rid)
        return out

    async def update_progress(self, progress: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            r = await http.post(
                f"{self.runtime_url}/runtime/update-progress",
                headers=self._headers,
                json=progress,
            )
        return self._parse_response(r)

    async def request_settlement(self, payload: dict[str, Any]) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            r = await http.post(
                f"{self.runtime_url}/runtime/request-settlement",
                headers=self._headers,
                json=payload,
            )
        return self._parse_response(r)

    async def get_task_status(self, task_id: str) -> dict[str, Any]:
        async with httpx.AsyncClient(timeout=self.timeout) as http:
            r = await http.get(
                f"{self.runtime_url}/runtime/task-status/{task_id}",
                headers=self._headers,
            )
        return self._parse_response(r)

    def revoke_session(self) -> None:
        """Clear local SDK state (does not revoke the server-side key without Console wallet flow)."""
        self._submitted_receipt_ids.clear()
        self._receipt_steps.clear()
        self._cached_identity = None

    async def wrap_tool_call(
        self,
        *,
        task_id: str,
        tool_name: str,
        fn: Callable[..., Any],
        input_data: Any,
        agent_signature: str = "runtime-sdk",
    ) -> T:
        input_digest = _sha256_hex(input_data)
        started = time.perf_counter()
        status_code = 200
        err: str | None = None
        result: Any = None
        try:
            if inspect.iscoroutinefunction(fn):
                result = await fn(input_data)  # type: ignore[misc]
            else:
                result = fn(input_data)  # type: ignore[misc]
        except Exception as exc:
            status_code = 500
            err = str(exc)
            result = None
        duration_ms = int((time.perf_counter() - started) * 1000)
        output_digest = _sha256_hex(result if status_code < 400 else {"error": err})
        now = datetime.now(timezone.utc)
        started_ts = now - timedelta(milliseconds=duration_ms)
        log_envelope = {
            "task_id": task_id,
            "tool_name": tool_name,
            "input_digest": input_digest,
            "output_digest": output_digest,
            "duration_ms": duration_ms,
            "status_code": status_code,
        }
        runtime_log_hash = _sha256_hex(log_envelope)
        step = self._receipt_steps.get(task_id, 0) + 1
        self._receipt_steps[task_id] = step
        receipt = {
            "receipt_id": str(uuid.uuid4()),
            "task_id": task_id,
            "agent_id": await self._identity(),
            "step_index": step,
            "tool_name": tool_name,
            "input_hash": input_digest,
            "output_hash": output_digest,
            "started_at": started_ts.isoformat(),
            "ended_at": now.isoformat(),
            "duration_ms": duration_ms,
            "status": "success" if status_code < 400 else "failure",
            "error_message": err,
            "metadata": {
                "runtime_log_hash": runtime_log_hash,
                "status_code": status_code,
                "agent_signature": agent_signature,
            },
        }
        try:
            await self.submit_receipt(receipt)
        finally:
            try:
                await self.get_task_status(task_id)
            except Exception:
                pass
        if status_code >= 400:
            raise RuntimeError(err or "tool execution failed")
        return result  # type: ignore[return-value]
