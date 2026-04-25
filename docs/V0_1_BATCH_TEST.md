# v0.1 Batch Stress Test (50-100 settlements)

Use this to run vertical scenario validation at realistic volume.

## Script

- `examples/v01-batch-settlement.ts`

## Prerequisites

- `SettlementEngine` deployed
- token allowlisted in engine
- payer has sufficient token balance
- payer approved `SettlementEngine` for token transfer

## Install

```bash
npm install ethers dotenv tsx
```

## Env

```bash
RPC_URL=<rpc_url>
ENGINE_ADDRESS=<engine_address>
TOKEN_ADDRESS=<allowed_token_address>
PAYER_PRIVATE_KEY=<payer_private_key_hex>
PAYEE_ADDRESS=<payee_address>
```

Optional tuning:

```bash
BATCH_SIZE=50          # recommended: 50 or 100
MIN_AMOUNT=100
MAX_AMOUNT=200
DELAY_MS=300
DEADLINE_SECONDS=3600
```

## Run 50 settlements

```bash
BATCH_SIZE=50 npx tsx examples/v01-batch-settlement.ts
```

## Run 100 settlements

```bash
BATCH_SIZE=100 npx tsx examples/v01-batch-settlement.ts
```

## Output Metrics

The script prints:

- attempted
- sent
- succeeded
- failed
- successRate
- failureReasons (grouped by known contract errors)
- sample tx hashes

## Recommended acceptance target

- success rate >= 95%
- no replay/nonce failures in normal run
- `TokenTransferFailed` should be 0 if balance/allowance are pre-checked
