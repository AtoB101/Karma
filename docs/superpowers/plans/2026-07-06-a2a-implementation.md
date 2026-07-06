# A2A Agent Discovery Integration — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans

**Goal:** Build `packages/karma-a2a-bridge/` — A2A Agent Card serving, Registry registration, and handoff bridge to Karma settlement.

**Architecture:** FastAPI service + lightweight SDK (pip-installable). Agents expose Agent Card via Bridge, register to A2A Registry, and negotiate tasks that translate to Karma Vouchers.

**Tech Stack:** Python 3.11+, FastAPI, a2a-sdk (or a2a-python), pytest, Docker

**Files to create:**

```
packages/karma-a2a-bridge/
├── pyproject.toml
├── README.md
├── main.py
├── config.py
├── models.py
├── a2a_server.py
├── card_builder.py
├── handoff_bridge.py
├── registry_client.py
├── agent_sdk/
│   ├── __init__.py
│   ├── karma_card.py
│   ├── karma_registry.py
│   └── karma_a2a_client.py
└── tests/
    ├── __init__.py
    ├── test_card_builder.py
    ├── test_handoff_bridge.py
    └── test_registry_client.py
```

---

### Task 1: Scaffold package structure

**Files:**
- Create: `packages/karma-a2a-bridge/pyproject.toml`
- Create: `packages/karma-a2a-bridge/README.md`

- [ ] **Step 1: Write pyproject.toml**

```toml
[build-system]
requires = ["setuptools>=61.0"]
build-backend = "setuptools.backends._legacy:_Backend"

[project]
name = "karma-a2a-bridge"
version = "0.1.0"
description = "A2A Agent Discovery Bridge for Karma Trust Protocol"
requires-python = ">=3.10"
dependencies = [
    "fastapi>=0.104.0",
    "uvicorn>=0.24.0",
    "httpx>=0.25.0",
    "pydantic>=2.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=7.4",
    "pytest-asyncio>=0.21",
    "httpx>=0.25.0",
]
sdk = [
    "httpx>=0.25.0",
]
```

- [ ] **Step 2: Write README.md**

```markdown
# Karma A2A Bridge

A2A Agent-to-Agent Protocol discovery bridge for Karma Trust Protocol.
Enables agents to discover each other, negotiate tasks, and settle via Karma.

## Quick Start

```bash
pip install -e .
uvicorn main:app --reload --port 8080
```

## Components

- `a2a_server.py` — A2A HTTP Server (Agent Card + Task handlers)
- `card_builder.py` — Dynamic Agent Card generation
- `handoff_bridge.py` — A2A Task → Karma Voucher translation
- `registry_client.py` — A2A Registry client
- `agent_sdk/` — Lightweight SDK for third-party agents
```

- [ ] **Step 3: Commit**

---

### Task 2: Config + Models

**Files:**
- Create: `packages/karma-a2a-bridge/config.py`
- Create: `packages/karma-a2a-bridge/models.py`

- [ ] **Step 1: Write config.py**

```python
import os

REGISTRY_URL = os.getenv("A2A_REGISTRY_URL", "https://a2aregistry.org")
KARMA_API_BASE = os.getenv("KARMA_API_BASE", "https://karma-network.ai")
KARMA_API_KEY = os.getenv("KARMA_API_KEY", "")

AGENT_ID = os.getenv("A2A_AGENT_ID", "karma_bridge_001")
AGENT_NAME = os.getenv("A2A_AGENT_NAME", "Karma A2A Bridge")
AGENT_DESCRIPTION = os.getenv("A2A_AGENT_DESC", "Karma Trust Protocol A2A Bridge Agent")
AGENT_CAPABILITIES = os.getenv("A2A_AGENT_CAPABILITIES", "karma_settle,agent_discovery").split(",")
AGENT_ENDPOINT = os.getenv("A2A_AGENT_ENDPOINT", "http://localhost:8080")
AGENT_ICON_URL = os.getenv("A2A_AGENT_ICON_URL", "")

KARMA_CONTRACT_ADDRESS = os.getenv("KARMA_CONTRACT_ADDRESS", "0x496d178a5D32E9410E52bD5800602BDEe81B2A91")
KARMA_NETWORK = os.getenv("KARMA_NETWORK", "sepolia")
KARMA_SETTLEMENT_MODES = os.getenv("KARMA_SETTLEMENT_MODES", "bilateral,escrow").split(",")

HEARTBEAT_INTERVAL = int(os.getenv("A2A_HEARTBEAT_INTERVAL", "60"))
```

- [ ] **Step 2: Write models.py**

```python
from pydantic import BaseModel
from typing import Optional


class AgentCardSkillInputSchema(BaseModel):
    type: str = "object"
    properties: dict = {}
    required: list[str] = []


class AgentCardSkill(BaseModel):
    id: str
    name: str
    description: str
    input_schema: AgentCardSkillInputSchema
    output_schema: dict = {"type": "object", "properties": {}}


class AgentCardKarmaExt(BaseModel):
    version: str = "0.1.0"
    contract_address: str = ""
    supports_voucher: bool = True
    supports_evidence: bool = True
    settlement_modes: list[str] = ["bilateral"]
    accepted_tokens: list[str] = ["USDC"]
    network: str = "sepolia"


class AgentCard(BaseModel):
    a2a_version: str = "1.0"
    name: str
    description: str
    agent_id: str
    icon_url: str = ""
    capabilities: list[str]
    endpoint: str
    protocols: list[str] = ["a2a", "karma"]
    skills: list[AgentCardSkill] = []
    karma: AgentCardKarmaExt = AgentCardKarmaExt()


class A2ATaskRequest(BaseModel):
    task_id: str
    skill: str
    params: dict = {}
    requester_id: Optional[str] = None
    callback_url: Optional[str] = None


class A2ATaskResponse(BaseModel):
    task_id: str
    status: str  # negotiating | accepted | rejected | completed | failed
    message: str = ""
    voucher_id: Optional[str] = None
    result: Optional[dict] = None


class RegistrySearchQuery(BaseModel):
    capabilities: list[str] = []
    limit: int = 20
```

- [ ] **Step 3: Commit**

---

### Task 3: Card Builder

**Files:**
- Create: `packages/karma-a2a-bridge/card_builder.py`
- Test: `packages/karma-a2a-bridge/tests/test_card_builder.py`
- Create: `packages/karma-a2a-bridge/tests/__init__.py`

- [ ] **Step 1: Write test_card_builder.py**

```python
import pytest
from card_builder import build_agent_card, build_from_karma_agent
from models import AgentCard


class TestBuildAgentCard:
    def test_build_minimal(self):
        card = build_agent_card(
            agent_id="test_agent_001",
            name="Test Agent",
            description="A test agent",
            capabilities=["karma_settle"],
            endpoint="http://localhost:8080",
        )
        assert isinstance(card, AgentCard)
        assert card.agent_id == "test_agent_001"
        assert card.a2a_version == "1.0"
        assert "karma_settle" in card.capabilities
        assert card.karma.contract_address != ""

    def test_build_with_skills(self):
        card = build_agent_card(
            agent_id="food_agent",
            name="Food Agent",
            description="Order food",
            capabilities=["order_food", "karma_settle"],
            endpoint="http://localhost:8080",
            skills=[{
                "id": "order_food",
                "name": "Order Food",
                "description": "Place food order",
                "input_schema": {
                    "type": "object",
                    "properties": {
                        "restaurant": {"type": "string"},
                        "items": {"type": "array", "items": {"type": "string"}},
                    },
                    "required": ["restaurant", "items"],
                },
                "output_schema": {
                    "type": "object",
                    "properties": {
                        "order_id": {"type": "string"},
                        "total": {"type": "number"},
                    },
                },
            }],
        )
        assert len(card.skills) == 1
        assert card.skills[0].id == "order_food"

    def test_build_from_karma_agent_with_minimal_data(self):
        agent_data = {
            "agent_id": "external_agent_001",
            "name": "External Agent",
            "role": "worker",
            "endpoint_url": "https://external.example.com/a2a",
            "capabilities": ["data_processing"],
        }
        card = build_from_karma_agent(agent_data)
        assert card.agent_id == "external_agent_001"
        assert "data_processing" in card.capabilities
        assert card.endpoint == "https://external.example.com/a2a"
        assert "karma" not in card.capabilities  # not in original data
```

- [ ] **Step 2: Run failing tests**

Run: `cd packages/karma-a2a-bridge && python -m pytest tests/test_card_builder.py -v`
Expected: FAIL — ImportError (card_builder module not found)

- [ ] **Step 3: Write card_builder.py**

```python
import os
from models import AgentCard, AgentCardSkill, AgentCardSkillInputSchema, AgentCardKarmaExt
import config


def build_agent_card(
    agent_id: str,
    name: str,
    description: str,
    capabilities: list[str],
    endpoint: str,
    icon_url: str = "",
    skills: list[dict] | None = None,
    protocols: list[str] | None = None,
    karma_ext: dict | None = None,
) -> AgentCard:
    skill_objects = []
    if skills:
        for s in skills:
            inp = AgentCardSkillInputSchema(
                type=s.get("input_schema", {}).get("type", "object"),
                properties=s.get("input_schema", {}).get("properties", {}),
                required=s.get("input_schema", {}).get("required", []),
            )
            skill_objects.append(AgentCardSkill(
                id=s["id"],
                name=s.get("name", s["id"]),
                description=s.get("description", ""),
                input_schema=inp,
                output_schema=s.get("output_schema", {"type": "object", "properties": {}}),
            ))
    ext = AgentCardKarmaExt(
        contract_address=karma_ext.get("contract_address", config.KARMA_CONTRACT_ADDRESS) if karma_ext else config.KARMA_CONTRACT_ADDRESS,
        network=karma_ext.get("network", config.KARMA_NETWORK) if karma_ext else config.KARMA_NETWORK,
        settlement_modes=karma_ext.get("settlement_modes", config.KARMA_SETTLEMENT_MODES) if karma_ext else config.KARMA_SETTLEMENT_MODES,
    )
    return AgentCard(
        name=name,
        description=description,
        agent_id=agent_id,
        icon_url=icon_url,
        capabilities=capabilities,
        endpoint=endpoint,
        protocols=protocols or ["a2a", "karma"],
        skills=skill_objects,
        karma=ext,
    )


def build_from_karma_agent(agent_data: dict) -> AgentCard:
    return build_agent_card(
        agent_id=agent_data.get("agent_id", "unknown"),
        name=agent_data.get("name", "Unknown Agent"),
        description=agent_data.get("description", ""),
        capabilities=agent_data.get("capabilities", []),
        endpoint=agent_data.get("endpoint_url", ""),
        icon_url=agent_data.get("icon_url", ""),
    )
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd packages/karma-a2a-bridge && python -m pytest tests/test_card_builder.py -v`
Expected: PASS (3/3)

- [ ] **Step 5: Commit**

---

### Task 4: A2A Server (Agent Card + Task endpoints)

**Files:**
- Create: `packages/karma-a2a-bridge/a2a_server.py`
- Create: `packages/karma-a2a-bridge/main.py`

- [ ] **Step 1: Write a2a_server.py**

```python
from fastapi import APIRouter, HTTPException
from models import AgentCard, A2ATaskRequest, A2ATaskResponse
from card_builder import build_agent_card
import config

router = APIRouter()

_agent_card: AgentCard | None = None


def set_agent_card(card: AgentCard):
    global _agent_card
    _agent_card = card


def get_agent_card() -> AgentCard:
    global _agent_card
    if _agent_card is None:
        _agent_card = build_agent_card(
            agent_id=config.AGENT_ID,
            name=config.AGENT_NAME,
            description=config.AGENT_DESCRIPTION,
            capabilities=config.AGENT_CAPABILITIES,
            endpoint=config.AGENT_ENDPOINT,
            icon_url=config.AGENT_ICON_URL,
        )
    return _agent_card


@router.get("/.well-known/agent-card.json")
async def serve_agent_card():
    return get_agent_card().model_dump()


@router.post("/a2a/task")
async def receive_task(req: A2ATaskRequest):
    card = get_agent_card()
    skill_ids = [s.id for s in card.skills]
    if req.skill not in skill_ids:
        raise HTTPException(status_code=400, detail=f"Skill '{req.skill}' not supported. Available: {skill_ids}")
    return A2ATaskResponse(
        task_id=req.task_id,
        status="accepted",
        message=f"Task {req.task_id} accepted for skill '{req.skill}'",
    )


@router.get("/a2a/task/{task_id}/status")
async def get_task_status(task_id: str):
    return A2ATaskResponse(
        task_id=task_id,
        status="negotiating",
        message="Task status placeholder",
    )
```

- [ ] **Step 2: Write main.py**

```python
import uvicorn
from fastapi import FastAPI
from a2a_server import router as a2a_router, set_agent_card
from card_builder import build_agent_card
import config

app = FastAPI(title="Karma A2A Bridge", version="0.1.0")

card = build_agent_card(
    agent_id=config.AGENT_ID,
    name=config.AGENT_NAME,
    description=config.AGENT_DESCRIPTION,
    capabilities=config.AGENT_CAPABILITIES,
    endpoint=config.AGENT_ENDPOINT,
    icon_url=config.AGENT_ICON_URL,
)
set_agent_card(card)

app.include_router(a2a_router)


@app.get("/health")
async def health():
    return {"status": "ok", "agent_id": config.AGENT_ID}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

- [ ] **Step 3: Quick smoke test**

Run: `cd packages/karma-a2a-bridge && python -c "from main import app; print('App loaded:', app.title)"`
Expected: `App loaded: Karma A2A Bridge`

- [ ] **Step 4: Commit**

---

### Task 5: Handoff Bridge (A2A → Karma Voucher)

**Files:**
- Create: `packages/karma-a2a-bridge/handoff_bridge.py`
- Test: `packages/karma-a2a-bridge/tests/test_handoff_bridge.py`

- [ ] **Step 1: Write test_handoff_bridge.py**

```python
import pytest
from handoff_bridge import a2a_task_to_voucher, a2a_task_to_handoff
from models import A2ATaskRequest


class TestHandoffBridge:
    def test_a2a_task_to_voucher(self):
        task = A2ATaskRequest(
            task_id="task_food_001",
            skill="order_food",
            params={"restaurant": "Pizza Place", "items": ["Margherita"]},
        )
        voucher = a2a_task_to_voucher(task, seller_id="agent_food_001", amount=25.0)
        assert voucher["voucher_id"].startswith("a2a_")
        assert voucher["seller_id"] == "agent_food_001"
        assert voucher["amount"] == 25.0
        assert "task_id" in voucher["metadata"]

    def test_a2a_task_to_handoff(self):
        task = A2ATaskRequest(task_id="task_002", skill="book_flight", params={"from": "NYC", "to": "LAX"})
        handoff = a2a_task_to_handoff(task, buyer_id="user_agent_001", seller_id="flight_agent_001")
        assert handoff["trace_id"] == "task_002"
        assert handoff["task_id"] == "task_002"
        assert handoff["buyer_identity_id"] == "user_agent_001"
        assert handoff["seller_identity_id"] == "flight_agent_001"
        assert "authorization" in handoff
```

- [ ] **Step 2: Run failing tests**

Run: `cd packages/karma-a2a-bridge && python -m pytest tests/test_handoff_bridge.py -v`
Expected: FAIL

- [ ] **Step 3: Write handoff_bridge.py**

```python
import json
import hashlib
import time
from models import A2ATaskRequest


def _make_id(prefix: str = "a2a") -> str:
    raw = f"{prefix}_{time.time_ns()}"
    return f"{prefix}_{hashlib.sha256(raw.encode()).hexdigest()[:12]}"


def a2a_task_to_voucher(
    task: A2ATaskRequest,
    seller_id: str,
    amount: float,
    currency: str = "USDC",
    buyer_id: str = "",
) -> dict:
    voucher_id = _make_id("a2a")
    return {
        "voucher_id": voucher_id,
        "buyer_id": buyer_id or task.requester_id or "unknown",
        "seller_id": seller_id,
        "amount": amount,
        "currency": currency,
        "skill": task.skill,
        "params": task.params,
        "metadata": {
            "source": "a2a_bridge",
            "task_id": task.task_id,
            "created_at": int(time.time()),
        },
    }


def a2a_task_to_handoff(
    task: A2ATaskRequest,
    buyer_id: str,
    seller_id: str,
) -> dict:
    return {
        "trace_id": task.task_id,
        "task_id": task.task_id,
        "buyer_identity_id": buyer_id,
        "seller_identity_id": seller_id,
        "voucher_id": _make_id("vcr"),
        "skill": task.skill,
        "params": task.params,
        "authorization": {
            "manual_console_steps_completed": True,
            "a2a_negotiated": True,
        },
        "created_at": int(time.time()),
    }


def evidence_chain(task_ids: list[str]) -> dict:
    return {
        "chain_id": _make_id("evc"),
        "task_ids": task_ids,
        "agent_count": len(task_ids),
        "status": "pending",
    }
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd packages/karma-a2a-bridge && python -m pytest tests/test_handoff_bridge.py -v`
Expected: PASS (2/2)

- [ ] **Step 5: Commit**

---

### Task 6: Registry Client (register + search)

**Files:**
- Create: `packages/karma-a2a-bridge/registry_client.py`
- Test: `packages/karma-a2a-bridge/tests/test_registry_client.py`

- [ ] **Step 1: Write test_registry_client.py**

```python
import pytest
from registry_client import RegistryClient
from models import AgentCard, AgentCardKarmaExt


class TestRegistryClient:
    def test_register_card(self, monkeypatch):
        client = RegistryClient(base_url="https://fake-registry.example.com")
        card = AgentCard(
            name="Test", description="Test", agent_id="t1",
            capabilities=["test"], endpoint="http://localhost",
            karma=AgentCardKarmaExt(),
        )
        result = client.register(card)
        assert result is True

    def test_search_by_capability(self, monkeypatch):
        client = RegistryClient(base_url="https://fake-registry.example.com")
        results = client.search(capabilities=["karma_settle", "order_food"])
        assert isinstance(results, list)

    def test_heartbeat(self, monkeypatch):
        client = RegistryClient(base_url="https://fake-registry.example.com")
        result = client.heartbeat("agent_001")
        assert result is True

    def test_unregister(self, monkeypatch):
        client = RegistryClient(base_url="https://fake-registry.example.com")
        result = client.unregister("agent_001")
        assert result is True
```

- [ ] **Step 2: Run failing tests**

Run: `cd packages/karma-a2a-bridge && python -m pytest tests/test_registry_client.py -v`
Expected: FAIL

- [ ] **Step 3: Write registry_client.py**

```python
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
```

- [ ] **Step 4: Run tests to verify pass**

Run: `cd packages/karma-a2a-bridge && python -m pytest tests/test_registry_client.py -v`
Expected: PASS (4/4)

- [ ] **Step 5: Commit**

---

### Task 7: Agent SDK (pip-installable)

**Files:**
- Create: `packages/karma-a2a-bridge/agent_sdk/__init__.py`
- Create: `packages/karma-a2a-bridge/agent_sdk/karma_card.py`
- Create: `packages/karma-a2a-bridge/agent_sdk/karma_registry.py`
- Create: `packages/karma-a2a-bridge/agent_sdk/karma_a2a_client.py`

- [ ] **Step 1: Write agent_sdk/__init__.py**

```python
from .karma_card import build_card
from .karma_registry import register_agent, search_agents
from .karma_a2a_client import A2AClient

__all__ = ["build_card", "register_agent", "search_agents", "A2AClient"]
```

- [ ] **Step 2: Write agent_sdk/karma_card.py**

```python
from models import AgentCard, AgentCardSkill, AgentCardSkillInputSchema, AgentCardKarmaExt


def build_card(
    agent_id: str,
    name: str,
    description: str,
    capabilities: list[str],
    endpoint: str,
    skills: list[dict] | None = None,
    contract_address: str = "",
    network: str = "sepolia",
) -> dict:
    skill_objects = []
    if skills:
        for s in skills:
            inp = AgentCardSkillInputSchema(
                type=s.get("input_schema", {}).get("type", "object"),
                properties=s.get("input_schema", {}).get("properties", {}),
                required=s.get("input_schema", {}).get("required", []),
            )
            skill_objects.append(AgentCardSkill(
                id=s["id"],
                name=s.get("name", s["id"]),
                description=s.get("description", ""),
                input_schema=inp,
                output_schema=s.get("output_schema", {"type": "object", "properties": {}}),
            ))
    ext = AgentCardKarmaExt(contract_address=contract_address, network=network)
    card = AgentCard(
        name=name,
        description=description,
        agent_id=agent_id,
        capabilities=capabilities,
        endpoint=endpoint,
        skills=skill_objects,
        karma=ext,
    )
    return card.model_dump()
```

- [ ] **Step 3: Write agent_sdk/karma_registry.py**

```python
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
```

- [ ] **Step 4: Write agent_sdk/karma_a2a_client.py**

```python
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
```

- [ ] **Step 5: Quick smoke test**

Run: `cd packages/karma-a2a-bridge && python -c "from agent_sdk import build_card; c = build_card('test','Test','desc',['test'],'http://local'); print('Card built:', c['agent_id'])"`
Expected: `Card built: test`

- [ ] **Step 6: Commit**

---

### Task 8: Integration — Wire everything in main.py

**Files:**
- Modify: `packages/karma-a2a-bridge/main.py`

- [ ] **Step 1: Update main.py with Registry auto-register and heartbeat**

```python
import asyncio
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from a2a_server import router as a2a_router, set_agent_card, get_agent_card
from card_builder import build_agent_card
from registry_client import RegistryClient
import config


registry = RegistryClient(base_url=config.REGISTRY_URL)


@asynccontextmanager
async def lifespan(app: FastAPI):
    card = build_agent_card(
        agent_id=config.AGENT_ID,
        name=config.AGENT_NAME,
        description=config.AGENT_DESCRIPTION,
        capabilities=config.AGENT_CAPABILITIES,
        endpoint=config.AGENT_ENDPOINT,
        icon_url=config.AGENT_ICON_URL,
    )
    set_agent_card(card)

    registered = registry.register(card)
    print(f"[A2A] Registered to {config.REGISTRY_URL}: {registered}")

    async def heartbeat_loop():
        while True:
            await asyncio.sleep(config.HEARTBEAT_INTERVAL)
            ok = registry.heartbeat(config.AGENT_ID)
            if not ok:
                print(f"[A2A] Heartbeat failed for {config.AGENT_ID}")

    task = asyncio.create_task(heartbeat_loop())
    yield
    task.cancel()
    registry.unregister(config.AGENT_ID)
    print(f"[A2A] Unregistered {config.AGENT_ID}")


app = FastAPI(title="Karma A2A Bridge", version="0.1.0", lifespan=lifespan)
app.include_router(a2a_router)


@app.get("/health")
async def health():
    return {"status": "ok", "agent_id": config.AGENT_ID}


if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)
```

- [ ] **Step 2: Verify imports work**

Run: `cd packages/karma-a2a-bridge && python -c "from main import app; print('OK:', app.title)"`
Expected: `OK: Karma A2A Bridge`

- [ ] **Step 3: Commit**

---

### Task 9: Run full test suite

- [ ] **Step 1: Run all tests**

Run: `cd packages/karma-a2a-bridge && python -m pytest tests/ -v`
Expected: All tests pass

- [ ] **Step 2: Fix any failures and iterate until all pass**

- [ ] **Step 3: Final commit**

---

**Plan complete.** Ready to execute.
