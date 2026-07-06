# A2A Agent Discovery Integration for Karma Trust Protocol

**Date:** 2026-07-06
**Status:** Draft
**Version:** 1.0

## 1. Objective

Enable all agents connected to Karma (user agents + merchant agents) to dynamically discover each other, forming a complete "Discover → Negotiate → Karma Trust Settlement" loop.

**Example scenario:** A user agent can automatically search for and find "food delivery agent", "flight booking agent", "hotel agent" that support Karma settlement.

## 2. Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                      A2A Discovery Layer                          │
│                                                                    │
│  ┌──────────────┐   ┌──────────────┐   ┌──────────────────┐       │
│  │ User Agent   │   │ Food Agent   │   │ Flight Agent     │       │
│  │ (A2A Client) │   │ (A2A Server) │   │ (A2A Server)     │       │
│  └──────┬───────┘   └──────┬───────┘   └────────┬─────────┘       │
│         │ discover         │ agent-card         │ agent-card        │
│         ▼                  ▼                    ▼                  │
│  ┌────────────────────────────────────────────────────────────┐   │
│  │  A2A Registry (a2aregistry.org / self-hosted)              │   │
│  │  - Agent Card register / search by capabilities / health    │   │
│  └────────────────────────┬───────────────────────────────────┘   │
│                           │ A2A task after negotiation             │
│  ┌────────────────────────▼───────────────────────────────────┐   │
│  │  Karma A2A Bridge Service (new)                             │   │
│  │                                                              │   │
│  │  ├─ a2a_server.py     — A2A HTTP Server (Card + Task)       │   │
│  │  ├─ registry_client.py  — Registry register/search           │   │
│  │  ├─ card_builder.py  — Dynamic Agent Card building           │   │
│  │  ├─ handoff_bridge.py— A2A Task → Karma Voucher/handoff     │   │
│  │  └─ agent_sdk/       — Lightweight SDK for agents           │   │
│  └────────────────────────┬───────────────────────────────────┘   │
│                           │ Voucher / Evidence                     │
│  ┌────────────────────────▼───────────────────────────────────┐   │
│  │  Karma Core API (existing, unchanged)                       │   │
│  │  /v1/agents  /v1/settlement  /v1/vouchers  /v1/evidence     │   │
│  │  OpenClaw / OpenManus Adapters                              │   │
│  └─────────────────────────────────────────────────────────────┘   │
└──────────────────────────────────────────────────────────────────┘
```

## 3. Agent Card Standard

Each agent exposes an Agent Card at `/.well-known/agent-card.json` (or proxied via A2A Bridge).

```json
{
  "a2a_version": "1.0",
  "name": "Karma Food Delivery Agent",
  "description": "AI-powered food ordering with Karma trust settlement",
  "agent_id": "agent_food_001",
  "icon_url": "https://karma-network.ai/agents/food/icon.png",
  "capabilities": ["order_food", "track_delivery", "karma_settle"],
  "endpoint": "https://karma-network.ai/a2a/agents/agent_food_001",
  "protocols": ["a2a", "mcp", "karma"],
  "skills": [
    {
      "id": "order_food",
      "name": "Order Food",
      "description": "Place food order from menu",
      "input_schema": {
        "type": "object",
        "properties": {
          "restaurant": {"type": "string"},
          "items": {"type": "array", "items": {"type": "string"}},
          "delivery_address": {"type": "string"}
        },
        "required": ["restaurant", "items"]
      },
      "output_schema": {
        "type": "object",
        "properties": {
          "order_id": {"type": "string"},
          "total": {"type": "number"},
          "estimated_time": {"type": "string"}
        }
      }
    }
  ],
  "karma": {
    "version": "0.1.0",
    "contract_address": "0x496d178a5D32E9410E52bD5800602BDEe81B2A91",
    "supports_voucher": true,
    "supports_evidence": true,
    "settlement_modes": ["bilateral", "escrow"],
    "accepted_tokens": ["USDC"],
    "network": "sepolia"
  }
}
```

Built dynamically by `card_builder.py` from Karma `/v1/agents` data + agent custom config.

## 4. A2A Bridge Service

**Location:** `packages/karma-a2a-bridge/`

### 4.1 File Structure

```
packages/karma-a2a-bridge/
├── pyproject.toml
├── main.py                    # FastAPI entry, mounts all routers
├── config.py                  # Registry URL, Karma API base, agent config
├── a2a_server.py              # A2A HTTP Server
│   ├── GET  /.well-known/agent-card.json   → Agent Card
│   └── POST /a2a/task         → Receive A2A Task
├── registry_client.py         # A2A Registry client
│   ├── register(card)         → Register Agent Card
│   ├── unregister(agent_id)   → Unregister
│   ├── search(capabilities)   → Search agents by capability
│   └── heartbeat(agent_id)    → Health heartbeat
├── card_builder.py            # Agent Card builder
│   ├── from_db(agent)         → Build from Karma /v1/agents
│   └── from_config(config)    → Build from local config
├── handoff_bridge.py          # A2A → Karma translation
│   ├── a2a_task_to_voucher()  → A2A result → Karma Voucher
│   ├── a2a_task_to_handoff()  → → handoff.json
│   └── evidence_chain()       → Cross-agent evidence chain
├── agent_sdk/                 # Lightweight pip-installable SDK
│   ├── karma_card.py          # Agent Card builder
│   ├── karma_registry.py      # Registry client (thin wrapper)
│   └── karma_a2a_client.py    # A2A Client for discovering others
└── tests/
    ├── test_card_builder.py
    ├── test_handoff_bridge.py
    ├── test_registry_client.py
    └── test_integration.py    # End-to-end: discover → negotiate → settle
```

### 4.2 API Endpoints

| Method | Path | Description |
|--------|------|-------------|
| GET | `/.well-known/agent-card.json` | Returns the agent's Agent Card |
| POST | `/a2a/task` | Receives A2A task (SendMessage/GetTask/Submit) |
| POST | `/a2a/task/{task_id}/cancel` | Cancel an A2A task |
| GET | `/a2a/task/{task_id}/status` | Get task status |

### 4.3 Configuration (config.py)

```python
REGISTRY_URL = "https://a2aregistry.org"  # or self-hosted
KARMA_API_BASE = "https://karma-network.ai"
KARMA_API_KEY = ""  # from env
AGENT_ID = "agent_food_001"
AGENT_NAME = "Karma Food Delivery Agent"
AGENT_CAPABILITIES = ["order_food", "track_delivery", "karma_settle"]
```

## 5. End-to-End Flow (Food Ordering Example)

```
Step 1: Discovery
  User Agent
  └─▶ registry_client.search(capabilities=["karma_settle", "order_food"])
      └─▶ A2A Registry
      ◀── Returns [Food Agent Card, ...]  ← endpoint, skills, karma ext

Step 2: Negotiation
  User Agent ── POST /a2a/task ──▶ Food Agent A2A Server
               { task_id, skill: "order_food", params: {...} }
  ◀── Returns { status: "negotiating", quote, voucher_required: true }
      Both sides agree on price, delivery, Karma settlement terms

Step 3: Create Karma Voucher
  Food Agent ──▶ handoff_bridge.a2a_task_to_voucher()
               └─▶ POST /v1/vouchers (Karma Core API)
               ◀── voucher_id, voucher_token
  Returns to User Agent: { status: "accepted", voucher_id, settlement_info }

Step 4: Execute
  User Agent executes via Karma MCP (OpenClaw/OpenManus) — existing flow
  Evidence Bundle uses existing Karma settlement flow

Step 5: Settle
  Existing Karma settlement flow (unchanged)
```

## 6. Backward Compatibility

- **Karma Core API:** No changes. All existing routes continue to work.
- **OpenClaw/OpenManus:** No changes. They still execute via MCP as before.
- **Karma Console:** No changes to existing pages. Agent management page can be extended with Agent Card preview (Phase 2).
- **Existing `/v1/agents`:** Continues to work. The A2A Bridge can optionally sync data from it.

## 7. Phased Implementation

### Phase 1 (2-3 weeks): Agent Card + A2A Server + Manual Registration

- [ ] Scaffold `packages/karma-a2a-bridge/` with FastAPI
- [ ] Implement `card_builder.py` — Agent Card generation
- [ ] Implement `a2a_server.py` — Agent Card endpoint and basic A2A Task handler
- [ ] Implement `handoff_bridge.py` — A2A → Karma Voucher translation
- [ ] Implement `agent_sdk/` — basic SDK for third-party agents
- [ ] Manual registration to a2aregistry.org
- [ ] Unit tests: card_builder, handoff_bridge

### Phase 2 (2 weeks): Auto-Registration + Registry Search + Karma Handoff

- [ ] Implement `registry_client.py` — auto register/unregister/heartbeat
- [ ] Implement `registry_client.search()` — capability-based search
- [ ] Full A2A Task negotiation (SendMessage/GetTask/Submit)
- [ ] Console integration: Agent Card preview in agents page
- [ ] Integration tests: discover → negotiate → settle
- [ ] Demo scenarios: food ordering, flight booking

### Phase 3 (optional): Self-Hosted Registry + Reputation

- [ ] Self-hosted Karma Agent Registry (FastAPI + PostgreSQL)
- [ ] Reputation filtering in search results
- [ ] Private registry support with OAuth
- [ ] Cross-agent evidence chain

## 8. Testing Strategy

| Test Type | Scope | Tools |
|-----------|-------|-------|
| Unit | card_builder, handoff_bridge transformation logic | pytest |
| Unit | registry_client (mocked HTTP) | pytest + responses |
| Integration | Full flow: discover → negotiate → voucher | pytest + docker |
| E2E | Two agents discovering and transacting | pytest + agent containers |

## 9. Open Questions

- Registry choice: use a2aregistry.org initially, design for self-hosted swap
- A2A Python SDK maturity: evaluate a2a-sdk vs a2a-python for protocol compliance
- Agent Card storage: Bridge-managed file vs DB-backed vs Karma API sync
