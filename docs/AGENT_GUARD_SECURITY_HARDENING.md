# Agent Guard — Security hardening (public static frontend)

This document describes **defense-in-depth** for `apps/agent-service-guard/frontend/` when you treat security as the first mission.

## Threat model (short)

- **XSS** on the same origin can read `sessionStorage` / `localStorage` and impersonate the user until logout or tab close.
- **Supply-chain** compromise of third-party CDNs could alter scripts; mitigate with **SRI** and pinning versions.
- **WalletConnect Project ID** is a *public client identifier*; still avoid committing production values to git — generate `public-config.json` at deploy (see `scripts/deploy/write-agent-guard-public-config.sh`).

## Implemented in-repo

| Control | Detail |
|--------|--------|
| Surface split | Marketing **`index.html`** does not load WalletConnect, QR libraries, or wallet session logic — only links to **`web3-login.html`**. Reduces XSS blast radius on the most content-heavy page. |
| Auth session | `karma_web3_session` stored in **`sessionStorage`** (tab-scoped). Legacy `localStorage` copies are **migrated once** then removed. Studio accepts only `loginMethod === "walletconnect-v2-qr"`. |
| WalletConnect ID | **Not** written to `localStorage`; only `window.KARMAPAY_WC_PROJECT_ID` after `wc-config.js` + optional `public-config.json`. |
| Pairing URI | **Not** persisted to storage. |
| Referrer | `strict-origin-when-cross-origin` on portal and sign-in pages. |
| Sign-in page | **`noindex, nofollow`** to avoid indexing an app entrypoint; wallet-only flow (no browser mnemonic entry). |
| Subresource integrity | `integrity="sha384-…"` on pinned **Font Awesome** (portal) and **qrcodejs** (sign-in). |
| Legacy cleanup | Sign-in boot removes obsolete `karma_wc_project_id` / `karma_web3_last_wc_uri` keys if present. |

## Deploy-time (mandatory for production)

1. **HTTPS only** — HSTS at the edge (see Nginx snippet).
2. **Security headers** — use `infra/nginx/agent-guard-security-headers.conf` (or equivalent on Caddy/CloudFront). Includes `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy`, `Cross-Origin-Resource-Policy`.
3. **`public-config.json`** — generated on the server from `WALLETCONNECT_PROJECT_ID`; file is **gitignored**; never paste secrets into the portal UI.
4. **CSP (Content-Security-Policy)** — WalletConnect and `esm.sh` endpoints evolve. Start from **Report-Only** in staging, watch browser console / reports, then tighten `connect-src` / `script-src`. A starter policy is commented in the Nginx snippet file.
5. **Seed phrases** — do **not** implement mnemonic or private-key entry in public web surfaces. Users should keep seeds in hardware or wallet apps; this repo’s sign-in is **WalletConnect QR only**.

## Operational

- Rotate WalletConnect Cloud project if abuse is suspected.
- Rebuild and redeploy when upgrading CDN script versions (SRI hashes must match).
- Monitor dependency advisories for `@walletconnect/sign-client` majors you pin in import URLs.

## Out of scope for static-only hosting

- **HttpOnly cookies** and server-side session invalidation require a backend.
- **Hardware security modules** / remote attestation are product-level, not static-file level.
