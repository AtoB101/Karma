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
2. **WalletConnect project id (recommended):** generate `public-config.json` on the host or in CI so it is **not** committed to git (see `public-config.json.example`; real file is gitignored).

   ```bash
   export WALLETCONNECT_PROJECT_ID="your_id_from_https://cloud.walletconnect.com"
   ./scripts/deploy/write-agent-guard-public-config.sh
   ```

   On load, `web3-login.html` fetches `./public-config.json` and applies `walletConnectProjectId` before starting pairing.

3. **Optional local override:** keep `wc-config.js` for dev machines; if both exist, **`public-config.json` wins** when it contains a non-empty id.

4. HTTPS in production (WalletConnect expects a real origin).

5. Confirm the browser can load `wc-config.js`, optional `public-config.json`, `favicon.svg`, and ESM CDNs.

## API / contracts

- `api/public-interfaces.json` — reserved private-engine shapes (risk/dispute/score placeholders)
- `api/README.md` — integration notes
- `docs/integration-guide.md` — public integration narrative
- `docs/agent-service-guard-changelog.md` — payload contract changelog

## Private engine boundary

Public repo documents interfaces only. Reserved endpoint names (`/risk/check`, etc.) are implemented in the private engine.
