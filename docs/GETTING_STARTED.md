# Getting Started — 10 minutes to your first proof

This guide walks you through Karma's core proof primitives:
**Execution Receipt → Evidence Bundle → Verification**.

You'll need: Python 3.12+, a terminal, and 10 minutes.

---

## 1. Install

```bash
git clone https://github.com/AtoB101/Karma.git
cd Karma

python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev]"
```

## 2. Configure

```bash
cp deploy/.env.local-openclaw.example .env
# Edit .env — at minimum set APP_SECRET_KEY
python scripts/generate_keys.py
```

## 3. Start infrastructure

```bash
docker compose -f deploy/docker-compose.yml up -d postgres redis minio
alembic upgrade head
```

## 4. Start the API

```bash
uvicorn api.app:app --reload
# → http://127.0.0.1:8000
# → http://127.0.0.1:8000/docs
```

## 5. Generate your first Execution Receipt

```python
from sdk import KarmaClient

client = KarmaClient(
    agent_id="demo-worker-001",
    runtime_url="http://localhost:8000",
    api_key=***karma_***_***",
)

receipt = client.create_receipt(
    task_id="getting-started-001",
    tool_name="mcp.search",
    input_data={"query": "latest BTC price"},
    output_data={"result": "$67,420"},
    payment_ref={"type": "x402", "id": "pay_demo_001"},
)

print(f"Receipt: {receipt['receipt_id']}")
# → Receipt: rcp_...
```

## 6. Build an Evidence Bundle

```python
bundle = client.submit_evidence_bundle(
    task_id="getting-started-001",
    metadata={"purpose": "getting-started-demo"},
)

print(f"Bundle: {bundle['bundle_id']}")
# → Bundle: bun_...
```

## 7. Verify the proof

```python
result = client.verify(
    task_id="getting-started-001",
    bundle_id=bundle["bundle_id"],
)

print(f"Verification: {result['decision']}")
# → Verification: release
```

## 8. Run the full demo script

```bash
python examples/proof-layer-demo/run.py
```

Expected output:

```
task_id: task_demo_001
receipt_id: rcp_...
bundle_id: bun_...
verification: passed
```

---

## What you've built

You've just produced:

1. **Execution Receipt** — a signed record proving what tool was called, with what inputs, and what came back.
2. **Evidence Bundle** — a portable audit package wrapping receipts with context.
3. **Verification** — an API call that checks the proof passes structural rules.

These three primitives form Karma's proof layer. From here you can explore:

- **[Proof Primitives](./PROOF_LAYER.md)** — deeper dive on receipts, bundles, and verification
- **[Integrations](./INTEGRATIONS.md)** — x402, AP2, MCP, OpenClaw
- **[API Reference](./API_REFERENCE.md)** — full endpoint docs
- **[Advanced Workflows](./)** — settlement, dispute, decentralized verification (experimental)

---

## Next: OpenClaw MCP Plugin

If you're using OpenClaw, install the MCP proof plugin:

```bash
pip install -e ./packages/karma-openclaw
export KARMA_RUNTIME_URL=http://127.0.0.1:8000
export KARMA_API_KEY=***
karma-openclaw-mcp
```

See **[OpenClaw MCP Plugin](../packages/karma-openclaw/README.md)** for details.
