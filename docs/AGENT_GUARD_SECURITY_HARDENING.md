# Agent Guard — Security hardening (full-chain)

Defense-in-depth for the public static frontend **and its CI gates**. Security CI for contracts (Foundry + Slither) runs separately; this document ties both together.

## End-to-end control map

| Layer | Controls |
|-------|-----------|
| **Repository** | `scripts/security-baseline-guard.sh` blocks private paths, obvious secrets, insecure auth flags, tracked `public-config.json`. |
| **CI — contracts** | `.github/workflows/security-ci.yml`: `forge test`, invariant suite, Slither, trust-engine safety, **`scripts/agent-guard-security-gate.py`**. |
| **CI — Agent Guard UI** | `.github/workflows/agent-service-guard-smoke.yml`: Phase 2 gate, security gate, Playwright + Python smoke. |
| **Marketing portal** | `index.html`: strict CSP meta (no remote scripts, **`connect-src 'none'`**), **`landing.js`** with **Subresource Integrity (SRI)**; no WalletConnect/ethers/session keys. Lang preference only: `localStorage[karma_landing_lang]`. |
| **Studio** | CSP meta（含 **`style-src 'self' 'unsafe-inline'`** 以支持动态样式条等 UI）；`connect-src 'self'`（API 请同源反代）；`robots noindex`；会话仅 **`walletconnect-v2-qr`**；`api-config.js` 设置 API 根路径；`saveState` 大小上限与列表上限。 |
| **Sign-in** | WalletConnect QR only; `noindex,nofollow`; Permissions-Policy meta; CDN + **`esm.sh`** pins (upgrade versions deliberately). |
| **Deploy** | `scripts/deploy/write-agent-guard-public-config.sh`: `umask 077`, **`chmod 600`** on emitted JSON; **`public-config.json`** gitignored. |
| **Edge** | `infra/nginx/agent-guard-security-headers.conf` + split CSP templates: `agent-guard-csp-portal.conf`, `agent-guard-csp-studio.conf`, `agent-guard-csp-wallet.conf`. |

## Threat notes

- **XSS** on the origin can steal `sessionStorage` while the tab is open. CSP + minimizing inline script + SRI shrink attack surface.
- **WalletConnect Project ID** is public client metadata — still inject via **`public-config.json`**, never commit production IDs.
- **Do not** add **Cross-Origin-Opener-Policy** on the WalletConnect route without staging tests (some wallets use popups or auxiliary tabs).

## Deploy checklist (production)

1. **HTTPS only** — HSTS at the edge (see Nginx snippet).
2. **Host split** — `www` = portal (+ `landing.js`), `app` = `web3-login.html` + `studio/` (+ tighter CSP/connect rules).
3. **Headers** — include baseline snippet; uncomment CSP **`add_header`** lines per-location after validating WalletConnect **`connect-src`** in staging.
4. **SRI drift** — any edit to **`landing.js`** must update **`integrity`** in **`index.html`**; CI verifies with **`scripts/agent-guard-security-gate.py`**.
5. **Operational** — rotate WalletConnect Cloud project if abuse is suspected; monitor `@walletconnect/sign-client` advisories.

## Automation

- **`python3 scripts/agent-guard-security-gate.py`** — portal forbidden tokens, `landing.js` SHA-384 SRI vs file, WalletConnect page invariants, studio meta CSP.
- **`scripts/agent-guard-security-gate.py`** is invoked from **Security CI** and **Agent Guard Smoke** workflows.

## Out of scope (static-only)

- **HttpOnly** sessions and server-side logout require a backend.
- Hardware wallets / attestations are product choices outside this repo’s static bundle.
