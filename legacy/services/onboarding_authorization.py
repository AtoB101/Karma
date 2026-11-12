"""Karma — interactive onboarding authorization (step-by-step owner consent).

当主人对 agent 说「接入 Karma」时，agent 驱动这个状态机：每一步返回一个**可渲染
的提示对象**，交互页面按 ``prompt_type`` 渲染对应控件，收集主人的回应后回传，
直到授权完成。

边界说明：这里只负责「提示 + 收集同意 + 交接」，不重做 SIWE / create-key /
pairing 的密码学校验 —— 那些仍在 auth / runtime_gateway / agent_pairing 里。
钱包签名步骤收集的是主人对该步骤的**同意签名**；真正动钱的端点仍会各自再做
一次安全校验（不把安全关键路径外包给本模块）。
"""
from __future__ import annotations

import json
import secrets
import threading
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .agent_onboarding_template import authorization_flow

_STORE_PATH = (
    Path(__file__).resolve().parents[1] / ".karma_data" / "onboarding_authorizations.json"
)
_LOCK = threading.Lock()
_FLOWS: dict[str, OnboardingFlow] = {}
_LOADED = False

# step_id -> prompt_type（与 authorization-flow 的七步对齐）
_STEP_PROMPT_TYPES: dict[str, str] = {
    "owner_identity": "wallet_sign",
    "role_declaration": "yes_no",
    "funding_bounds": "ack",
    "runtime_key_mint": "wallet_sign",
    "agent_pairing": "matching_code",
    "binding_attestation": "info",
    "runtime_spend": "info",
}

# prompt_type -> 交互页面该画的控件说明（供前端直接渲染）
_PROMPT_TYPE_CONTROLS: dict[str, dict[str, Any]] = {
    "yes_no": {"control_zh": "确认 / 拒绝 按钮", "actions": ["confirm", "reject"]},
    "ack": {"control_zh": "责任确认勾选 + 确认 / 拒绝", "actions": ["confirm", "reject"]},
    "wallet_sign": {
        "control_zh": "钱包签名按钮（personal_sign）",
        "actions": ["sign", "cancel"],
    },
    "matching_code": {
        "control_zh": "展示 8 位对照码 + 输入框回填",
        "actions": ["confirm", "reject"],
    },
    "info": {"control_zh": "信息卡（点继续）", "actions": ["continue"]},
}

FLOW_TTL_SECONDS = 30 * 60


@dataclass
class OnboardingFlow:
    flow_id: str
    identity_id: str
    profile_id: str
    step_index: int = 0
    status: str = "in_progress"  # in_progress | aborted | complete
    collected: dict[str, Any] = field(default_factory=dict)
    started_by: str = ""
    created_at: str = ""
    updated_at: str = ""

    def public(self) -> dict[str, Any]:
        return {
            "flow_id": self.flow_id,
            "identity_id": self.identity_id,
            "profile_id": self.profile_id,
            "status": self.status,
            "step_index": self.step_index,
            "collected": self.collected,
            "started_by": self.started_by,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }


def _iso_now() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _ensure_loaded() -> None:
    global _LOADED
    if _LOADED:
        return
    with _LOCK:
        if _LOADED:
            return
        if _STORE_PATH.is_file():
            try:
                raw = json.loads(_STORE_PATH.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    for fid, body in raw.items():
                        if not isinstance(body, dict):
                            continue
                        _FLOWS[str(fid)] = OnboardingFlow(
                            flow_id=str(body.get("flow_id") or fid),
                            identity_id=str(body.get("identity_id") or ""),
                            profile_id=str(body.get("profile_id") or ""),
                            step_index=int(body.get("step_index") or 0),
                            status=str(body.get("status") or "in_progress"),
                            collected=dict(body.get("collected") or {}),
                            started_by=str(body.get("started_by") or ""),
                            created_at=str(body.get("created_at") or ""),
                            updated_at=str(body.get("updated_at") or ""),
                        )
            except Exception:  # noqa: BLE001, S110
                pass
        _LOADED = True


def _persist_unlocked() -> None:
    _STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    payload = {fid: asdict(flow) for fid, flow in _FLOWS.items()}
    _STORE_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def reset_onboarding_flows() -> None:
    global _LOADED
    with _LOCK:
        _FLOWS.clear()
        _LOADED = True
        if _STORE_PATH.is_file():
            _STORE_PATH.unlink(missing_ok=True)


def _steps() -> list[dict[str, Any]]:
    return list(authorization_flow().get("steps") or [])


def _public_base_url() -> str:
    try:
        from config.settings import settings

        return (getattr(settings, "public_runtime_base_url", "") or "").strip()
    except Exception:  # noqa: BLE001
        return ""


def _fmt(template: str, ctx: dict[str, Any]) -> str:
    try:
        return str(template).format(**ctx)
    except Exception:  # noqa: BLE001
        return template


def _sign_message(flow: OnboardingFlow, step: dict[str, Any]) -> str:
    nonce = secrets.token_hex(8)
    flow.collected[f"{step['step_id']}_nonce"] = nonce
    return (
        "Karma 接入授权 · "
        f"第 {step['order']} 步「{step['title_zh']}」\n"
        f"身份：{flow.identity_id}\n"
        f"角色：{flow.profile_id}\n"
        f"nonce：{nonce}"
    )


def _make_matching_code() -> str:
    alphabet = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return f"{''.join(secrets.choice(alphabet) for _ in range(4))}-{''.join(secrets.choice(alphabet) for _ in range(4))}"


def _normalize_code(value: str) -> str:
    return "".join(ch for ch in (value or "").upper() if ch.isalnum())


def _prompt_for(flow: OnboardingFlow, step: dict[str, Any]) -> dict[str, Any]:
    step_id = step["step_id"]
    prompt_type = _STEP_PROMPT_TYPES.get(step_id, "info")
    base_url = _public_base_url()
    ctx = {"identity_id": flow.identity_id, "profile": flow.profile_id}

    prompt: dict[str, Any] = {
        "flow_id": flow.flow_id,
        "step_id": step_id,
        "step_index": step["order"],
        "total_steps": len(_steps()),
        "prompt_type": prompt_type,
        "title_zh": _fmt(step.get("title_zh") or step_id, ctx),
        "title_en": _fmt(step.get("title_en") or step_id, ctx),
        "body_zh": _fmt(step.get("summary_zh") or "", ctx),
        "protects_zh": step.get("protects_zh") or "",
        "control": _PROMPT_TYPE_CONTROLS.get(prompt_type, {}),
        "actions": list(_PROMPT_TYPE_CONTROLS.get(prompt_type, {}).get("actions") or []),
        "deep_link": None,
        "payload": {},
    }

    if prompt_type == "wallet_sign":
        prompt["payload"] = {
            "sign_message": _sign_message(flow, step),
            "note_zh": "该签名是接入授权回执；真正的 SIWE / 铸钥匙端点会各自再校验一次。",
        }
        if base_url:
            prompt["deep_link"] = f"{base_url}/console/?onboard=1"

    if prompt_type == "matching_code":
        if f"{step_id}_code" not in flow.collected:
            flow.collected[f"{step_id}_code"] = _make_matching_code()
        prompt["payload"] = {
            "match_code": flow.collected[f"{step_id}_code"],
            "note_zh": "请核对 agent 展示的对照码，并在下方输入框里原样输入确认。",
        }

    if step_id == "funding_bounds":
        prompt["payload"] = {
            "defaults": {
                "single_limit": 100.0,
                "daily_limit": 500.0,
                "high_risk_mode": "above_single",
                "permissions": [
                    "request_voucher",
                    "submit_receipt",
                    "update_progress",
                    "request_settlement",
                    "sync_task_status",
                    "discover_agents",
                    "place_order",
                ],
            },
            "note_zh": "这些默认边界可在「身份 · 认证」建卡时改；确认后按此写入自动化策略。",
        }

    return prompt


def start_onboarding(*, identity_id: str, profile_id: str, started_by: str = "") -> dict[str, Any]:
    _ensure_loaded()
    if not (identity_id or "").strip():
        raise ValueError("identity_id is required")
    if profile_id not in {"user", "merchant", "enterprise"}:
        raise ValueError("profile_id must be one of user|merchant|enterprise")
    flow = OnboardingFlow(
        flow_id="obf_" + secrets.token_hex(12),
        identity_id=identity_id.strip(),
        profile_id=profile_id,
        started_by=(started_by or "").strip(),
        created_at=_iso_now(),
        updated_at=_iso_now(),
    )
    with _LOCK:
        _FLOWS[flow.flow_id] = flow
        _persist_unlocked()
    return current_prompt(flow.flow_id)


def get_onboarding_flow(flow_id: str) -> OnboardingFlow | None:
    _ensure_loaded()
    return _FLOWS.get(flow_id)


def current_prompt(flow_id: str) -> dict[str, Any]:
    flow = get_onboarding_flow(flow_id)
    if not flow:
        raise KeyError(f"unknown onboarding flow: {flow_id}")
    steps = _steps()
    if flow.status == "complete":
        return {"status": "complete", "flow": flow.public(), "prompt": None}
    if flow.status == "aborted":
        return {"status": "aborted", "flow": flow.public(), "prompt": None}
    if flow.step_index >= len(steps):
        flow.status = "complete"
        flow.updated_at = _iso_now()
        with _LOCK:
            _persist_unlocked()
        return {
            "status": "complete",
            "flow": flow.public(),
            "prompt": None,
            "next_steps": _handoff_next_steps(flow),
        }
    step = steps[flow.step_index]
    return {
        "status": "in_progress",
        "flow": flow.public(),
        "prompt": _prompt_for(flow, step),
        "next_steps": _step_next_steps(flow, step),
    }


def _handoff_next_steps(flow: OnboardingFlow) -> list[str]:
    return [
        "接入授权已完成，主人已逐步同意",
        "POST /v1/identities/{id}/automation-policy 用 collected 里的边界落库",
        "POST /runtime/create-key 用主人钱包签名铸运行时钥匙",
        "POST /v1/agent-pairing/request 用 collected 里的 agent 公钥配对",
        "完成后 GET /runtime/policy 让 agent 读自己的边界",
    ]


def _step_next_steps(flow: OnboardingFlow, step: dict[str, Any]) -> list[str]:
    step_id = step["step_id"]
    return {
        "owner_identity": ["在钱包里对 sign_message 签名后，把地址与签名回传"],
        "role_declaration": ["确认或拒绝这一步的接入身份"],
        "funding_bounds": ["核对默认边界并勾选责任确认，然后确认"],
        "runtime_key_mint": ["在钱包里对 sign_message 签名后回传地址与签名"],
        "agent_pairing": ["把 payload.match_code 输入到输入框里确认"],
        "binding_attestation": ["点继续"],
        "runtime_spend": ["点继续，完成接入"],
    }.get(step_id, ["继续"])


def respond_onboarding(*, flow_id: str, action: str, value: dict[str, Any] | None = None) -> dict[str, Any]:
    flow = get_onboarding_flow(flow_id)
    if not flow:
        raise KeyError(f"unknown onboarding flow: {flow_id}")
    if flow.status != "in_progress":
        raise ValueError(f"flow is {flow.status}")
    steps = _steps()
    if flow.step_index >= len(steps):
        return current_prompt(flow_id)
    step = steps[flow.step_index]
    prompt_type = _STEP_PROMPT_TYPES.get(step["step_id"], "info")
    action = (action or "").strip().lower()
    value = dict(value or {})

    if action in {"reject", "cancel"}:
        flow.status = "aborted"
        flow.updated_at = _iso_now()
        with _LOCK:
            _persist_unlocked()
        return {"status": "aborted", "flow": flow.public(), "prompt": None}

    if prompt_type == "wallet_sign":
        if action != "sign":
            raise ValueError("wallet_sign step requires action=sign")
        address = str(value.get("address") or "").strip()
        signature = str(value.get("signature") or "").strip()
        if not address.startswith("0x") or len(address) != 42:
            raise ValueError("address must be a 0x-prefixed 40-hex address")
        if not signature.startswith("0x") or len(signature) < 130:
            raise ValueError("signature must be a 0x-prefixed hex signature")
        flow.collected[f"{step['step_id']}_address"] = address
        flow.collected[f"{step['step_id']}_signature"] = signature
    elif prompt_type == "matching_code":
        if action != "confirm":
            raise ValueError("matching_code step requires action=confirm")
        expected = _normalize_code(str(flow.collected.get(f"{step['step_id']}_code") or ""))
        got = _normalize_code(str(value.get("code") or ""))
        if not got or got != expected:
            raise ValueError("code does not match")
    elif prompt_type in {"yes_no", "ack"}:
        if action != "confirm":
            raise ValueError(f"{prompt_type} step requires action=confirm")
        if step["step_id"] == "role_declaration":
            flow.profile_id = str(value.get("profile_id") or flow.profile_id).strip()
    elif prompt_type == "info":
        if action != "continue":
            raise ValueError("info step requires action=continue")

    flow.step_index += 1
    flow.updated_at = _iso_now()
    with _LOCK:
        _persist_unlocked()
    return current_prompt(flow_id)


def abort_onboarding(flow_id: str) -> dict[str, Any]:
    flow = get_onboarding_flow(flow_id)
    if not flow:
        raise KeyError(f"unknown onboarding flow: {flow_id}")
    if flow.status != "in_progress":
        raise ValueError(f"flow is {flow.status}")
    flow.status = "aborted"
    flow.updated_at = _iso_now()
    with _LOCK:
        _persist_unlocked()
    return {"status": "aborted", "flow": flow.public(), "prompt": None}
