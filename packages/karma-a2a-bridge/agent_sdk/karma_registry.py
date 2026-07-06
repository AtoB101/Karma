import httpx

_REGISTRY_URL = "https://a2aregistry.org"


def register_agent(card_dict: dict, registry_url: str = _REGISTRY_URL) -> bool:
    try:
        resp = httpx.post(f"{registry_url.rstrip('/')}/api/agents", json=card_dict, timeout=10)
        return resp.is_success
    except httpx.RequestError:
        return False


def search_agents(capabilities: list[str], registry_url: str = _REGISTRY_URL, limit: int = 20) -> list[dict]:
    try:
        params = {"limit": limit, "capabilities": ",".join(capabilities)}
        resp = httpx.get(f"{registry_url.rstrip('/')}/api/agents", params=params, timeout=10)
        if resp.is_success:
            data = resp.json()
            return data if isinstance(data, list) else data.get("agents", [])
        return []
    except httpx.RequestError:
        return []
