# Getting started — KARMA public repository

## 1. Clone

```bash
git clone https://github.com/AtoB101/Karma.git
cd Karma
```

## 2. Website + Console (static)

```bash
python3 -m http.server 8787
```

- Website: `http://127.0.0.1:8787/apps/website/index.html`
- Console: `http://127.0.0.1:8787/apps/console/index.html`
- Developers: `http://127.0.0.1:8787/apps/developer-portal/index.html`

Optional Docker static host: `docker compose -f docker/docker-compose.example.yml up` (see `docker/README.md`).

## 3. Contracts (Foundry)

```bash
forge build
forge test -q
```

## 4. Trusted Agent runtime (Python)

```bash
python3 scripts/trusted_agent_minimal_flow.py
```

## 5. Testnet (optional)

See `docs/TESTNET_EXECUTION_CHECKLIST.md` and `docs/TESTNET_RUNBOOK.md`.
