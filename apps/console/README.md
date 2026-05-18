# KARMA Console (public shell)

Static **operational shell** for Receiving, Payments, Agents, Evidence, and Disputes — plus **Cyber Console** (`pages/cyber/index.html`) which connects to the **Karma public API** (`GET /v1/capacity/{id}`, `GET /v1/settlement/{task_id}`) with optional `X-Karma-Api-Key` and **8-locale UI** (zh-CN, en, ja, ko, es, fr, de, pt-BR).

## Principles

- **Website** (`apps/website`) does not connect wallets.  
- **Console** is where Connect Wallet and bill/evidence/dispute UX live.  
- **Cyber Console** stores API base / key / identity in `localStorage` (dev convenience); do not use shared machines for production secrets.
- Production may host Console at `https://app.karma-network.ai` with `/console` rewrites.

## Last mile (live API)

Payments / Receiving / Trade pages call the real Karma API via `scripts/karma-public-api.js` and `scripts/console-actions.js` (settlement, capacity, payment codes). See **`docs/public-testing/CONSOLE_LAST_MILE-zh.md`**.

```bash
cp apps/console/config.example.js apps/console/config.js   # set KARMA_API_BASE + optional BFF
bash scripts/acceptance/console_last_mile_gate.sh
```

## Preview

```bash
python3 -m http.server 8787
```

Open `http://127.0.0.1:8787/apps/console/index.html` or **`http://127.0.0.1:8787/apps/console/pages/cyber/index.html`**.

Ensure the Karma API allows **CORS** from your static origin (`CORS_ALLOW_ORIGINS` / dev `*`) or serve Console behind the same origin as the API.

## Karma BFF status (read-only, no secrets)

1. Start BFF (see `apps/karma_bff/README.md`).
2. Copy `config.example.js` → `config.js` and set `KARMA_API_BASE`, `KARMA_BFF_PUBLIC_BASE`, etc.
3. Pages load `config.js` (optional, `onerror` safe) + bootstrap + BFF readonly panel for **GET `/public/status/:traceId`**.

Write operations (HMAC, OpenManus tools) stay **server-side** only.

For WalletConnect-based sign-in (demo), the repository also ships `apps/agent-service-guard/frontend/web3-login.html` — wire your deployment to land users in Console after auth.
