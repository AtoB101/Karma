import time
from typing import Any, Optional

import httpx

try:
    from eip712_auth import (
        OP_CANCEL,
        OP_CONFIRM,
        OP_CREATE,
        OP_HANDOFF,
        OP_SUBMIT,
        sign_a2a_task_op,
    )
except ImportError:  # package-relative when imported as agent_sdk
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from eip712_auth import (  # type: ignore
        OP_CANCEL,
        OP_CONFIRM,
        OP_CREATE,
        OP_HANDOFF,
        OP_SUBMIT,
        sign_a2a_task_op,
    )


class A2AClient:
    def __init__(self, base_url: str, private_key: str | None = None):
        self.base_url = base_url.rstrip("/")
        self.private_key = private_key
        self._nonce = 0

    def _next_nonce(self) -> int:
        self._nonce += 1
        return self._nonce

    def _auth(
        self,
        *,
        task_id: str,
        op_type: str,
        requester_id: str = "",
        amount_micro: int = 0,
    ) -> dict[str, Any] | None:
        if not self.private_key:
            return None
        from eth_account import Account

        acct = Account.from_key(self.private_key)
        deadline = int(time.time()) + 600
        nonce = self._next_nonce()
        sig = sign_a2a_task_op(
            private_key=self.private_key,
            task_id=task_id,
            op_type=op_type,
            agent=acct.address,
            requester_id=requester_id,
            amount_micro=amount_micro,
            nonce=nonce,
            deadline=deadline,
        )
        return {
            "agent": acct.address,
            "signature": sig,
            "nonce": nonce,
            "deadline": deadline,
            "amount_micro": amount_micro,
            "requester_id": requester_id,
        }

    def get_agent_card(self) -> Optional[dict]:
        try:
            resp = httpx.get(f"{self.base_url}/.well-known/agent-card.json", timeout=10)
            return resp.json() if resp.is_success else None
        except httpx.RequestError:
            return None

    def discover(self, requirement_text: str, buyer_identity_id: str = "", amount: float | None = None) -> Optional[dict]:
        body: dict[str, Any] = {"requirement_text": requirement_text}
        if buyer_identity_id:
            body["buyer_identity_id"] = buyer_identity_id
        if amount is not None:
            body["amount"] = amount
        try:
            resp = httpx.post(f"{self.base_url}/a2a/discover", json=body, timeout=20)
            return resp.json() if resp.is_success else None
        except httpx.RequestError:
            return None

    def send_task(
        self,
        task_id: str,
        skill: str,
        params: dict,
        requester_id: str = "",
    ) -> Optional[dict]:
        body: dict[str, Any] = {
            "task_id": task_id,
            "skill": skill,
            "params": params,
            "requester_id": requester_id,
        }
        auth = self._auth(task_id=task_id, op_type=OP_CREATE, requester_id=requester_id)
        if auth:
            body["auth"] = auth
        try:
            resp = httpx.post(f"{self.base_url}/a2a/task", json=body, timeout=30)
            return resp.json() if resp.is_success else None
        except httpx.RequestError:
            return None

    def confirm_task(self, task_id: str, seller_id: str = "", amount: float = 0.0, requester_id: str = "") -> Optional[dict]:
        micro = int(round(float(amount) * 1_000_000)) if amount else 0
        body: dict[str, Any] = {"seller_id": seller_id, "amount": amount}
        auth = self._auth(task_id=task_id, op_type=OP_CONFIRM, requester_id=requester_id, amount_micro=micro)
        if auth:
            body["auth"] = auth
        try:
            resp = httpx.post(f"{self.base_url}/a2a/task/{task_id}/confirm", json=body, timeout=30)
            return resp.json() if resp.is_success else None
        except httpx.RequestError:
            return None

    def submit_task(self, task_id: str, result: dict, requester_id: str = "") -> Optional[dict]:
        body: dict[str, Any] = {"result": result}
        auth = self._auth(task_id=task_id, op_type=OP_SUBMIT, requester_id=requester_id)
        if auth:
            body["auth"] = auth
        try:
            resp = httpx.post(f"{self.base_url}/a2a/task/{task_id}/submit", json=body, timeout=30)
            return resp.json() if resp.is_success else None
        except httpx.RequestError:
            return None

    def cancel_task(self, task_id: str, reason: str = "", requester_id: str = "") -> Optional[dict]:
        body: dict[str, Any] = {"reason": reason}
        auth = self._auth(task_id=task_id, op_type=OP_CANCEL, requester_id=requester_id)
        if auth:
            body["auth"] = auth
        try:
            resp = httpx.post(f"{self.base_url}/a2a/task/{task_id}/cancel", json=body, timeout=30)
            return resp.json() if resp.is_success else None
        except httpx.RequestError:
            return None

    def handoff(self, task_id: str, buyer_id: str = "", seller_id: str = "") -> Optional[dict]:
        body: dict[str, Any] = {"buyer_id": buyer_id, "seller_id": seller_id}
        auth = self._auth(task_id=task_id, op_type=OP_HANDOFF, requester_id=buyer_id)
        if auth:
            body["auth"] = auth
        try:
            resp = httpx.post(f"{self.base_url}/a2a/task/{task_id}/handoff", json=body, timeout=30)
            return resp.json() if resp.is_success else None
        except httpx.RequestError:
            return None

    def get_task_status(self, task_id: str) -> Optional[dict]:
        try:
            resp = httpx.get(f"{self.base_url}/a2a/task/{task_id}/status", timeout=10)
            return resp.json() if resp.is_success else None
        except httpx.RequestError:
            return None

    def negotiate(
        self,
        *,
        skill: str,
        params: dict,
        requester_id: str,
        amount: float,
        seller_id: str = "",
    ) -> dict[str, Any]:
        """Full A2A negotiate: create → confirm → submit → handoff."""
        import uuid

        task_id = f"neg-{uuid.uuid4().hex[:12]}"
        out: dict[str, Any] = {"task_id": task_id}
        out["create"] = self.send_task(task_id, skill, params, requester_id=requester_id)
        out["confirm"] = self.confirm_task(task_id, seller_id=seller_id, amount=amount, requester_id=requester_id)
        out["submit"] = self.submit_task(task_id, {"ok": True}, requester_id=requester_id)
        out["handoff"] = self.handoff(task_id, buyer_id=requester_id, seller_id=seller_id)
        out["ok"] = bool(out.get("confirm") and out["confirm"].get("status") == "accepted")
        return out
