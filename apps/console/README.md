# KARMA Console (public shell)

Static **operational shell** for Receiving, Payments, Agents, Evidence, and Disputes — plus **Cyber Console** (`pages/cyber/index.html`) which connects to the **Karma public API** (`GET /v1/capacity/{id}`, `GET /v1/settlement/{task_id}`) with optional `X-Karma-Api-Key` and **8-locale UI** (zh-CN, en, ja, ko, es, fr, de, pt-BR).

## Principles

- **Website** (`apps/website`) does not connect wallets.  
- **Console** is where Connect Wallet and bill/evidence/dispute UX live.  
- **Cyber Console** stores API base / key / identity in `localStorage` (dev convenience); do not use shared machines for production secrets.
- Production may host Console at `https://app.karma-network.ai` with `/console` rewrites.

## Preview

```bash
python3 -m http.server 8787
```

Open `http://127.0.0.1:8787/apps/console/index.html` or **`http://127.0.0.1:8787/apps/console/pages/cyber/index.html`**.

Ensure the Karma API allows **CORS** from your static origin (`CORS_ALLOW_ORIGINS` / dev `*`) or serve Console behind the same origin as the API.

## Karma BFF status (read-only, no secrets)

1. Start BFF (see `apps/karma_bff/README.md`).
2. Copy `config.example.js` → `config.js` and set `window.KARMA_BFF_PUBLIC_BASE` to the BFF origin (e.g. `http://127.0.0.1:8820`).
3. Receiving / Payments pages load `config.js` (optional) + `scripts/karma-bff-readonly.js` and show **GET `/public/status/:traceId`** + link to **买家锁仓说明页**.

Write operations (HMAC, OpenManus tools) stay **server-side** only.

For WalletConnect-based sign-in (demo), the repository also ships `apps/agent-service-guard/frontend/web3-login.html` — wire your deployment to land users in Console after auth.
