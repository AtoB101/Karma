"""L4 后端客户端 —— 唯一允许出网的地方。

职责：注入 ``X-Karma-Runtime-Key`` + 逐请求 Agent 签名；传 ``client_nonce`` /
``Idempotency-Key``；把 HTTP 结果归类成 ``KarmaToolError``。

**不做**：不代签钱包交易、不持有私钥、不做额度/风控/状态机判定。
"""

from __future__ import annotations

import json
from typing import Any

import httpx

from karma_mcp_server.agent_signing import (
    agent_key_from_seed,
    runtime_key_id,
    sign_runtime_request,
)
from karma_mcp_server.config import McpConfig
from karma_mcp_server.credentials import credential
from karma_mcp_server.errors import ErrorClass, KarmaToolError, classify_http_status
from karma_mcp_server.redact import fingerprint

_SIGNATURE_REQUIRED_MARKER = "X-Karma-Agent-Signature"


def _encode(body: Any) -> bytes:
    if body is None:
        return b""
    return json.dumps(body, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


class KarmaBackend:
    """对 Karma 后端的薄封装。一个实例 = 一个进程的凭据视图。"""

    def __init__(
        self,
        config: McpConfig,
        *,
        runtime_key: str | None = None,
        api_key: str | None = None,
        agent_private_key_seed: str | None = None,
        transport: httpx.AsyncBaseTransport | None = None,
        credential_fn=credential,
    ) -> None:
        self._config = config
        self._credential = credential_fn
        self._transport = transport
        self._explicit_runtime_key = runtime_key
        self._explicit_api_key = api_key
        self._explicit_seed = agent_private_key_seed
        self._signing_mode: bool | None = None

    # ---- 凭据（只读） --------------------------------------------------
    def runtime_key(self) -> str:
        if self._explicit_runtime_key is not None:
            return self._explicit_runtime_key.strip()
        return self._credential("KARMA_RUNTIME_KEY")

    def has_runtime_key(self) -> bool:
        return bool(self.runtime_key())

    def api_key(self) -> str:
        """公共 API（``/v1/*``）用的 key。配对前为空是正常的。"""
        if self._explicit_api_key is not None:
            return self._explicit_api_key.strip()
        return self._credential("KARMA_API_KEY")

    def key_fingerprint(self) -> str:
        return fingerprint(self.runtime_key())

    def _agent_key(self):
        seed = (
            self._explicit_seed
            if self._explicit_seed is not None
            else self._credential("KARMA_AGENT_PRIVATE_KEY")
        )
        if not seed:
            return None
        try:
            return agent_key_from_seed(seed)
        except Exception:  # noqa: BLE001 - 种子坏了就当没有，走「不签名」这条老路
            return None

    # ---- 出网 ----------------------------------------------------------
    def _headers(
        self, *, method: str, path: str, body: bytes, runtime: bool = True
    ) -> dict[str, str]:
        h = {"Content-Type": "application/json", "Accept": "application/json"}
        ak = self.api_key()
        if ak and not runtime:
            h["X-Karma-Api-Key"] = ak
        rk = self.runtime_key()
        if not rk:
            raise KarmaToolError(
                ErrorClass.UNAUTHORIZED,
                "no Runtime Key configured for this MCP server",
            )
        h["X-Karma-Runtime-Key"] = rk
        key = self._agent_key()
        if key is not None and self._signing_mode is True:
            h.update(
                sign_runtime_request(
                    key=key, key_id=runtime_key_id(rk), method=method, path=path, body=body
                )
            )
        return h

    @staticmethod
    def _detail(resp: httpx.Response) -> str:
        try:
            payload = resp.json()
        except Exception:  # noqa: BLE001
            return (resp.text or "")[:300]
        if isinstance(payload, dict) and payload.get("detail"):
            return str(payload["detail"])[:300]
        return (resp.text or "")[:300]

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=httpx.Timeout(self._config.write_timeout_seconds),
            transport=self._transport,
        )

    async def _probe_signing_mode(self, client: httpx.AsyncClient) -> bool:
        """探一次这把钥匙要不要签名（读路径，不落调用记录）。"""
        if not self.has_runtime_key():
            self._signing_mode = False
            return False
        if self._agent_key() is None:
            self._signing_mode = False
            return False
        url = self._config.runtime_base_url + "/runtime/permissions"
        headers = {"Content-Type": "application/json", "X-Karma-Runtime-Key": self.runtime_key()}
        try:
            resp = await client.get(url, headers=headers)
        except httpx.HTTPError:
            self._signing_mode = False
            return False
        self._signing_mode = bool(
            resp.status_code == 401 and _SIGNATURE_REQUIRED_MARKER in self._detail(resp)
        )
        return self._signing_mode

    async def request(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        runtime: bool = True,
        extra_headers: dict[str, str] | None = None,
    ) -> Any:
        payload = _encode(body)
        url = self._config.runtime_base_url + path
        async with self._client() as client:
            if runtime and self._signing_mode is None:
                await self._probe_signing_mode(client)
            headers = self._headers(method=method, path=path, body=payload, runtime=runtime)
            if extra_headers:
                headers = {**headers, **extra_headers}
            try:
                resp = await client.request(method, url, headers=headers, content=payload or None)
            except httpx.TimeoutException as exc:
                raise KarmaToolError(ErrorClass.TRANSPORT, f"request to {path} timed out") from exc
            except httpx.HTTPError as exc:
                raise KarmaToolError(
                    ErrorClass.TRANSPORT, f"cannot reach Karma backend at {path}"
                ) from exc

            # 主人刚在操作台输完配对码：这一刻服务端开始要求签名，补签重发一次。
            if (
                resp.status_code == 401
                and self._agent_key() is not None
                and self._signing_mode is not True
                and _SIGNATURE_REQUIRED_MARKER in self._detail(resp)
            ):
                self._signing_mode = True
                headers = self._headers(method=method, path=path, body=payload, runtime=runtime)
                if extra_headers:
                    headers = {**headers, **extra_headers}
                resp = await client.request(method, url, headers=headers, content=payload or None)

            if resp.is_error:
                detail = self._detail(resp)
                raise KarmaToolError(
                    classify_http_status(resp.status_code, detail),
                    detail or f"backend returned {resp.status_code}",
                    http_status=resp.status_code,
                )
            if not resp.content:
                return {}
            return resp.json()

    # ---- 便捷方法 ------------------------------------------------------
    async def runtime_get(self, path: str) -> Any:
        return await self.request("GET", path, runtime=True)

    async def runtime_post(
        self, path: str, body: Any, *, extra_headers: dict[str, str] | None = None
    ) -> Any:
        return await self.request(
            "POST", path, body=body, runtime=True, extra_headers=extra_headers
        )

    async def api_get(self, path: str) -> Any:
        return await self.request("GET", path, runtime=False)
