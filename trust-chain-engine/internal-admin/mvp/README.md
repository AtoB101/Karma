# Trust-Chain P0 Paid Price API MVP (Private)

Goal: prove real paid API settlement with one call.

## What this MVP shows

1. User balance before call
2. Agent triggers symbol price API call (e.g. BTCUSDT / ETHUSDC)
3. API returns symbol price
4. Automatic on-chain transfer settlement
5. Transaction hash and balances after call

## Setup

```bash
cd trust-chain-engine/internal-admin/mvp
cp .env.example .env
```

Edit `.env`:

- `RPC_URL`: your EVM RPC endpoint
- `USER_PRIVATE_KEY`: payer wallet private key (test wallet only)
- `PROVIDER_WALLET`: payee wallet address
- `CHARGE_WEI`: charge amount in wei (must be > 0)
- `MVP_PORT` (optional): default `8822`

## Run

```bash
npm install
./run-demo.sh
```

Open:

- `http://127.0.0.1:8822/`

## Go live portal (single command)

Start production-like portal server (serves UI + API on same origin):

```bash
./start-portal-live.sh
```

Run go-live checks (must pass before launch):

```bash
./portal-go-live-check.sh
```

## API

Primary namespace is now `/api/v1` (legacy `/api/*` remains compatible).

- `GET /api/v1/health` (legacy: `/api/health`)
- `GET /api/v1/status` (legacy: `/api/status`)
- `GET /api/v1/config`
- `GET /api/v1/dashboard`
- `GET /api/v1/agents`
- `POST /api/v1/agents`
- `PATCH /api/v1/agents/:id`
- `DELETE /api/v1/agents/:id`
- `GET /api/v1/user-console/overview`
- `GET /api/v1/user-console/pay-rule`
- `POST /api/v1/user-console/pay-rule`
- `POST /api/v1/user-console/payments/create`
- `POST /api/v1/user-console/payments/:id/approve|reject`
- `POST /api/v1/user-console/receipts/create`
- `GET /api/v1/bills`
- `POST /api/v1/bills/:id/confirm|reject|settle|dispute`
- `POST /api/v1/bills/batch-settle-now`
- `POST /api/v1/bills/strategy`
- `POST /api/v1/allowance/stop`
- `POST /api/v1/allowance/increase`
- `POST /api/v1/price-paid` with body `{ "symbol": "BTCUSDT" }`
- Compatibility alias: `POST /api/v1/btc-price-paid` (legacy alias remains too)

Detailed request/response contract: `./API_CONTRACT_V1.md`

## Seller one-click toolkit (new)

Initialize a seller starter project:

```bash
npx --yes --package file:. trustchain-seller-init ./my-seller-agent
```

Run gateway self-check:

```bash
npm run trustchain:doctor
```

Simulate first paid sale and auto-verify:

```bash
npm run trustchain:first-sale
```

## Agent wrapTool (author monetization)

Use the private helper to wrap any tool and charge per invocation:

```javascript
const { wrapTool } = require("./trustchain-wrap-tool");

const wrapped = wrapTool({
  gatewayBaseUrl: "http://127.0.0.1:8822",
  userId: "agent-owner-01",
  price: "0.01",
  token: "USDC",
  tool: async ({ symbol }) => ({ symbol }),
  symbolResolver: (input) => input.symbol,
});
```

Run the demo:

```bash
npm run agent-example
# with custom symbol
npm run agent-example -- SOLUSDT
```

## External user simulation

```bash
npm run simulate
# writes logs/external-user-call-summary.json
```

Or with explicit environment overrides:

```bash
RPC_URL=http://127.0.0.1:8545 \
USER_PRIVATE_KEY=<external-user-test-key> \
PROVIDER_WALLET=<provider-wallet> \
CHARGE_WEI=1000000000000 \
./simulate-external-user-call.sh --symbol ETHUSDC
```

## Capture demo proof bundle

```bash
npm run proof
# writes logs/proofs/demo-proof-<timestamp>.json
```

## Output logs

Paid call records are appended to:

- `logs/paid-calls.jsonl`

Each record includes:

- `symbol`
- `exchange`
- `quote`
- `chargedWei`
- `txHash`
- `balances.before/after`

## Verify first paid call closure

Run:

```bash
./verify-first-paid-call.sh
```

or:

```bash
npm run verify
```

Verifier checks:

1. a paid-call log exists
2. `chargedWei > 0`
3. `txHash` format is valid
4. user/provider balances changed in expected direction

Optional explicit threshold:

```bash
EXPECTED_MIN_CHARGE_WEI=10000000000000 ./verify-first-paid-call.sh
```

## Important

- This is a private validation MVP.
- Do not use production private keys.
