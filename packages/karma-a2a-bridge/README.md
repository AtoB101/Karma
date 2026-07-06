# Karma A2A Bridge

A2A Agent-to-Agent Protocol discovery bridge for Karma Trust Protocol.
Enables agents to discover each other, negotiate tasks, and settle via Karma.

## Quick Start

```bash
pip install -e .
uvicorn main:app --reload --port 8080
```

## Components

- `a2a_server.py` — A2A HTTP Server (Agent Card + Task endpoints)
- `card_builder.py` — Dynamic Agent Card generation
- `handoff_bridge.py` — A2A Task → Karma Voucher translation
- `registry_client.py` — A2A Registry client
- `agent_sdk/` — Lightweight SDK for third-party agents
