import httpx
from typing import Optional


class A2AClient:
    def __init__(self, base_url: str):
        self.base_url = base_url.rstrip("/")

    def get_agent_card(self) -> Optional[dict]:
        try:
            resp = httpx.get(f"{self.base_url}/.well-known/agent-card.json", timeout=10)
            return resp.json() if resp.is_success else None
        except httpx.RequestError:
            return None

    def send_task(self, task_id: str, skill: str, params: dict, requester_id: str = "") -> Optional[dict]:
        try:
            resp = httpx.post(
                f"{self.base_url}/a2a/task",
                json={"task_id": task_id, "skill": skill, "params": params, "requester_id": requester_id},
                timeout=30,
            )
            return resp.json() if resp.is_success else None
        except httpx.RequestError:
            return None

    def get_task_status(self, task_id: str) -> Optional[dict]:
        try:
            resp = httpx.get(f"{self.base_url}/a2a/task/{task_id}/status", timeout=10)
            return resp.json() if resp.is_success else None
        except httpx.RequestError:
            return None
