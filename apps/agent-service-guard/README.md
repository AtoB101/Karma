# Karma Guard — Agent Service Portal (Public)

Single static **portal** plus **wallet sign-in** and **Agent Studio**. Optimized for daily deploy: one directory tree, consistent paths, no duplicate marketing pages.

## What ships in `frontend/`

| Path | Purpose |
|------|---------|
| `index.html` | Public portal (product narrative, FAQ, deploy CTA) |
| `web3-login.html` | WalletConnect QR + mnemonic path → session → redirect to Studio |
| `wc-config.js` | Set `window.KARMAPAY_WC_PROJECT_ID` (WalletConnect Cloud) before production |
| `favicon.svg` | Site icon |
| `studio/` | User Studio (requires `karma_web3_session` from sign-in) |

**Flow:** `index.html` → `web3-login.html?target=studio%2Findex.html` → `studio/index.html`

## Run locally

From repository root:

```bash
python3 -m http.server 8790
```

Open:

- Portal: `http://127.0.0.1:8790/apps/agent-service-guard/frontend/index.html`
- Sign-in: `http://127.0.0.1:8790/apps/agent-service-guard/frontend/web3-login.html`
- Studio: `http://127.0.0.1:8790/apps/agent-service-guard/frontend/studio/index.html` (redirects to sign-in if no session)

### Smoke

```bash
python3 ./scripts/agent-service-guard-smoke.py
npm install && npm run test:agent-guard
```

### Phase 2 contract gate

```bash
python3 scripts/phase2-public-contract-gate.py
```

## Deploy checklist (server)

1. Serve `apps/agent-service-guard/frontend/` as static files (same origin for portal, login, studio).
2. Edit `wc-config.js` and set `KARMAPAY_WC_PROJECT_ID` to your [WalletConnect Cloud](https://cloud.walletconnect.com) project id.
3. HTTPS required for WalletConnect in production.
4. Confirm `web3-login.html` can load `wc-config.js`, `favicon.svg`, and ESM CDNs from the browser.

## API / contracts

- `api/public-interfaces.json` — reserved private-engine shapes (risk/dispute/score placeholders)
- `api/README.md` — integration notes
- `docs/integration-guide.md` — public integration narrative
- `docs/agent-service-guard-changelog.md` — payload contract changelog

## Private engine boundary

Public repo documents interfaces only. Reserved endpoint names (`/risk/check`, etc.) are implemented in the private engine.
