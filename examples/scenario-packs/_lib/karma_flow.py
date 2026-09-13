"""
Karma 场景包 · 共享客户端 —— 把一笔生意在 Karma 上跑完的完整链路收成一条直线。

    买方下单   登录 → 建任务合同 → 建结算单 → 转 pending → 指派卖方（lock）
    卖方执行   start → 上报进度 → 产出交付凭证 → 交执行回执
    交付验真   实物三方（外卖 / 跨境电商）：卖方发出 → 物流接件核验 → 送达凭证 → 买方确认
              票务回执（酒店）：卖方出确认号 / 回执 → 买方确认
              轻量数字（数据 API / 打车）：执行回执本身即证据
    结算       submit → 买方验收 → SETTLED（真实释放买方锁仓额度给卖方）

安全边界：只用 SIWE 会话签名 + 协议内角色签名，全程不接触任何用户私钥 / 助记词。
"""
from __future__ import annotations

import hashlib
import secrets
import time
from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

DEFAULT_BASE_URL = "https://karma-network.ai"


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


class KarmaError(RuntimeError):
    """一次 API 调用失败。带状态码与原始响应，方便定位。"""

    def __init__(self, method: str, path: str, status: int, body: Any):
        self.method, self.path, self.status, self.body = method, path, status, body
        super().__init__(f"{method} {path} -> HTTP {status}: {body}")


class KarmaFlow:
    """一个身份（一把钱包）在 Karma 上的操作面。买方 / 卖方 / 物流各起一个实例。"""

    def __init__(
        self,
        wallet_key: str,
        *,
        base_url: str = DEFAULT_BASE_URL,
        label: str = "agent",
        timeout: float = 40.0,
    ):
        from eth_account import Account

        self.account = Account.from_key(wallet_key)
        self.address = self.account.address
        self.base_url = base_url.rstrip("/")
        self.label = label
        self.identity_id: str = ""
        self.token: str = ""
        self._client = httpx.Client(base_url=self.base_url, timeout=timeout)

    # ------------------------------------------------------------------ 传输
    def _call(
        self,
        method: str,
        path: str,
        *,
        body: Any = None,
        auth: bool = True,
        expect: tuple[int, ...] = (200, 201),
    ) -> Any:
        headers = {"Accept": "application/json"}
        if auth:
            if not self.token:
                raise RuntimeError(f"{self.label}: 还没登录，先调 login()")
            headers["Authorization"] = f"Bearer {self.token}"
        resp = self._client.request(method, path, json=body, headers=headers)
        text = resp.text
        try:
            data = resp.json() if text else None
        except ValueError:
            data = {"raw": text[:500]}
        if resp.status_code not in expect:
            raise KarmaError(method, path, resp.status_code, data)
        return data

    def get(self, path: str, **kw) -> Any:
        return self._call("GET", path, **kw)

    def post(self, path: str, body: Any = None, **kw) -> Any:
        return self._call("POST", path, body=body if body is not None else {}, **kw)

    # ------------------------------------------------------------------ 登录
    def login(self) -> str:
        """SIWE：钱包签一句挑战，换来会话令牌与身份 ID。不暴露私钥。"""
        ch = self.post("/v1/auth/siwe/challenge", {"address": self.address}, auth=False)
        message = ch.get("message") or ch.get("challenge") or ""
        signature = self.account.sign_message(_encode_defunct(message)).signature.hex()
        if not signature.startswith("0x"):
            signature = "0x" + signature
        out = self.post(
            "/v1/auth/siwe/verify",
            {
                "nonce": ch["nonce"],
                "signature": signature,
                "address": self.address,
            },
            auth=False,
        )
        self.token = out.get("access_token") or out.get("token") or ""
        self.identity_id = out.get("identity_id") or out.get("agent_id") or ""
        if not self.token or not self.identity_id:
            raise RuntimeError(f"{self.label}: 登录返回缺少 access_token / identity_id：{out}")
        return self.identity_id

    # ------------------------------------------------------------------ 买方
    def create_contract(
        self,
        *,
        task_id: str,
        title: str,
        description: str,
        escrow_amount: float,
        deadline_days: int = 7,
        expected_steps: int = 3,
    ) -> dict:
        return self.post(
            "/v1/contracts",
            {
                "task_id": task_id,
                "client_agent_id": self.identity_id,
                "title": title,
                "description": description,
                "expected_output_schema": {"type": "object"},
                "expected_step_count": expected_steps,
                "escrow_amount": escrow_amount,
                "currency": "USDC",
                "deadline_at": iso(utcnow() + timedelta(days=deadline_days)),
            },
        )

    def create_settlement(
        self,
        *,
        task_id: str,
        escrow_amount: float,
        scene_id: str,
        delivery_days: int = 7,
    ) -> dict:
        return self.post(
            "/v1/settlement/create",
            {
                "task_id": task_id,
                "client_agent_id": self.identity_id,
                "escrow_amount": escrow_amount,
                "currency": "USDC",
                "delivery_deadline_at": iso(utcnow() + timedelta(days=delivery_days)),
                "progress_rule_spec": {"scene_id": scene_id},
            },
        )

    def to_pending(self, task_id: str) -> dict:
        return self.post(f"/v1/settlement/{task_id}/pending")

    def assign_seller(self, task_id: str, seller_identity_id: str) -> dict:
        """lock：买方把单子指派给卖方（要求卖方已是网络里的身份）。"""
        return self.post(
            f"/v1/settlement/{task_id}/lock", {"worker_agent_id": seller_identity_id}
        )

    # ------------------------------------------------------------------ 卖方
    def start(self, task_id: str) -> dict:
        return self.post(f"/v1/settlement/{task_id}/start")

    def submit_delivery(self, task_id: str) -> dict:
        return self.post(f"/v1/settlement/{task_id}/submit")

    def report_progress(
        self,
        *,
        task_id: str,
        progress_percent: float,
        claimed_value_percent: float,
        note: str = "",
    ) -> dict:
        now = utcnow()
        return self.post(
            "/v1/progress",
            {
                "progress_receipt_id": "pr_" + secrets.token_hex(12),
                "task_id": task_id,
                "seller_identity_id": self.identity_id,
                "progress_percent": progress_percent,
                "claimed_value_percent": claimed_value_percent,
                "evidence_hash": sha256_hex(f"{task_id}:{progress_percent}:{note}"),
                "runtime_log_hash": sha256_hex(f"{task_id}:{now.isoformat()}:log"),
                "timestamp": iso(now),
                "seller_signature": "runtime:" + self.identity_id,
                "validation_method": "seller_attested",
            },
        )

    def submit_receipt(
        self,
        *,
        task_id: str,
        step_index: int,
        tool_name: str,
        input_payload: str,
        output_payload: str,
        started_at: datetime,
        duration_ms: int = 1200,
        ok: bool = True,
    ) -> dict:
        ended_at = started_at + timedelta(milliseconds=duration_ms)
        return self.post(
            "/v1/receipts",
            {
                "receipt_id": "rc_" + secrets.token_hex(12),
                "task_id": task_id,
                "agent_id": self.identity_id,
                "step_index": step_index,
                "tool_name": tool_name,
                "input_hash": sha256_hex(input_payload),
                "output_hash": sha256_hex(output_payload),
                "started_at": iso(started_at),
                "ended_at": iso(ended_at),
                "duration_ms": duration_ms,
                "status": "success" if ok else "failure",
                "signature": "runtime:" + self.identity_id,
                "metadata": {},
            },
        )

    # ------------------------------------------------------- 交付验真（P7）
    def dv_open(
        self,
        *,
        task_id: str,
        scene_id: str,
        seller_identity_id: str,
        buyer_identity_id: str,
        amount: float,
        logistics_identity_id: str | None = None,
    ) -> dict:
        return self.post(
            "/v1/delivery-verification/sessions",
            {
                "task_id": task_id,
                "scene_id": scene_id,
                "seller_agent_id": seller_identity_id,
                "buyer_agent_id": buyer_identity_id,
                "logistics_agent_id": logistics_identity_id,
                "amount": amount,
            },
        )

    def dv(self, verification_id: str) -> dict:
        return self.get(f"/v1/delivery-verification/{verification_id}")

    def dv_seller_issue(self, verification_id: str, *, ship_proof_hash: str | None = None) -> dict:
        return self.post(
            f"/v1/delivery-verification/{verification_id}/seller-ship",
            {"actor_agent_id": self.identity_id, "ship_proof_hash": ship_proof_hash},
        )

    def dv_logistics_intake(self, verification_id: str, *, item_matches: bool = True) -> dict:
        return self.post(
            f"/v1/delivery-verification/{verification_id}/logistics-intake",
            {"actor_agent_id": self.identity_id, "item_matches": item_matches},
        )

    def dv_capture_challenge(self, verification_id: str, *, party_role: str = "logistics") -> dict:
        return self.post(
            f"/v1/delivery-verification/{verification_id}/capture-challenge",
            {"party_role": party_role, "geo_hash": "geo_" + secrets.token_hex(6)},
        )

    def dv_logistics_deliver(self, verification_id: str, *, challenge: dict) -> dict:
        return self.post(
            f"/v1/delivery-verification/{verification_id}/logistics-deliver",
            {
                "actor_agent_id": self.identity_id,
                "content_hash": "pod_" + secrets.token_hex(16),
                "delivery_proof_type": "delivery_photo_tagged",
                "nonce": challenge.get("nonce"),
                "captured_at": challenge.get("captured_at"),
                "geo_hash": challenge.get("geo_hash"),
                "tag_hmac": challenge.get("tag_hmac"),
            },
        )

    def dv_submit_proof(
        self,
        verification_id: str,
        *,
        proof_type: str,
        party_role: str = "seller",
    ) -> dict:
        return self.post(
            f"/v1/delivery-verification/{verification_id}/proofs",
            {
                "proof_type": proof_type,
                "content_hash": proof_type + "_" + secrets.token_hex(16),
                "actor_agent_id": self.identity_id,
                "party_role": party_role,
            },
        )

    def dv_buyer_confirm(self, verification_id: str) -> dict:
        return self.post(
            f"/v1/delivery-verification/{verification_id}/buyer-confirm",
            {"actor_agent_id": self.identity_id, "confirm": True},
        )

    # ------------------------------------------------------------------ 结算
    def buyer_accept(
        self,
        task_id: str,
        *,
        scene_id: str | None = None,
        confirmation_session_id: str | None = None,
    ) -> dict:
        path = f"/v1/settlement/{task_id}/buyer-accept"
        params = []
        if scene_id:
            params.append(f"scene_id={scene_id}")
        if confirmation_session_id:
            params.append(f"confirmation_session_id={confirmation_session_id}")
        if params:
            path += "?" + "&".join(params)
        return self.post(path)

    def start_confirmation(self, *, scene_id: str, step: str, amount: float) -> dict:
        return self.post(
            "/v1/confirmations/sessions",
            {
                "scene_id": scene_id,
                "role": "buyer",
                "step": step,
                "owner_agent_id": self.identity_id,
                "context": {"amount": amount, "currency": "USDC"},
                "interaction_ref": f"{step}:{scene_id}:{secrets.token_hex(4)}",
            },
        )

    def decide_confirmation(self, session_id: str, *, confirm: bool = True) -> dict:
        return self.post(
            f"/v1/confirmations/sessions/{session_id}/decide",
            {"confirm": confirm, "actor_agent_id": self.identity_id},
            expect=(200, 201, 403),
        )

    # ------------------------------------------------------------------ 只读
    def settlement(self, task_id: str) -> dict | None:
        resp = self._client.get(
            f"/v1/settlement/{task_id}",
            headers={"Authorization": f"Bearer {self.token}", "Accept": "application/json"},
        )
        if resp.status_code == 404:
            return None
        if resp.status_code != 200:
            raise KarmaError("GET", f"/v1/settlement/{task_id}", resp.status_code, resp.text[:300])
        return resp.json()

    def transitions(self, task_id: str) -> list:
        return self.get(f"/v1/settlement/{task_id}/transitions")

    def capacity(self) -> dict:
        return self.get(f"/v1/capacity/{self.identity_id}")

    def close(self) -> None:
        self._client.close()


def _encode_defunct(message: str):
    from eth_account.messages import encode_defunct

    return encode_defunct(text=message)


def wait_for(fn, *, timeout: float = 20.0, interval: float = 1.0, what: str = "condition"):
    """轮询直到 fn() 返回真值。用于等后端把异步步骤落库。"""
    deadline = time.time() + timeout
    last = None
    while time.time() < deadline:
        last = fn()
        if last:
            return last
        time.sleep(interval)
    raise TimeoutError(f"等待超时（{timeout}s）：{what}")
