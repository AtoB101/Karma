# KARMA Console (public shell)

The public web surface of Karma is the **Cyber Console** — a single static page at
`apps/console/pages/cyber/index.html` that talks to the Karma public API
(`GET /v1/capacity/{id}`, `GET /v1/settlement/{task_id}`, `GET /health`) with an
optional `X-Karma-Api-Key` and an **8-locale UI** (zh-CN, en, ja, ko, es, fr, de, pt-BR).

`apps/console/index.html` is a redirect stub to that page, so `/console/` and the
GitHub Pages root keep working.

## Principles

- The legacy multi-page console (Receiving / Payments / Agents / Evidence / Disputes /
  Trade / Dashboard / MVVS / Verifier Explorer / OpenClaw Connect) has been removed.
  `pages/cyber/` is now the only console UI.
- The Cyber Console stores API base / key / identity in `localStorage` (dev
  convenience); do not use shared machines for production secrets.
- API base resolution: unset means local dev (`http://127.0.0.1:8000`), an explicitly
  empty string means **same origin** (production reverse proxy). See
  `scripts/karma-public-api.js` (`karmaResolveApiBase`).

## Files

```
index.html                     redirect stub -> pages/cyber/index.html
pages/cyber/index.html         the console
scripts/karma-public-api.js    API client (karmaResolveApiBase, settlement/trade helpers)
scripts/cyber-console.js       page bootstrap + API base display
scripts/cyber-actions.js       action handlers
scripts/cyber-identity.js      identity / profile handling
scripts/console-sync.js        state polling
scripts/console-wallet-auth.js wallet auth (SIWE)
scripts/cyber-globe-bg.js      background canvas
scripts/i18n-cyber.js          8-locale strings
styles/cyber-console.css       styles
```

## Preview

```bash
python3 -m http.server 8787
```

Open `http://127.0.0.1:8787/apps/console/pages/cyber/index.html`.

Ensure the Karma API allows **CORS** from your static origin (`CORS_ALLOW_ORIGINS`)
or serve the console behind the same origin as the API.

## Gate

```bash
bash scripts/acceptance/console_last_mile_gate.sh
```
