# Karma Guard — Acceptance (single portal + studio)

## Portal (`frontend/index.html`)

- [ ] Karma Protected marketing layout loads; CTAs point to `web3-login.html?target=studio%2Findex.html` (isolated console).
- [ ] Language switcher lists Global, Southeast Asia, and Africa groups; switching updates copy and `<html lang>` (RTL for Arabic).
- [ ] Loads **`landing.js`** with **`integrity="sha384-..."`** + portal **CSP** (`connect-src 'none'`).
- [ ] **Sign in** uses same wallet sign-in URL as console entries.
- [ ] No WalletConnect / mnemonic / session logic on the marketing page.

## Sign-in (`frontend/web3-login.html`)

- [ ] With no `public-config.json` and `wc-config.js` **empty**: page shows clear “configure project id” message (no crash).
- [ ] With valid `public-config.json` **or** `wc-config.js` id: QR appears; after wallet connect + signature, browser lands on `studio/index.html` with session in **`sessionStorage.karma_web3_session`** (tab-scoped).
- [ ] **Home** returns to portal.
- [ ] Page is **wallet-only** (WalletConnect QR); no browser-side mnemonic / seed entry.

## Studio (`frontend/studio/`)

- [ ] Without session: redirect to `web3-login.html?target=studio%2Findex.html`.
- [ ] Sessions created by legacy demo paths (non–WalletConnect `loginMethod`) are rejected and force a fresh sign-in.
- [ ] With session: **统一操作界面** loads;侧栏导航切换各模块；钱包址显示在顶栏。
- [ ] **立即同步** / 定时拉取调用 `sync.js`：成功时 `syncMeta.lastSource=api`，失败保留本地 `unified` 演示数据。
- [ ] `POST /services` / `GET /orders` 等在有后端时更新列表；无后端时创建服务回退到本地 `createAgent`。
- [ ] **Sign out** clears session and returns to sign-in.

## Deploy

- [ ] Static host serves `frontend/` as one tree; HTTPS in production.
- [ ] `public-config.json` generated on server (e.g. `./scripts/deploy/write-agent-guard-public-config.sh`) and **not** committed; or dev-only `wc-config.js` override.
