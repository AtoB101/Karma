# Portal Go-Live Runbook V1

Goal: launch the Karma portal in a runnable state for users.

## 1) Start portal service

```bash
cd karma-engine/internal-admin/mvp
./start-portal-live.sh
```

Default URL:
- `http://127.0.0.1:8822/`

Notes:
- If chain env is missing, dashboard APIs still work.
- Chain-required paid call endpoint (`/api/price-paid`) will report `CHAIN_DISABLED` until env is provided.

## 2) Run go-live checks

```bash
cd karma-engine/internal-admin/mvp
./portal-go-live-check.sh
```

This checks:
- portal root responds
- dashboard API responds
- deploy-readiness API responds
- create agent path
- bill transition path
- allowance update path

Expected final output:
- `portal go-live checks passed`

## 3) Optional public temporary URL

Use your own tunnel/provider to expose `:8822` externally for temporary QA.

## 4) Production criteria

Mandatory before declaring production-ready:
- replace in-memory state with persistent storage
- enable authenticated access control
- enable audited chain env for paid settlement
- define backup/restore and monitoring policies

