# Karma Guard — Acceptance (single portal + studio)

## Portal (`frontend/index.html`)

- [ ] Page loads with KARMA//PAY branding and sections (problem / trust / flow / FAQ).
- [ ] Language switcher changes visible copy (en/zh at minimum).
- [ ] **Sign in** and **Open user studio** link to `web3-login.html?target=studio%2Findex.html`.
- [ ] Login modal opens; QR targets full sign-in URL; mnemonic path accepts 12 words and redirects to Studio when valid (demo).

## Sign-in (`frontend/web3-login.html`)

- [ ] With no `public-config.json` and `wc-config.js` **empty**: page shows clear “configure project id” message (no crash).
- [ ] With valid `public-config.json` **or** `wc-config.js` id: QR appears; after wallet connect + signature, browser lands on `studio/index.html` with session in **`sessionStorage.karma_web3_session`** (tab-scoped).
- [ ] **Home** returns to portal.

## Studio (`frontend/studio/`)

- [ ] Without session: redirect to `web3-login.html?target=studio%2Findex.html`.
- [ ] With session: dashboard and nav render; **Sign out** clears session and returns to sign-in.
- [ ] Create Agent produces `shareLink` pointing at `../index.html?agent=...` (portal deep link placeholder).

## Deploy

- [ ] Static host serves `frontend/` as one tree; HTTPS in production.
- [ ] `public-config.json` generated on server (e.g. `./scripts/deploy/write-agent-guard-public-config.sh`) and **not** committed; or dev-only `wc-config.js` override.
