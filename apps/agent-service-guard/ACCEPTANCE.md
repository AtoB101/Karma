# Karma Guard — Acceptance (single portal + studio)

## Portal (`frontend/index.html`)

- [ ] Page loads with KARMA//PAY branding and sections (problem / trust / flow / FAQ).
- [ ] Language switcher changes visible copy (en/zh at minimum).
- [ ] Loads **`landing.js`** with **`integrity="sha384-..."`** + portal **CSP meta** (`connect-src 'none'`).
- [ ] **Sign in** and **Open Agent Studio** link to `web3-login.html?target=studio%2Findex.html`.
- [ ] Portal does **not** embed wallet QR, WalletConnect, or mnemonic entry (marketing surface stays separate from sign-in).

## Sign-in (`frontend/web3-login.html`)

- [ ] With no `public-config.json` and `wc-config.js` **empty**: page shows clear “configure project id” message (no crash).
- [ ] With valid `public-config.json` **or** `wc-config.js` id: QR appears; after wallet connect + signature, browser lands on `studio/index.html` with session in **`sessionStorage.karma_web3_session`** (tab-scoped).
- [ ] **Home** returns to portal.
- [ ] Page is **wallet-only** (WalletConnect QR); no browser-side mnemonic / seed entry.

## Studio (`frontend/studio/`)

- [ ] Without session: redirect to `web3-login.html?target=studio%2Findex.html`.
- [ ] Sessions created by legacy demo paths (non–WalletConnect `loginMethod`) are rejected and force a fresh sign-in.
- [ ] With session: dashboard and nav render; **Sign out** clears session and returns to sign-in.
- [ ] Create Agent produces `shareLink` pointing at `../index.html?agent=...` (portal deep link placeholder).

## Deploy

- [ ] Static host serves `frontend/` as one tree; HTTPS in production.
- [ ] `public-config.json` generated on server (e.g. `./scripts/deploy/write-agent-guard-public-config.sh`) and **not** committed; or dev-only `wc-config.js` override.
