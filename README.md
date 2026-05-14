# Karma Trust Protocol — Public SDK & API

Build verifiable AI agents. Every tool call generates a signed receipt. Every task produces an auditable evidence bundle. Settlement is automatic.

**Early builders:** we are recruiting **core developers** (≈10 roles), **security researchers**, and **ecosystem advocates** (≈20) for the pre-token phase. Incentive design (including potential future token mechanisms and early **equity-like** arrangements) will follow formal governance and legal processes. **→ [Read the full public brief (中文)](docs/early-builders-recruitment-zh.md)**

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

## One-click deploy (PaaS)

Pre-configured paths for **Railway**, **Fly.io**, and **Vercel** (static marketing site):

- `railway.toml` + `deploy/Dockerfile.paas` — API container, `/health`, `alembic` pre-deploy
- `fly.toml` — Fly Machines + `release_command` migrations
- `apps/website/vercel.json` — optional headers for the static site

| | |
|--|--|
| **Railway** (API) | [![Deploy on Railway](https://railway.com/button.svg)](https://railway.com/new/github?repositories[]=https://github.com/AtoB101/Karma) |
| **Fly.io** (API) | [![Deploy to Fly.io](https://fly.io/button.svg)](https://fly.io/launch?template=https://github.com/AtoB101/Karma) |
| **Vercel** (`apps/website`) | [![Deploy with Vercel](https://vercel.com/button)](https://vercel.com/new/clone?repository-url=https%3A%2F%2Fgithub.com%2FAtoB101%2FKarma&root-directory=apps%2Fwebsite) |

Full checklist (env vars, Postgres/Redis, post-click steps): **[`deploy/one-click-deploy.md`](deploy/one-click-deploy.md)**.

---

## Run Tests

```bash
pytest tests/                    # all Python tests (unit + integration + trusted_agent, etc.)
pytest tests/unit/               # unit tests only
pytest tests/integration/        # integration + E2E (incl. test_runtime_e2e.py)
pytest tests/integration/test_runtime_e2e.py -v   # Runtime Key /runtime acceptance only
pytest -v --cov=. --cov-report=term-missing
make test-python                 # pip install -e ".[dev]" then pytest tests/
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

P0 helpers on `KarmaClient` include `lock_usdc`, `get_capacity`, `create_voucher`, `verify_voucher`, `accept_voucher`, `accept_task` (settlement create → pending → lock), and `submit_execution_receipt`. Evidence bundle helpers: `submit_evidence_bundle`, `get_evidence_bundle`, `get_evidence_bundle_by_task` (`GET` uses URL-encoded segments, matching `KarmaPublicSdk`'s `submitEvidenceBundle`, `getEvidenceBundle`, and `getEvidenceBundleByTask`). P1 adds optional `extension` on `run_tool` / hook layer (api / mcp / agent templates) plus `sdk/execution_receipt_helpers.py` for digest construction. Progress path: optional `progress_confirm_require_buyer_actor`, partial settlement capped to confirmed claimed value when confirmations exist, and `timeout_confirm_stale_progress` on the HTTP/SDK surface. TypeScript mirror: `packages/sdk` (`npm run build`; `npm run test` runs Vitest fetch-URL smoke checks) exposes settlement start/submit/dispute/partial/regret/auto-arbitrate, progress CRUD, evidence bundle POST/GET, and `apiExecutionExtensionFromHashes` plus related builders. OpenAPI documents `POST`/`GET /v1/bundles` and related paths (`openapi/karma-v1.yaml`). **P2 (public surface):** `POST /v1/settlement/{taskId}/auto-arbitrate` uses `services/auto_arbitration_rules.py` (delivery timeout, receipt success, evidence-bundle id order, step metadata, per-receipt hash recomputation); decentralized arbitration pool and case flow live under `api/routes/arbitration.py`; multi-agent path features under `services/responsibility_graph.py`; sub-identities and `rotate-display-id` under `api/routes/identities.py`. Optional voucher EIP-712 enforcement: environment `VOUCHER_REQUIRE_EIP712=true` plus `buyer_wallet_address` on `POST /v1/vouchers` (see `services/voucher_eip712.py`). Isolated operational UI demo: `examples/p0-buyer-seller-console.html`.

### OpenManus / OpenClaw installable bridges

| Package | Purpose |
|---------|---------|
| [`packages/karma-openmanus`](packages/karma-openmanus/) | `pip install ./packages/karma-openmanus` — async **HMAC client** for Karma **BFF** `/v1/integration/*` (matches `packages/openmanus-karma-tools/tools.json`). |
| [`packages/karma-openclaw`](packages/karma-openclaw/) | `pip install ./packages/karma-openclaw` — **stdio MCP** server (`karma-openclaw-mcp`) exposing selected **`/v1/*`** tools for [OpenClaw](https://github.com/openclaw/openclaw) MCP bridge. |

In-process signed tool calls without BFF: `agents/openmanus/adapter.py` + `KarmaHookLayer` / `KarmaClient` (see examples above).

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
├── packages/             TypeScript SDK, OpenManus tools spec, karma-openmanus, karma-openclaw
├── worker/               Celery tasks
├── scripts/              init_db, seed, generate_keys
├── tests/                Unit + integration tests
├── deploy/               Dockerfile(s), docker-compose, Prometheus, PaaS (`Dockerfile.paas`, `one-click-deploy.md`)
├── railway.toml          Railway config-as-code (API)
├── fly.toml              Fly.io template (API)
└── docs/                 API reference, deployment SOP
```

---

## Docs

- [**公开测试计划（模拟 / 攻击测试 / 测试网）— 索引**](docs/public-testing/README.md)
- [API Reference](docs/API_REFERENCE.md)
- [Deployment SOP](docs/DEPLOYMENT.md)
- [**One-click deploy — Railway / Fly.io / Vercel**](deploy/one-click-deploy.md)
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
