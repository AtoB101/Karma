# Karma Private Runtime

**CONFIDENTIAL. Internal use only. Never make public.**

---

## Prerequisites

Public SDK must be installed first:

```bash
cd ../karma-public
pip install -e ".[dev]"
```

Then install private runtime:

```bash
cd ../karma-private
pip install -e ".[dev]"
```

---

## Configure

```bash
cp .env.private.example .env.private
# Edit: set RUNTIME_API_KEY (must match PUBLIC .env PRIVATE_RUNTIME_API_KEY)
```

---

## Run Tests

```bash
pytest tests/ -v
pytest tests/ -v --cov=. --cov-report=term-missing
```

---

## Start Runtime Locally

```bash
python main.py
# Binds to 127.0.0.1:8001 — never exposed to public internet
```

---

## Start Runtime via Docker

```bash
docker compose -f deploy/docker-compose.private.yml up
```

---

## Project Layout

```
karma-private/
├── api/                  Private FastAPI app (no public docs endpoint)
├── core/
│   ├── verification/     Full verification engine (weights + decision matrix)
│   ├── settlement/       Release/refund/dispute logic + partial split formula
│   ├── reputation/       Score deltas + decay + anti-gaming
│   ├── risk/             Risk scoring weights + malicious actor detection
│   ├── fraud/            Wash trade, self-dealing, replay attack detection
│   ├── behavior/         Bot detection + timing variance analysis
│   └── arbitration/      Buyer/seller win conditions + arbitration weights
├── db/stores/            Private store injection layer
├── tests/                Full private engine test suite
├── deploy/               Dockerfile.runtime + docker-compose.private.yml
└── docs/                 OPS_SOP.md
```

---

## Definition of Private

This repo contains the **WHY** behind every Karma decision:
- Verification check weights and thresholds
- Fraud detection signal definitions
- Arbitration composite scoring formula
- Reputation score delta table and decay algorithm
- Risk factor weights

The public SDK only sees the output (`VerificationResult`, `SettlementState`).
