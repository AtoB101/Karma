# KARMA Console (public shell)

The public web surface of Karma is the **Cyber Console** — a single static page at
`apps/console/pages/cyber/index.html` that talks to the Karma public API
(`GET /v1/capacity/{id}`, `GET /v1/settlement/{task_id}`, `GET /health`) with an
optional `X-Karma-Api-Key` and a **6-locale UI** (zh-CN, en, ja, ko, es-AR, es-SV), plus a
**node layer** that lets the user choose which node it reads from.

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
- **Which node it talks to is the user's choice, not ours.** The top-bar node chip
  switches between the built-in bootstrap nodes and any node the user adds, probes
  `GET /health`, and can fail over automatically. The selection lives in
  `localStorage["karma_cyber_api_base"]` — still one key, so nothing else had to change.
- **Everything handed to an agent points at the selected node.** The handoff env file
  and the SFK env both resolve `KARMA_RUNTIME_URL` through the node layer; there is no
  hard-coded vendor domain left in either path.
- **Every request has a deadline.** A node that accepts the connection and then never
  answers used to freeze the whole console (the UI just spun). `karmaFetch` now carries
  a 15 s `AbortSignal.timeout`, and a timeout takes the same path as "cannot connect" —
  a visible failure plus a report to the node layer, so failover can act.
- **The phrase packs are fetched, not script-tagged.** Under same-origin connection
  pressure the browser parks dynamically inserted `<script>` at low priority and a
  ~250 KB pack can hang for tens of seconds; the same URL via `fetch` came back in ~1 s
  (measured in production). Failed loads are no longer remembered, and one retry with a
  cache-busting query follows.

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
scripts/karma-nodes.js        node registry, health probing, failover (no DOM)
scripts/cyber-node-panel.js   node chip + dropdown + settings card (DOM only)
scripts/cyber-globe-bg.js      background canvas
scripts/i18n-cyber.js          6-locale strings
scripts/i18n-phrase/*.js       per-locale phrase packs (whole-sentence lookup)
styles/cyber-console.css       styles
```

## Self-host / pick your node

The console is a static directory with no build step, so it can be served from anywhere.

```bash
python3 scripts/console_bundle.py build --src apps/console --out dist/console
python3 scripts/console_bundle.py verify --dir dist/console
python3 -m http.server 8787 --directory dist/console
```

After a deploy, check that what is actually being served is your source:

```bash
python3 scripts/console_bundle.py remote --src apps/console --base https://karma-network.ai/console/
```

Open `http://127.0.0.1:8787/pages/cyber/index.html`, then use the node chip to add and
switch to your own node. A node qualifies when `GET <base>/health` returns
`{"status":"ok", ...}` and it allows this origin (`CORS_ALLOW_ORIGINS`), or when it is
served same-origin behind a reverse proxy (preferred).

See `docs/DECENTRALIZED_CONSOLE_V1.md` for the distribution model, the IPFS/DNSLink
publishing path, and an honest list of what is *still* centralised.

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

The gate also runs the behaviour suites:

- `tests/js/test_karma_nodes.cjs` — 53 checks against the real `karma-nodes.js`
- `tests/js/test_console_fetch.cjs` — request deadlines: a request that never answers
  must be aborted and reported, not left spinning
- `tests/playwright/console_nodes_live.cjs` — 45 checks in a real browser, including a
  phrase pack that returns 503 on the first request and must still land on the retry
  (needs `playwright`; skipped when it is not installed)

To exercise a deployed site:

```bash
python3 scripts/console_bundle.py remote --src apps/console --base https://<your-host>/console/
KARMA_PROD_URL=https://<your-host>/console/pages/cyber/index.html \
  node tests/playwright/console_nodes_prod.cjs
```
