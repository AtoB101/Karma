"""FastMCP 实例与工具注册。

分层：
* Tier 0 只读 —— 连接 / 身份 / 授权状态 / 交易 / 结算 / 信誉查询。
* Tier 1 授权 —— 铸造 / 更新 / 撤销 Runtime Key（**必须**主人钱包签名）。
* Tier 2 交易 —— 下单 / 确认 / 证据 / 回执 / 结算请求（默认不注册）。
* Tier 3 资金 —— 争议 / 退款 / 凭证校验（默认不注册）。

每条工具返回 ``{"ok": true, ...}`` 或 ``{"ok": false, "error": {...}}`` ——
**永不**用成功结构包装失败。
"""

from __future__ import annotations

import json
from collections.abc import Awaitable, Callable
from typing import Any

from mcp.server.auth.provider import TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP

from karma_mcp_server.backend_client import KarmaBackend
from karma_mcp_server.config import McpConfig, load_config
from karma_mcp_server.credential_store import write_env_file
from karma_mcp_server.errors import ErrorClass, KarmaToolError, ok
from karma_mcp_server.pairing import (
    credentials_env_text,
    load_pairing,
    resolve_pairing_code,
    save_pairing,
)
from karma_mcp_server.redact import fingerprint, redact_wallet
from karma_mcp_server.wallet_messages import (
    build_create_key_message,
    build_revoke_key_message,
)

INSTRUCTIONS = (
    "Karma MCP server - connect an agent to Karma, read authorization boundaries, "
    "and (when enabled) trade within them."
    + chr(10)
    + chr(10)
    + "Karma backend is authoritative: identity, authorization, limits, risk and the "
    "funding state machine are all decided server-side. A successful tool call is NOT "
    "a successful trade."
    + chr(10)
    + chr(10)
    + "This process holds no private key: only KARMA_RUNTIME_KEY. Wallet signatures "
    "are always produced by the user's own wallet."
)

#: 复杂制品（回执 / 进度 / 证据包）的透传上限，防超长载荷。
MAX_ARTIFACT_CHARS = 200_000

PLATFORM = "mcp"


def build_server(
    config: McpConfig | None = None,
    *,
    backend: KarmaBackend | None = None,
    token_verifier: TokenVerifier | None = None,
    auth_settings: AuthSettings | None = None,
) -> FastMCP:
    cfg = config or load_config()
    be = backend or KarmaBackend(cfg)
    tiers = cfg.allowed_tiers()

    mcp = FastMCP(
        "karma-mcp-server",
        instructions=INSTRUCTIONS,
        token_verifier=token_verifier,
        auth=auth_settings,
    )

    async def _guard(fn: Callable[[], Awaitable[dict[str, Any]]]) -> dict[str, Any]:
        try:
            return await fn()
        except KarmaToolError as exc:
            return exc.as_dict()
        except Exception as exc:  # noqa: BLE001
            return KarmaToolError(
                ErrorClass.BACKEND, "unexpected error: " + type(exc).__name__
            ).as_dict()

    def _artifact(payload: dict[str, Any], *, require_task_id: bool = True) -> dict[str, Any]:
        if not isinstance(payload, dict):
            raise KarmaToolError(ErrorClass.INVALID, "payload must be a JSON object")
        if require_task_id and not str(payload.get("task_id") or "").strip():
            raise KarmaToolError(ErrorClass.INVALID, "payload.task_id is required")
        raw = json.dumps(payload, ensure_ascii=False)
        if len(raw) > MAX_ARTIFACT_CHARS:
            raise KarmaToolError(
                ErrorClass.INVALID,
                "payload exceeds " + str(MAX_ARTIFACT_CHARS) + " characters",
            )
        return payload

    async def _current_identity() -> str:
        data = await be.runtime_get("/runtime/permissions")
        return str(data.get("karma_identity_id") or "")

    # ================= Tier 0: 连接 =================

    async def karma_connect(
        agent_name: str, self_description: str = "", platform: str = PLATFORM
    ) -> dict[str, Any]:
        """申请接入 Karma：返回 user_code 与 verification_uri 交给主人。

        这一步不花钱、也不产生任何权限 —— 只是让主人在操作台看到「谁在申请」。
        pairing_code 只落在本机 0600 文件里，聊天里不出现。
        """

        async def _run() -> dict[str, Any]:
            name = (agent_name or "").strip()
            if not name:
                raise KarmaToolError(ErrorClass.INVALID, "agent_name is required")
            from karma_mcp_server.agent_signing import (
                agent_public_key_b64,
                agent_public_key_fingerprint,
                ensure_local_agent_key,
                sign_pairing_request,
            )

            key = ensure_local_agent_key()
            body: dict[str, Any] = {
                "agent_name": name,
                "platform": (platform or PLATFORM).strip() or PLATFORM,
            }
            if (self_description or "").strip():
                body["self_description"] = self_description.strip()
            if key is not None:
                public_key = agent_public_key_b64(key)
                body["public_key"] = public_key
                # 申请端点现在要「持有证明」：拿本机私钥签自己的公钥。
                body.update(
                    sign_pairing_request(key=key, agent_name=name, public_key=public_key)
                )
            payload = await be.request(
                "POST", "/v1/agent-pairing/request", body=body, runtime=False
            )
            if not isinstance(payload, dict) or not payload.get("pairing_code"):
                raise KarmaToolError(ErrorClass.BACKEND, "pairing request returned no pairing_code")
            if key is not None:
                # 服务端不回显公钥；这里本地留痕，karma_connect_status 才能如实报告
                # 「公钥已交」—— 否则状态页会一直说没交，主人会以为白配了。
                payload["public_key"] = body["public_key"]
            path = save_pairing(payload)
            user_code = str(payload.get("user_code") or "")
            public_key = str(payload.get("public_key") or "")
            return ok(
                {
                    "status": "pending_owner",
                    "user_code": user_code,
                    "verification_uri": payload.get("verification_uri"),
                    "expires_at": payload.get("expires_at"),
                    "poll_interval_seconds": payload.get("poll_interval_seconds"),
                    "state_file": str(path),
                    "public_key_attached": key is not None,
                    # 操作台待批准卡片上会显示同一串；agent 把这一串报给主人核对。
                    "agent_fingerprint": agent_public_key_fingerprint(public_key),
                    "next_step": (
                        "请主人打开 "
                        + str(payload.get("verification_uri") or "Karma 操作台")
                        + " 批准这次接入（配对码 "
                        + user_code
                        + " 只是用来对号，不必手输）；"
                        "把上面的 agent_fingerprint 一起报给主人，让他和操作台上显示的那串核对"
                    ),
                    "note": (
                        "pairing_code 只写在本机，聊天里不出现。指纹只能证明"
                        "「操作台这条申请 = 本机这把公钥」，不等于主人已确认授权对象"
                        "（授权要主人自己钱包签名）。"
                    ),
                }
            )

        return await _guard(_run)

    async def karma_connect_status(user_code: str = "") -> dict[str, Any]:
        """这次配对接进到哪一步了。

        **只读本机状态文件，不发任何网络请求** —— 领凭据那一步会消耗服务端的一次性
        凭据，绝不能因为「查一下状态」就把它吃掉（那会让凭据永久丢失）。
        批准结果请用 karma_connect_claim 领取。
        """

        async def _run() -> dict[str, Any]:
            record = load_pairing(user_code)
            if record is None:
                return ok({"pairing": "none", "next_step": "先调用 karma_connect 发起配对"})
            from karma_mcp_server.agent_signing import agent_public_key_fingerprint

            return ok(
                {
                    "pairing": "pending_owner",
                    "user_code": record.get("user_code"),
                    "verification_uri": record.get("verification_uri"),
                    "expires_at": record.get("expires_at"),
                    "public_key_attached": bool(record.get("public_key")),
                    "agent_fingerprint": agent_public_key_fingerprint(
                        str(record.get("public_key") or "")
                    ),
                    "next_step": "主人批准后调用 karma_connect_claim 领取凭据",
                }
            )

        return await _guard(_run)

    async def karma_connect_claim(
        handoff_code: str = "", pairing_code: str = "", user_code: str = ""
    ) -> dict[str, Any]:
        """领取凭据：只写盘、**不回显**（返回指纹与路径）。

        主人一批准，凭据就等你来领。只有主人在操作台主动点过「签发交接码」时，
        才需要把 handoff_code 传进来。
        """

        async def _run() -> dict[str, Any]:
            resolved, record = resolve_pairing_code(pairing_code, user_code)
            if not resolved:
                raise KarmaToolError(
                    ErrorClass.INVALID, "no local pairing found; call karma_connect first"
                )
            body: dict[str, Any] = {"pairing_code": resolved}
            if (handoff_code or "").strip():
                body["handoff_code"] = handoff_code.strip()
            payload = await be.request("POST", "/v1/agent-pairing/claim", body=body, runtime=False)
            status = str(payload.get("status") or "")
            if status in ("pending", "awaiting_handoff"):
                return ok(
                    {
                        "status": status,
                        "handoff_state": payload.get("handoff_state"),
                        "user_code": (record or {}).get("user_code") or user_code,
                        "expires_at": payload.get("expires_at"),
                        "ask_owner": payload.get("message_zh") or "主人还没批准（或还差交接码）。",
                    }
                )
            if status != "approved":
                raise KarmaToolError(ErrorClass.CONFLICT, "pairing has nothing left to deliver")
            creds = dict(payload.get("credentials") or {})
            env = dict(payload.get("env_snippet") or {})
            agent_id = str(payload.get("agent_id") or env.get("KARMA_AGENT_ID") or "")
            api_key = str(creds.get("api_key") or "")
            runtime_key = str(creds.get("runtime_key") or "")
            if not api_key and not runtime_key:
                raise KarmaToolError(
                    ErrorClass.BACKEND, "server said approved but returned no credential"
                )
            from karma_mcp_server.credentials import read_agent_env

            text = credentials_env_text(agent_id, cfg.runtime_base_url, env)
            seed = str(read_agent_env().get("KARMA_AGENT_PRIVATE_KEY") or "").strip()
            if seed:
                text += "KARMA_AGENT_PRIVATE_KEY=" + seed + chr(10)
            path = write_env_file(text)
            delivered: dict[str, Any] = {
                "api_key": {"present": bool(api_key), "fingerprint": fingerprint(api_key)}
            }
            if runtime_key:
                delivered["runtime_key"] = {
                    "present": True,
                    "fingerprint": fingerprint(runtime_key),
                    "runtime_key_id": creds.get("runtime_key_id"),
                }
            return ok(
                {
                    "status": "claimed",
                    "agent_id": agent_id,
                    "owner_identity_id": payload.get("owner_identity_id"),
                    "env_path": str(path),
                    "credentials": delivered,
                    "note": "凭据已写入本机（0600），聊天里不出现明文。",
                }
            )

        return await _guard(_run)

    async def karma_get_connection_status() -> dict[str, Any]:
        """当前凭据的连接状态：是否已配对、钥匙是否已激活、拥有哪些权限。只读。"""

        async def _run() -> dict[str, Any]:
            if not be.has_runtime_key():
                return ok(
                    {
                        "connection": "unconfigured",
                        "key_fingerprint": None,
                        "next_step": "调用 karma_connect 开始配对",
                    }
                )
            data = await be.runtime_get("/runtime/permissions")
            binding = str(data.get("key_binding") or "service")
            if data.get("activation_required") or binding == "agent_pending":
                connection = "pending_activation"
            elif str(data.get("status") or "") != "active":
                connection = "revoked"
            else:
                connection = "active"
            return ok(
                {
                    "connection": connection,
                    "key_id": data.get("key_id"),
                    "key_fingerprint": be.key_fingerprint(),
                    "karma_identity_id": data.get("karma_identity_id"),
                    "permissions": data.get("permissions") or [],
                    "nonce_required": bool(data.get("nonce_required")),
                    "activation_required": bool(data.get("activation_required")),
                    "activation_code_ttl_seconds": data.get("activation_code_ttl_seconds"),
                    "expire_time": data.get("expire_time"),
                    "never_expires": bool(data.get("never_expires")),
                    "next_step": (
                        "请主人在 Karma 操作台输入配对码激活这把钥匙"
                        if connection == "pending_activation"
                        else None
                    ),
                }
            )

        return await _guard(_run)

    # ================= Tier 0: 身份 =================

    async def karma_get_identity_status(identity_id: str = "") -> dict[str, Any]:
        """身份核验状态（KYC / 刷脸 / 绑定钱包）。钱包地址脱敏后返回。只读。"""

        async def _run() -> dict[str, Any]:
            target = (identity_id or "").strip()
            if not target:
                if not be.has_runtime_key():
                    raise KarmaToolError(
                        ErrorClass.UNAUTHORIZED, "no Runtime Key; pass identity_id explicitly"
                    )
                target = await _current_identity()
            if not target:
                raise KarmaToolError(ErrorClass.INVALID, "identity_id is required")
            verification = await be.request(
                "GET", "/v1/identity/" + target + "/verification", runtime=False
            )
            activation = await be.request(
                "GET", "/v1/identity/" + target + "/activation", runtime=False
            )
            out: dict[str, Any] = {
                "identity_id": target,
                "verification": verification,
                "activation": activation,
                "note": "刷脸/KYC 不能被钱包签名替代。",
            }
            wallet = str(
                (verification or {}).get("bound_wallet_address")
                or (verification or {}).get("wallet_address")
                or ""
            ).strip()
            if wallet:
                out["bound_wallet"] = redact_wallet(wallet)
            return ok(out)

        return await _guard(_run)

    async def karma_start_identity_verification(
        identity_id: str, return_url: str = ""
    ) -> dict[str, Any]:
        """开一次身份核验会话，返回给浏览器/手机打开的服务商入口。"""

        async def _run() -> dict[str, Any]:
            target = (identity_id or "").strip()
            if not target:
                raise KarmaToolError(ErrorClass.INVALID, "identity_id is required")
            body: dict[str, Any] = {}
            if (return_url or "").strip():
                body["return_url"] = return_url.strip()
            return ok(
                await be.request(
                    "POST",
                    "/v1/identity/" + target + "/verification/provider/session",
                    body=body,
                    runtime=False,
                )
            )

        return await _guard(_run)

    # ================= Tier 0: 授权状态 =================

    async def karma_get_authorization_status() -> dict[str, Any]:
        """当前授权的额度与权限：单笔上限、日上限、今日已用、剩余。只读。"""

        async def _run() -> dict[str, Any]:
            if not be.has_runtime_key():
                return ok({"connection": "unconfigured", "next_step": "先完成 karma_connect"})
            data = await be.runtime_get("/runtime/policy")
            limits = data.get("limits") or {}
            hard = float(limits.get("per_order_hard_cap_usdc") or 0.0)
            daily_hard = float(limits.get("daily_hard_cap_usdc") or 0.0)
            used = float(limits.get("daily_used_usdc") or 0.0)
            return ok(
                {
                    "key_id": data.get("key_id"),
                    "karma_identity_id": data.get("karma_identity_id"),
                    "agent_name": data.get("agent_name"),
                    "permissions": data.get("permissions") or [],
                    "configured": bool(data.get("configured")),
                    "auto_enabled": bool(data.get("auto_enabled")),
                    "limits": {
                        "per_order_auto_approve_usdc": limits.get("per_order_auto_approve_usdc"),
                        "per_order_hard_cap_usdc": hard,
                        "daily_auto_usdc": limits.get("daily_auto_usdc"),
                        "daily_hard_cap_usdc": daily_hard,
                        "daily_used_usdc": used,
                        "remaining_today_usdc": max(daily_hard - used, 0.0),
                    },
                    "expire_time": data.get("expire_time"),
                    "never_expires": bool(data.get("never_expires")),
                }
            )

        return await _guard(_run)

    async def karma_get_policy() -> dict[str, Any]:
        """当前边界政策：哪些事 agent 可以自己拍板、哪些必须主人确认。只读。"""

        async def _run() -> dict[str, Any]:
            if not be.has_runtime_key():
                return ok({"connection": "unconfigured", "next_step": "先完成 karma_connect"})
            data = await be.runtime_get("/runtime/policy")
            return ok(
                {
                    "key_id": data.get("key_id"),
                    "configured": bool(data.get("configured")),
                    "policy_version": data.get("policy_version"),
                    "boundaries": data.get("boundaries") or {},
                    "rules_zh": data.get("rules_zh") or [],
                    "expire_time": data.get("expire_time"),
                    "never_expires": bool(data.get("never_expires")),
                }
            )

        return await _guard(_run)

    # ================= Tier 1: 授权写入 =================

    async def _bound_wallet(identity_id: str) -> str:
        """主人身份上已绑定的钱包地址；读不到就回空串 —— 绝不猜、绝不编。

        只对主人本人的身份有效：服务端只在调用方就是这个身份（或其自己的 agent）
        时才回这个字段，陌生人拿到的是没有钱包的公开视图。
        """
        target = (identity_id or "").strip()
        if not target:
            return ""
        try:
            view = await be.request(
                "GET", "/v1/identity/" + target + "/verification", runtime=False
            )
        except KarmaToolError:
            return ""
        if not isinstance(view, dict):
            return ""
        for key in ("bound_wallet_address", "wallet_address"):
            value = str(view.get(key) or "").strip()
            if value:
                return value
        return ""

    def _authorization_preview(
        *,
        karma_identity_id: str,
        wallet_address: str,
        permissions: list[str],
        single_limit: float,
        daily_limit: float,
        expire_time: str,
        agent_name: str,
        agent_binding: str,
        agent_public_key_fingerprint: str = "",
    ) -> dict[str, Any]:
        if not permissions:
            raise KarmaToolError(ErrorClass.INVALID, "permissions must not be empty")
        if single_limit <= 0 or daily_limit <= 0:
            raise KarmaToolError(ErrorClass.INVALID, "single_limit and daily_limit must be > 0")
        if daily_limit < single_limit:
            raise KarmaToolError(ErrorClass.INVALID, "daily_limit must be >= single_limit")
        if not karma_identity_id or not wallet_address or not agent_name:
            raise KarmaToolError(
                ErrorClass.INVALID,
                "karma_identity_id, agent_name and a bound wallet_address are required"
                " (wallet_address 可留空 —— MCP 会用主人身份已绑定的钱包自动补上)",
            )
        if not agent_binding:
            # 后端在 runtime_require_agent_binding 开启时拒绝不记名钥匙（谁捡到谁能花）。
            # 这里提前拦：不指名就先去跟主人要 agent id，别等后端用英文 400 打回来。
            raise KarmaToolError(
                ErrorClass.INVALID,
                "agent_binding is required: 每把 Runtime Key 都必须指名它授权的 agent"
                "（不记名钥匙会被后端拒绝）",
            )
        message = build_create_key_message(
            karma_identity_id=karma_identity_id,
            wallet_address=wallet_address,
            permissions=permissions,
            single_limit=single_limit,
            daily_limit=daily_limit,
            expire_time=(expire_time or "").strip() or None,
            agent_name=agent_name,
            agent_binding=agent_binding or None,
            agent_public_key_fingerprint=agent_public_key_fingerprint or None,
        )
        return {
            "karma_identity_id": karma_identity_id,
            "wallet_address": wallet_address,
            "permissions": sorted(permissions),
            "single_limit_usdc": single_limit,
            "daily_limit_usdc": daily_limit,
            "expire_time": (expire_time or "").strip() or None,
            "agent_name": agent_name,
            "agent_binding": agent_binding,
            "agent_public_key_fingerprint": agent_public_key_fingerprint,
            "sign_message": message,
        }

    async def karma_request_authorization(
        permissions: list[str],
        single_limit: float,
        daily_limit: float,
        agent_name: str,
        karma_identity_id: str,
        wallet_address: str,
        agent_binding: str = "",
        expire_time: str = "",
    ) -> dict[str, Any]:
        """**第一步（预览）**：把权限意图变成待签文案，交给主人的钱包。

        这一步**不写任何后端状态、不产生任何权限**。主人用自己的钱包对
        sign_message 做 personal_sign，再把签名交给 karma_submit_authorization。
        """

        async def _run() -> dict[str, Any]:
            identity = (karma_identity_id or "").strip()
            wallet = (wallet_address or "").strip()
            if not wallet:
                # 主人不用把钱包地址贴进聊天：直接用他自己身份上已绑定的地址。
                # 地址本身是公开的，服务端还会再校验它确实属于这个身份。
                wallet = await _bound_wallet(identity)
            preview = _authorization_preview(
                karma_identity_id=identity,
                wallet_address=wallet,
                permissions=list(permissions or []),
                single_limit=float(single_limit),
                daily_limit=float(daily_limit),
                expire_time=expire_time,
                agent_name=(agent_name or "").strip(),
                agent_binding=(agent_binding or "").strip(),
                agent_public_key_fingerprint=be.agent_key_fingerprint(),
            )
            return ok(
                {
                    "step": "awaiting_wallet_signature",
                    "preview": preview,
                    "sign_message": preview["sign_message"],
                    "next_step": (
                        "请主人用绑定钱包对 sign_message 做 personal_sign，"
                        "然后把签名交给 karma_submit_authorization"
                    ),
                }
            )

        return await _guard(_run)

    async def _create_runtime_key(body: dict[str, Any]) -> dict[str, Any]:
        data = await be.request("POST", "/runtime/create-key", body=body, runtime=False)
        return ok(
            {
                "key_id": data.get("key_id") or data.get("runtime_key_id"),
                "key_fingerprint": fingerprint(str(data.get("runtime_key") or "")),
                "delivered": bool(data.get("runtime_key")),
                "permissions": data.get("permissions"),
                "single_limit": data.get("single_limit"),
                "daily_limit": data.get("daily_limit"),
                "expire_time": data.get("expire_time"),
                "env_path": data.get("env_path"),
                "note": "Runtime Key 明文只在服务端返回一次；这里只报指纹。",
            }
        )

    async def karma_submit_authorization(
        wallet_signature: str,
        agent_name: str,
        wallet_address: str,
        permissions: list[str],
        single_limit: float,
        daily_limit: float,
        karma_identity_id: str = "",
        agent_binding: str = "",
        expire_time: str = "",
    ) -> dict[str, Any]:
        """**第二步（落库）**：带上主人的钱包签名铸造 Runtime Key。

        签名必须由主人钱包产生；MCP 与模型**没有**签发资金权限的能力。
        """

        async def _run() -> dict[str, Any]:
            if not (wallet_signature or "").strip():
                raise KarmaToolError(ErrorClass.INVALID, "wallet_signature is required")
            identity = (karma_identity_id or "").strip()
            if not identity and be.has_runtime_key():
                identity = await _current_identity()
            wallet = (wallet_address or "").strip()
            if not wallet:
                wallet = await _bound_wallet(identity)
            preview = _authorization_preview(
                karma_identity_id=identity,
                wallet_address=wallet,
                permissions=list(permissions or []),
                single_limit=float(single_limit),
                daily_limit=float(daily_limit),
                expire_time=expire_time,
                agent_name=(agent_name or "").strip(),
                agent_binding=(agent_binding or "").strip(),
                agent_public_key_fingerprint=be.agent_key_fingerprint(),
            )
            body: dict[str, Any] = {
                "wallet_address": preview["wallet_address"],
                "karma_identity_id": preview["karma_identity_id"],
                "wallet_signature": wallet_signature.strip(),
                "permissions": preview["permissions"],
                "single_limit": preview["single_limit_usdc"],
                "daily_limit": preview["daily_limit_usdc"],
                "agent_name": preview["agent_name"],
            }
            if preview["expire_time"]:
                body["expire_time"] = preview["expire_time"]
            if preview["agent_binding"]:
                body["agent_binding"] = preview["agent_binding"]
                body["agent_id"] = preview["agent_binding"]
            if preview["agent_public_key_fingerprint"]:
                # 签名里的指纹行必须和这里提交的一模一样，否则服务端验签就 403。
                body["agent_public_key_fingerprint"] = preview["agent_public_key_fingerprint"]
            return await _create_runtime_key(body)

        return await _guard(_run)

    async def karma_revoke_authorization(
        key_id: str = "",
        wallet_signature: str = "",
        wallet_address: str = "",
        karma_identity_id: str = "",
        twofa_code: str = "",
    ) -> dict[str, Any]:
        """停用一把 Runtime Key（= 操作台「一键停用」）。

        不传 wallet_signature 时返回待签文案（预览）；带上签名才真正撤销。
        撤销后这把钥匙的权限**立即**不可再用。
        """

        async def _run() -> dict[str, Any]:
            identity = (karma_identity_id or "").strip()
            target = (key_id or "").strip()
            if (not target or not identity) and be.has_runtime_key():
                perms = await be.runtime_get("/runtime/permissions")
                target = target or str(perms.get("key_id") or "")
                identity = identity or str(perms.get("karma_identity_id") or "")
            if not target or not identity:
                raise KarmaToolError(
                    ErrorClass.INVALID, "key_id and karma_identity_id are required"
                )
            if not (wallet_signature or "").strip():
                message = build_revoke_key_message(
                    key_id=target,
                    karma_identity_id=identity,
                    wallet_address=(wallet_address or "").strip(),
                )
                return ok(
                    {
                        "step": "awaiting_wallet_signature",
                        "key_id": target,
                        "karma_identity_id": identity,
                        "sign_message": message,
                        "next_step": "请主人用绑定钱包签名后再调用一次（带 wallet_signature）",
                    }
                )
            body: dict[str, Any] = {
                "key_id": target,
                "karma_identity_id": identity,
                "wallet_address": (wallet_address or "").strip(),
                "wallet_signature": wallet_signature.strip(),
            }
            if (twofa_code or "").strip():
                body["twofa_code"] = twofa_code.strip()
            return ok(await be.request("POST", "/runtime/revoke-key", body=body, runtime=False))

        return await _guard(_run)

    async def karma_update_authorization(
        revoke_key_id: str = "",
        new_wallet_signature: str = "",
        revoke_wallet_signature: str = "",
        permissions: list[str] | None = None,
        single_limit: float = 0.0,
        daily_limit: float = 0.0,
        agent_name: str = "",
        wallet_address: str = "",
        karma_identity_id: str = "",
        agent_binding: str = "",
        expire_time: str = "",
        twofa_code: str = "",
    ) -> dict[str, Any]:
        """改额度 / 边界 = **铸新 key（重新钱包签名）+ 撤销旧 key**。不存在原地修改。

        两张签名都没有时返回两段待签文案；两张都到位才执行。
        顺序：先铸新、再撤旧；撤销失败会显式报错（此时新旧两把同时存在，需重试撤销）。
        """

        async def _run() -> dict[str, Any]:
            identity = (karma_identity_id or "").strip()
            old_key = (revoke_key_id or "").strip()
            if be.has_runtime_key():
                perms = await be.runtime_get("/runtime/permissions")
                identity = identity or str(perms.get("karma_identity_id") or "")
                old_key = old_key or str(perms.get("key_id") or "")
            if not identity:
                raise KarmaToolError(ErrorClass.INVALID, "karma_identity_id is required")
            if not new_wallet_signature or not revoke_wallet_signature:
                preview = _authorization_preview(
                    karma_identity_id=identity,
                    wallet_address=(wallet_address or "").strip(),
                    permissions=list(permissions or []),
                    single_limit=float(single_limit),
                    daily_limit=float(daily_limit),
                    expire_time=expire_time,
                    agent_name=(agent_name or "").strip(),
                    agent_binding=(agent_binding or "").strip(),
                )
                return ok(
                    {
                        "step": "awaiting_wallet_signatures",
                        "preview": preview,
                        "create_sign_message": preview["sign_message"],
                        "revoke_sign_message": build_revoke_key_message(
                            key_id=old_key,
                            karma_identity_id=identity,
                            wallet_address=preview["wallet_address"],
                        ),
                        "next_step": "两张签名都到位后再调用一次本工具",
                    }
                )
            create_body: dict[str, Any] = {
                "wallet_address": (wallet_address or "").strip(),
                "karma_identity_id": identity,
                "wallet_signature": new_wallet_signature.strip(),
                "permissions": sorted(permissions or []),
                "single_limit": float(single_limit),
                "daily_limit": float(daily_limit),
                "agent_name": (agent_name or "").strip(),
            }
            if (expire_time or "").strip():
                create_body["expire_time"] = expire_time.strip()
            if (agent_binding or "").strip():
                create_body["agent_binding"] = agent_binding.strip()
                create_body["agent_id"] = agent_binding.strip()
            created = await _create_runtime_key(create_body)
            revoke_body: dict[str, Any] = {
                "key_id": old_key,
                "karma_identity_id": identity,
                "wallet_address": (wallet_address or "").strip(),
                "wallet_signature": revoke_wallet_signature.strip(),
            }
            if (twofa_code or "").strip():
                revoke_body["twofa_code"] = twofa_code.strip()
            try:
                revoked = await be.request(
                    "POST", "/runtime/revoke-key", body=revoke_body, runtime=False
                )
            except KarmaToolError as exc:
                return {
                    "ok": False,
                    "error": exc.info.as_dict(),
                    "new_authorization": created,
                    "warning": (
                        "新 key 已铸成，但旧 key 撤销失败 —— 两把钥匙现在同时有效，"
                        "请立刻重试 karma_revoke_authorization。"
                    ),
                }
            return ok({"status": "updated", "new_authorization": created, "revoked": revoked})

        return await _guard(_run)

    # ================= Tier 0: 交易 / 结算 / 信誉 =================

    async def karma_get_transaction_status(task_id: str = "", order_id: str = "") -> dict[str, Any]:
        """查交易状态（task_id 或 order_id 至少给一个）。只读。"""

        async def _run() -> dict[str, Any]:
            task = (task_id or "").strip()
            order = (order_id or "").strip()
            if not task and not order:
                raise KarmaToolError(ErrorClass.INVALID, "task_id or order_id is required")
            out: dict[str, Any] = {"task_id": task or None, "order_id": order or None}
            if task and be.has_runtime_key():
                out["task"] = await be.runtime_get("/runtime/task-status/" + task)
            if order:
                out["order"] = await be.request("GET", "/v1/trade/orders/" + order, runtime=False)
            return ok(out)

        return await _guard(_run)

    async def karma_get_settlement_status(task_id: str) -> dict[str, Any]:
        """查结算状态与状态机迁移历史。只读。"""

        async def _run() -> dict[str, Any]:
            task = (task_id or "").strip()
            if not task:
                raise KarmaToolError(ErrorClass.INVALID, "task_id is required")
            base = "/v1/settlement/" + task
            return ok(
                {
                    "task_id": task,
                    "settlement": await be.request("GET", base, runtime=False),
                    "transitions": await be.request("GET", base + "/transitions", runtime=False),
                }
            )

        return await _guard(_run)

    async def karma_get_reputation(agent_id: str) -> dict[str, Any]:
        """查公开信誉画像（不含任何内部评分算法细节）。只读。"""

        async def _run() -> dict[str, Any]:
            target = (agent_id or "").strip()
            if not target:
                raise KarmaToolError(ErrorClass.INVALID, "agent_id is required")
            return ok(
                {
                    "agent_id": target,
                    "reputation": await be.request(
                        "GET", "/v1/reputation/" + target, runtime=False
                    ),
                }
            )

        return await _guard(_run)

    async def karma_get_risk_result(identity_id: str = "") -> dict[str, Any]:
        """查**公开投影**的风险结果（风险等级 / 公开标记）。

        内部风控算法、特征、权重一律不返回 —— 那部分在私有域，不对外暴露。
        """

        async def _run() -> dict[str, Any]:
            target = (identity_id or "").strip()
            if not target and be.has_runtime_key():
                target = await _current_identity()
            if not target:
                raise KarmaToolError(ErrorClass.INVALID, "identity_id is required")
            data = await be.request(
                "GET", "/v1/responsibility/identity/" + target + "/score", runtime=False
            )
            allowed = {
                "identity_id",
                "level",
                "band",
                "score_band",
                "public_label",
                "updated_at",
            }
            public = {k: v for k, v in (data or {}).items() if k in allowed}
            return ok(
                {
                    "identity_id": target,
                    "public_risk": public,
                    "note": "仅公开投影；内部风控细节不对外暴露。",
                }
            )

        return await _guard(_run)

    # ================= Tier 2: 交易 / 交付 =================

    async def karma_create_transaction(
        requirement_text: str,
        amount: float,
        client_nonce: str,
        seller_identity_id: str = "",
        negotiate_a2a: bool = True,
        auto_complete: bool = False,
        confirmation_session_id: str = "",
        important_fields_capture_id: str = "",
    ) -> dict[str, Any]:
        """按主人划的边界下单（动钱，Tier 2）。

        边界在服务端算：单笔 > key 上限直接 403；超「自动额度」不建单不扣钱，
        返回 awaiting_owner_confirmation 等主人确认。**「调用成功」不等于「成交」**。
        """

        async def _run() -> dict[str, Any]:
            if len((client_nonce or "").strip()) < 8:
                raise KarmaToolError(ErrorClass.INVALID, "client_nonce is required (min 8 chars)")
            body: dict[str, Any] = {
                "requirement_text": requirement_text,
                "amount": float(amount),
                "client_nonce": client_nonce.strip(),
                "negotiate_a2a": bool(negotiate_a2a),
                "auto_complete": bool(auto_complete),
            }
            for key, value in (
                ("seller_identity_id", seller_identity_id),
                ("confirmation_session_id", confirmation_session_id),
                ("important_fields_capture_id", important_fields_capture_id),
            ):
                if (value or "").strip():
                    body[key] = value.strip()
            return ok(await be.runtime_post("/runtime/place-order", body))

        return await _guard(_run)

    async def karma_accept_payment_code(voucher_id: str) -> dict[str, Any]:
        """卖方接受付款凭证（Tier 2）。"""

        async def _run() -> dict[str, Any]:
            vid = (voucher_id or "").strip()
            if not vid:
                raise KarmaToolError(ErrorClass.INVALID, "voucher_id is required")
            return ok(
                await be.request(
                    "POST", "/v1/payment-codes/" + vid + "/accept", body={}, runtime=False
                )
            )

        return await _guard(_run)

    async def karma_decide_confirmation(
        session_id: str, confirm: bool, actor_agent_id: str, note: str = ""
    ) -> dict[str, Any]:
        """人工确认会话的裁决（Tier 2）。"""

        async def _run() -> dict[str, Any]:
            sid = (session_id or "").strip()
            if not sid or not (actor_agent_id or "").strip():
                raise KarmaToolError(
                    ErrorClass.INVALID, "session_id and actor_agent_id are required"
                )
            body: dict[str, Any] = {
                "confirm": bool(confirm),
                "actor_agent_id": actor_agent_id.strip(),
            }
            if (note or "").strip():
                body["note"] = note.strip()
            return ok(
                await be.request(
                    "POST",
                    "/v1/confirmations/sessions/" + sid + "/decide",
                    body=body,
                    runtime=False,
                )
            )

        return await _guard(_run)

    async def karma_submit_evidence(bundle: dict[str, Any]) -> dict[str, Any]:
        """提交交付证据包（Tier 2）。payload 必须符合后端证据 schema 且含 task_id。"""

        async def _run() -> dict[str, Any]:
            return ok(await be.runtime_post("/runtime/submit-bundle", _artifact(bundle)))

        return await _guard(_run)

    async def karma_verify_evidence(evidence_id: str) -> dict[str, Any]:
        """请求后端验证一份证据（Tier 2）。"""

        async def _run() -> dict[str, Any]:
            eid = (evidence_id or "").strip()
            if not eid:
                raise KarmaToolError(ErrorClass.INVALID, "evidence_id is required")
            return ok(
                await be.request("POST", "/v1/evidence/" + eid + "/verify", body={}, runtime=False)
            )

        return await _guard(_run)

    async def karma_submit_receipt(receipt: dict[str, Any]) -> dict[str, Any]:
        """提交执行回执（Tier 2）。payload 必须符合后端回执 schema 且含 task_id。"""

        async def _run() -> dict[str, Any]:
            return ok(await be.runtime_post("/runtime/submit-receipt", _artifact(receipt)))

        return await _guard(_run)

    async def karma_submit_progress(progress: dict[str, Any]) -> dict[str, Any]:
        """提交进度回执（Tier 2）。payload 必须含 task_id。"""

        async def _run() -> dict[str, Any]:
            return ok(await be.runtime_post("/runtime/update-progress", _artifact(progress)))

        return await _guard(_run)

    async def karma_request_settlement(
        task_id: str, kind: str, client_nonce: str, settled_value_percent: float = 0.0
    ) -> dict[str, Any]:
        """请求结算（Tier 2）。kind ∈ submit_delivery / buyer_accept / partial。"""

        async def _run() -> dict[str, Any]:
            task = (task_id or "").strip()
            if not task:
                raise KarmaToolError(ErrorClass.INVALID, "task_id is required")
            if kind not in ("submit_delivery", "buyer_accept", "partial"):
                raise KarmaToolError(
                    ErrorClass.INVALID,
                    "kind must be one of submit_delivery / buyer_accept / partial",
                )
            if len((client_nonce or "").strip()) < 8:
                raise KarmaToolError(ErrorClass.INVALID, "client_nonce is required (min 8 chars)")
            body: dict[str, Any] = {
                "task_id": task,
                "kind": kind,
                "client_nonce": client_nonce.strip(),
            }
            if kind == "partial" and settled_value_percent:
                body["settled_value_percent"] = float(settled_value_percent)
            return ok(await be.runtime_post("/runtime/request-settlement", body))

        return await _guard(_run)

    # ================= Tier 3: 资金 / 争议 =================

    async def karma_verify_voucher(
        voucher_id: str, client_nonce: str, expected_amount: float = 0.0
    ) -> dict[str, Any]:
        """校验付款凭证（只读校验，不承兑；Tier 3）。"""

        async def _run() -> dict[str, Any]:
            if not (voucher_id or "").strip():
                raise KarmaToolError(ErrorClass.INVALID, "voucher_id is required")
            if len((client_nonce or "").strip()) < 8:
                raise KarmaToolError(ErrorClass.INVALID, "client_nonce is required (min 8 chars)")
            body: dict[str, Any] = {
                "voucher_id": voucher_id.strip(),
                "client_nonce": client_nonce.strip(),
            }
            if expected_amount:
                body["expected_amount"] = float(expected_amount)
            return ok(await be.runtime_post("/runtime/check-voucher", body))

        return await _guard(_run)

    async def karma_get_voucher(voucher_id: str) -> dict[str, Any]:
        """查付款凭证状态与事件。只读。"""

        async def _run() -> dict[str, Any]:
            vid = (voucher_id or "").strip()
            if not vid:
                raise KarmaToolError(ErrorClass.INVALID, "voucher_id is required")
            base = "/v1/vouchers/" + vid
            return ok(
                {
                    "voucher_id": vid,
                    "voucher": await be.request("GET", base, runtime=False),
                    "events": await be.request("GET", base + "/events", runtime=False),
                }
            )

        return await _guard(_run)

    async def karma_open_dispute(task_id: str, reason: str = "") -> dict[str, Any]:
        """对一笔交易发起争议（Tier 3，动钱）。"""

        async def _run() -> dict[str, Any]:
            task = (task_id or "").strip()
            if not task:
                raise KarmaToolError(ErrorClass.INVALID, "task_id is required")
            body: dict[str, Any] = {}
            if (reason or "").strip():
                body["reason"] = reason.strip()
            return ok(
                await be.request(
                    "POST", "/v1/settlement/" + task + "/dispute", body=body, runtime=False
                )
            )

        return await _guard(_run)

    async def karma_request_refund(task_id: str, reason: str = "") -> dict[str, Any]:
        """申请退款（Tier 3，动钱）。走后端争议/退款入口，由后端与链上状态机裁定。"""

        async def _run() -> dict[str, Any]:
            task = (task_id or "").strip()
            if not task:
                raise KarmaToolError(ErrorClass.INVALID, "task_id is required")
            body: dict[str, Any] = {}
            if (reason or "").strip():
                body["reason"] = reason.strip()
            return ok(
                await be.request(
                    "POST", "/v1/settlement/" + task + "/dispute", body=body, runtime=False
                )
            )

        return await _guard(_run)

    # ================= 注册（按 Tier 白名单，fail-closed） =================

    tier_groups: dict[int, list[Any]] = {
        0: [
            karma_connect,
            karma_connect_status,
            karma_connect_claim,
            karma_get_connection_status,
            karma_get_identity_status,
            karma_start_identity_verification,
            karma_get_authorization_status,
            karma_get_policy,
            karma_get_transaction_status,
            karma_get_settlement_status,
            karma_get_reputation,
            karma_get_risk_result,
            karma_get_voucher,
        ],
        1: [
            karma_request_authorization,
            karma_submit_authorization,
            karma_update_authorization,
            karma_revoke_authorization,
        ],
        2: [
            karma_create_transaction,
            karma_accept_payment_code,
            karma_decide_confirmation,
            karma_submit_evidence,
            karma_verify_evidence,
            karma_submit_receipt,
            karma_submit_progress,
            karma_request_settlement,
        ],
        3: [
            karma_verify_voucher,
            karma_open_dispute,
            karma_request_refund,
        ],
    }
    for tier, group in tier_groups.items():
        if tier not in tiers:
            continue
        for fn in group:
            mcp.add_tool(fn)

    return mcp
