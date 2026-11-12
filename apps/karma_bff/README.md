# Karma BFF — secure bridge (OpenManus ↔ Karma)

Thin **Backend-for-OpenManus** service:

- **HMAC** integration auth (`X-Karma-Timestamp` + `X-Karma-Signature`).
- **Idempotency-Key** on mutating routes.
- **SQLite** task state + receipts (dev default; use Postgres in production).
- **No private keys** in this service for buyer/seller; chain txs remain wallet-side or indexer-driven webhooks.

## Run locally

```bash
cd /workspace
python3 -m venv .venv-bff && . .venv-bff/bin/activate
pip install -r requirements-bff.txt
export BFF_INTEGRATION_SECRET="change-me-in-production-min-32-chars!!"
export BFF_DATABASE_PATH="/tmp/karma_bff.db"
PYTHONPATH=/workspace uvicorn apps.karma_bff.app.main:app --host 127.0.0.1 --port 8820 --reload
```

- Health: `GET http://127.0.0.1:8820/health`
- OpenManus (server): `POST /v1/integration/...` with HMAC headers (see `docs/KARMA_BFF_OPENMANUS_INTEGRATION.md`).
- Buyer lock **info page** (human-readable): `GET /public/lock/{trace_id}`

## Docker

```bash
docker compose -f docker/docker-compose.karma-bff.yml up --build
```

## Security

- Rotate `BFF_INTEGRATION_SECRET`; never commit real values.
- In production: **TLS**, bind to private network, mTLS optional.
- Webhook `POST /v1/webhooks/chain` must use the same HMAC secret (or separate `BFF_WEBHOOK_SECRET`).
