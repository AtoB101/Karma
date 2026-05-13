# Karma Trust Protocol — Public SDK & API

Build verifiable AI agents. Every tool call generates a signed receipt. Every task produces an auditable evidence bundle. Settlement is automatic.

---

## Quick Start

### 1. Install

```bash
git clone https://github.com/your-org/karma-public.git
cd karma-public

pip install -e ".[dev]"
```

### 2. Configure

```bash
cp .env.example .env
# Edit .env — at minimum set APP_SECRET_KEY and PRIVATE_RUNTIME_API_KEY
```

### 3. Generate signing keys

```bash
python scripts/generate_keys.py
```

### 4. Start infrastructure (PostgreSQL, Redis, MinIO)

```bash
docker compose -f deploy/docker-compose.yml up -d postgres redis minio
```

### 5. Run database migrations

```bash
alembic upgrade head
```

### 6. Seed demo data (optional)

```bash
python scripts/seed_demo_data.py
```

### 7. Start the API

```bash
uvicorn api.app:app --reload
# API: http://localhost:8000
# Docs: http://localhost:8000/docs
```

### 8. Start Celery worker (separate terminal)

```bash
celery -A worker.tasks worker --loglevel=info -Q verification,settlement,reputation
```

### 9. Start full stack via Docker

```bash
docker compose -f deploy/docker-compose.yml up
```

---

## Run Tests

```bash
pytest                          # all tests
pytest tests/unit/              # unit tests only
pytest tests/integration/       # integration tests only
pytest -v --cov=. --cov-report=term-missing
```

---

## Run Demo

```bash
python examples/demo_captioning.py
```

---

## SDK Usage

```python
from sdk import KarmaClient
from sdk.task import TaskRunner

client = KarmaClient(
    agent_id="worker-001",
    runtime_url="http://localhost:8000",
    api_key="karma_worker-001_secret",
)

async def my_task(contract, client):
    runner = TaskRunner(contract, client)
    result = await runner.call("caption.generate", my_caption_fn, {"url": "..."})
    return runner.results()

result = await client.run_task(contract, my_task)
```

P0 helpers on `KarmaClient` include `lock_usdc`, `get_capacity`, `create_voucher`, `verify_voucher`, `accept_voucher`, `accept_task` (settlement create → pending → lock), and `submit_execution_receipt`. P1 adds optional `extension` on `run_tool` / hook layer (api / mcp / agent templates) plus `sdk/execution_receipt_helpers.py` for digest construction. Progress path: optional `progress_confirm_require_buyer_actor`, partial settlement capped to confirmed claimed value when confirmations exist, and `timeout_confirm_stale_progress` on the HTTP/SDK surface. TypeScript mirror: `packages/sdk` (`npm run build`, `npm run test` for Vitest fetch-URL smoke checks) with `apiExecutionExtensionFromHashes` and related builders. **P2 (public surface):** `POST /v1/settlement/{taskId}/auto-arbitrate` uses `services/auto_arbitration_rules.py` (delivery timeout, receipt success, evidence-bundle id order, step metadata, per-receipt hash recomputation); decentralized arbitration pool and case flow live under `api/routes/arbitration.py`; multi-agent path features under `services/responsibility_graph.py`; sub-identities and `rotate-display-id` under `api/routes/identities.py`. TypeScript `KarmaPublicSdk` now mirrors settlement start/submit/dispute/partial/regret/auto-arbitrate, progress CRUD, and evidence bundle submit/fetch (`submitEvidenceBundle`, `getEvidenceBundle`, `getEvidenceBundleByTask`) (`packages/sdk`, `npm run build`). OpenAPI documents `POST/GET /v1/bundles` and related paths. Optional voucher EIP-712 enforcement: environment `VOUCHER_REQUIRE_EIP712=true` plus `buyer_wallet_address` on `POST /v1/vouchers` (see `services/voucher_eip712.py`). Isolated operational UI demo: `examples/p0-buyer-seller-console.html`.

---

## Project Layout

```
karma-public/
├── api/                  FastAPI routes + middleware
├── agents/               OpenManus + LangGraph adapters
├── core/                 Schemas, hooks, evidence builder, interfaces
├── db/                   ORM models, migrations, stores (PG + Redis)
├── sdk/                  High-level SDK client
├── services/             Signing service, MinIO object store
├── worker/               Celery tasks
├── scripts/              init_db, seed, generate_keys
├── tests/                Unit + integration tests
├── deploy/               Dockerfile, docker-compose, Prometheus config
└── docs/                 API reference, deployment SOP
```

---

## Docs

- [API Reference](docs/API_REFERENCE.md)
- [Deployment SOP](docs/DEPLOYMENT.md)
- [Karma FINAL V1.0 Engineering Kickoff (CN)](docs/KARMA_FINAL_V1_ENGINEERING_KICKOFF_CN.md)
- [Execution Receipt Standard](docs/EXECUTION_RECEIPT_STANDARD.md)
- [Public 12 Deliverables (CN)](docs/PUBLIC_12_DELIVERABLES_CN.md)
- [Public P0 Acceptance Runbook (CN)](docs/PUBLIC_P0_ACCEPTANCE_RUNBOOK_CN.md)

---

## Architecture

```
Your Agent
    ↓
KarmaHookLayer          ← wraps every tool call, generates signed receipts
    ↓
EvidenceBundleBuilder   ← aggregates receipts into proof package
    ↓
POST /v1/verify         ← public API forwards to private runtime
    ↓
Private Runtime         ← verification + fraud + behavior + risk (internal)
    ↓
Settlement              ← escrow released / refunded / disputed
    ↓
Reputation              ← agent scores updated
```

The verification decision logic, fraud detection rules, and reputation scoring weights live in the **private runtime** and are never exposed here.

---

## License

Apache 2.0

---

## Testnet Settlement

The Karma runtime integrates with the **existing** Karma smart contracts:
- `KarmaSettlementEngine` — EIP-712 quote + `submitSettlement()` (legacy)
- `KarmaNonCustodial` — batch + bill model (M2.0)

### Configure

```bash
cp .env.testnet.example .env
# Edit .env:
#   SETTLEMENT_MODE=testnet
#   TESTNET_RPC_URL=https://sepolia.infura.io/v3/YOUR_KEY
#   TESTNET_CHAIN_ID=11155111
#   TESTNET_PRIVATE_KEY=0x...  (testnet-only wallet, never mainnet)
#   KARMA_ENGINE_ADDRESS=0x...
#   ERC20_TOKEN_ADDRESS=0x...
#   PAYEE_ADDRESS=0x...
```

### Run migration (adds on-chain fields)

```bash
alembic upgrade head
```

### Pre-flight check (balance, allowance, nonce)

```bash
python scripts/testnet/testnet_lock.py --task-id my-task-001 --amount 100
```

### Compute evidence bundle hash

```bash
python scripts/testnet/testnet_submit_evidence.py --task-id my-task-001 --bundle-id my-bundle-001
```

### Submit on-chain release

```bash
python scripts/testnet/testnet_release.py --task-id my-task-001 --amount 100
```

### Record off-chain refund (no chain tx — contract has no refund method)

```bash
python scripts/testnet/testnet_refund.py --task-id my-task-001
```

### Record off-chain dispute

```bash
python scripts/testnet/testnet_dispute.py --task-id my-task-001 --bundle-hash 0x...
```

### Full end-to-end testnet flow

```bash
python scripts/testnet/testnet_full_flow.py --amount 100
```

### Settlement mode switching

```bash
# .env
SETTLEMENT_MODE=offchain   # default — database only
SETTLEMENT_MODE=testnet    # full on-chain via existing Karma contracts
SETTLEMENT_MODE=hybrid     # off-chain receipts/verify, on-chain payment only
```

### Runtime security

See `docs/SECURITY_AUDIT_2026.md` for the audit summary and configuration checklist. When `AUTH_ENFORCE_PROTECTED_ROUTES` is enabled together with `SETTLEMENT_REQUIRE_PARTY_ACTOR` (default **true**), settlement and progress mutations bind to the **buyer** or **worker** identity so arbitrary API keys cannot drive another party’s task rules. With **`LEDGER_REQUIRE_PARTY_ACTOR`** (default **true**), **capacity** lock/release and **voucher** create/verify/accept bind to the asserted ledger identities.

### On-chain fields in API response

After testnet settlement, `GET /v1/settlement/{task_id}` returns:

```json
{
  "status": "released",
  "settlement_mode": "testnet",
  "chain_id": 11155111,
  "contract_address": "0x...",
  "tx_hash": "0x...",
  "evidence_bundle_hash": "0x...",
  "onchain_status": "confirmed",
  "quote_id": "0x..."
}
```

### Contract architecture note

The existing `KarmaSettlementEngine` has **no on-chain refund or dispute methods**.
- **Release** → `submitSettlement()` called on-chain, tokens transferred payer→payee
- **Refund/Dispute** → off-chain decision only; `submitSettlement()` never called, funds stay with payer
- **Evidence hash** → embedded in `scopeHash` field of EIP-712 Quote for on-chain auditability
