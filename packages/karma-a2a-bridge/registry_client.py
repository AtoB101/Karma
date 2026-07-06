import httpx
from models import AgentCard


class RegistryClient:
    def __init__(self, base_url: str = "https://a2aregistry.org"):
        self.base_url = base_url.rstrip("/")

    def register(self, card: AgentCard) -> bool:
        try:
            resp = httpx.post(
                f"{self.base_url}/api/agents",
                json=card.model_dump(),
                timeout=10,
            )
            return resp.is_success
        except httpx.RequestError:
            return False

    def search(self, capabilities: list[str] | None = None, limit: int = 20) -> list[dict]:
        try:
            params = {"limit": limit}
            if capabilities:
                params["capabilities"] = ",".join(capabilities)
            resp = httpx.get(f"{self.base_url}/api/agents", params=params, timeout=10)
            if resp.is_success:
                data = resp.json()
                return data if isinstance(data, list) else data.get("agents", [])
            return []
        except httpx.RequestError:
            return []

    def heartbeat(self, agent_id: str) -> bool:
        try:
            resp = httpx.post(
                f"{self.base_url}/api/agents/{agent_id}/heartbeat",
                timeout=10,
            )
            return resp.is_success
        except httpx.RequestError:
            return False

    def unregister(self, agent_id: str) -> bool:
        try:
            resp = httpx.delete(
                f"{self.base_url}/api/agents/{agent_id}",
                timeout=10,
            )
            return resp.is_success
        except httpx.RequestError:
            return False
