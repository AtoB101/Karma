# KARMA Console (public shell)

Static **operational shell** for Receiving, Payments, Agents, Evidence, and Disputes. It connects to the **Karma public API** (`GET /v1/capacity/{id}`, `GET /v1/settlement/{task_id}`) with optional `X-Karma-Api-Key` and a **multi-locale UI**.

The previous single-page **Cyber Console** (`pages/cyber/index.html` + `cyber-*.js`) has been archived under `legacy/apps/console/` and is no longer linked from the main navigation.

## Principles

- Marketing/brochure pages were removed; this console is the public web surface.
- **Console** is where Connect Wallet and bill/evidence/dispute UX live.
- API base / key / identity are stored in `localStorage` (dev convenience); do not use shared machines for production secrets.
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

Open `http://127.0.0.1:8787/apps/console/index.html`.

Ensure the Karma API allows **CORS** from your static origin (`CORS_ALLOW_ORIGINS` / dev `*`) or serve Console behind the same origin as the API.

## Karma BFF status (read-only, no secrets)

1. Start BFF (see `apps/karma_bff/README.md`).
2. Copy `config.example.js` → `config.js` and set `KARMA_API_BASE`, `KARMA_BFF_PUBLIC_BASE`, etc. For Bitpie connect, set the backend `WC_PROJECT_ID` env var (from https://cloud.walletconnect.com); the console reads it from `GET /v1/info`. Local static debug can override via `window.KARMA_WC_PROJECT_ID` in `config.js`.
3. Pages load `config.js` (optional, `onerror` safe) + bootstrap + BFF readonly panel for **GET `/public/status/:traceId`**.

Write operations (HMAC, OpenManus tools) stay **server-side** only.

Wallet / auth wiring for production deployments should land users in this Console after sign-in.
