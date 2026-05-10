# KARMA Console (public shell)

Static **operational shell** for Receiving, Payments, Agents, Evidence, and Disputes.  
Wallet signing, chain writes, and private risk calls belong in integrated clients — this tree ships **layout + copy + navigation** only.

## Principles

- **Website** (`apps/website`) does not connect wallets.  
- **Console** is where Connect Wallet and bill/evidence/dispute UX live.  
- Production may host Console at `https://app.karma-network.ai` with `/console` rewrites.

## Preview

```bash
python3 -m http.server 8787
```

Open `http://127.0.0.1:8787/apps/console/index.html`.

For WalletConnect-based sign-in (demo), the repository also ships `apps/agent-service-guard/frontend/web3-login.html` — wire your deployment to land users in Console after auth.
