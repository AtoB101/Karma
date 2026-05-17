# karma-openmanus

Python integration package for **OpenManus (or any orchestrator)** calling the **Karma BFF** integration API with the HMAC contract from `docs/KARMA_BFF_OPENMANUS_INTEGRATION.md`.

This is **not** a vendored OpenManus runtime — it is a **small HTTP client** you install next to your OpenManus server and use from tool handlers.

## Install

```bash
pip install ./packages/karma-openmanus
# or from repo root:
pip install -e ./packages/karma-openmanus
```

## Environment

| Variable | Meaning |
|----------|---------|
| `KARMA_BFF_URL` | Base URL of Karma BFF (no trailing slash), e.g. `https://bff.example.com` |
| `BFF_INTEGRATION_SECRET` | Shared secret for HMAC-SHA256 signing |

## Usage

```python
import os
from karma_openmanus import KarmaBffClient

async def main():
    client = KarmaBffClient.from_env()
    trace_id = "trace-demo-001"
    out = await client.create_task(
        {"trace_id": trace_id, "title": "Demo"},
        idempotency_key="idem-create-1",
    )
    status = await client.get_task_status(trace_id)
    print(out, status)

# asyncio.run(main())
```

Tool names and paths follow `packages/openmanus-karma-tools/tools.json` (also bundled under `karma_openmanus/data/tools.json` for offline reference).

## Direct Runtime API (phase 1 trade / payment codes)

When OpenManus should call the **main Karma API** (not BFF integration state):

```python
from karma_openmanus import KarmaRuntimeClient

client = KarmaRuntimeClient.from_env()  # KARMA_RUNTIME_URL + KARMA_API_KEY
order = await client.launch_trade_order(
    buyer_identity_id="buyer-1",
    seller_identity_id="seller-1",
    requirement_text="caption 任务 15 USDC",
    idempotency_key="manus-order-001",
    task_type="api.caption",
)
status = await client.get_trade_order(order["order_id"])
```

Tool manifest for orchestrator registration: `karma_openmanus/data/runtime_tools.json`.

**Acceptance checklist:** `docs/PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md`

## Security

- Read secrets **only** from the OpenManus **server** environment — never from end-user chat.
- Respect BFF state machine: heavy execution only after `EXECUTE_ALLOWED` (see integration doc).
