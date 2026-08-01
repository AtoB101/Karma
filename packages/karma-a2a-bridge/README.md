# Karma A2A Bridge

A2A Agent-to-Agent Protocol discovery bridge for Karma Trust Protocol.
Enables agents to discover each other, negotiate tasks, and settle via Karma.

## Quick Start

```bash
pip install -e ".[dev]"
uvicorn main:app --reload --port 8080
```

## Security & identity (2026-08)

1. **EIP-712 on all write ops** — `POST /a2a/task`, confirm/submit/cancel/handoff require
   `auth` (`agent`, `signature`, `nonce`, `deadline`) using domain `KarmaA2A` / type `A2ATaskOp`
   (same EIP-712 encoding style as on-chain Karma auth). Set `A2A_REQUIRE_EIP712=0` only for local demos.
2. **DID SSOT** — set `A2A_DID_AGENT_ADDRESS` (+ optional `A2A_ON_CHAIN_DID`).
   `AgentCard.agent_id` becomes `did:karma:0x…` (read-only projection of on-chain DID).
3. **Event-sourced tasks** — `_task_store` replaced by SQLite event log
   (`A2A_TASK_STORE_PATH`, default `data/a2a_tasks.sqlite3`). `GET /a2a/task/{id}/events` exposes the log.
4. **Attestation discovery** — AgentCard may advertise `karma_attestation` plus
   `karma.verifier_registry` / `karma.attestation_gateway` **addresses**.
   Privileged methods `recordAttestation` / `rewardVerifier` are **not** published as skills;
   on-chain they are restricted to authorized Gateway callers.

## Components

- `a2a_server.py` — A2A HTTP Server (Agent Card + Task endpoints)
- `eip712_auth.py` — EIP-712 typed-data sign/verify for write ops
- `task_store.py` — Persistent event-sourced task store
- `identity.py` — DID → agent_id projection helpers
- `card_builder.py` — Dynamic Agent Card generation
- `handoff_bridge.py` — A2A Task → Karma Voucher translation
- `registry_client.py` — A2A Registry client
- `agent_sdk/` — Lightweight SDK for third-party agents
