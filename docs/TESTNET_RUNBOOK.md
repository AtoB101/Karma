# Testnet runbook — Trusted Agent hybrid (Phase 3)

This runbook describes the **minimal real testnet path** on top of the existing
`NonCustodialAgentPayment` contract. It does **not** add new escrow contracts.

## Prerequisites

1. **Deploy or obtain** a `NonCustodialAgentPayment` instance and an **ERC20** token on your testnet (e.g. Sepolia) with balances for **buyer** and **seller** keys.
2. Python **web3** stack (not required for Phase-2-only flows):

   ```bash
   pip install -r requirements-testnet.txt
   ```

3. Copy `.env.testnet.example` to a **local gitignored** `.env` and fill values **without committing keys**.

## Environment variables

| Variable | Purpose |
|----------|---------|
| `TESTNET_RPC_URL` | HTTPS JSON-RPC endpoint |
| `NONCUSTODIAL_AGENT_PAYMENT_ADDRESS` | Existing Karma core contract |
| `ERC20_TOKEN_ADDRESS` | Token used for `lockFunds` / `createBill` |
| `TESTNET_BUYER_PRIVATE_KEY` | Buyer wallet (funds `createBill`, `confirmBill`) |
| `TESTNET_SELLER_PRIVATE_KEY` | Seller wallet (must `lockFunds` for bond capacity) |
| `TESTNET_SELLER_ADDRESS` | Seller **address** (must differ from buyer) |
| `BILL_AMOUNT_WEI` | Bill principal (default `1000000`) |
| `BUYER_LOCK_WEI` / `SELLER_LOCK_WEI` | Optional lock overrides (defaults scale from amount + `sellerBondBps`) |
| `BILL_DEADLINE_UNIX` | Optional Unix deadline for `createBill` |
| `SETTLEMENT_MODE` | `hybrid` or `testnet` (informational; scripts always perform on-chain steps when `--send` is used) |

For **stepwise** scripts you also need:

| Variable | Scripts |
|----------|---------|
| `KARMA_PROOF_HASH` | `testnet_create_bill.py` (string passed to `createBill`) |
| `KARMA_SCOPE_HEX` | `testnet_create_bill.py` (`0x` + 64 hex = 32-byte `scopeHash`) |

Generate them from the hybrid artifact file:

- `hybrid_settlement_result.json` → fields `karma_proof_hash`, `karma_scope_hex`

## One-shot hybrid (recommended)

Writes off-chain JSON + optional on-chain tx log:

```bash
# Off-chain artifacts only
python3 scripts/testnet_full_flow.py --output-dir results/trusted-agent-hybrid

# + on-chain sequence (requires env + token balances)
set -a && source .env && set +a
python3 scripts/testnet_full_flow.py --output-dir results/trusted-agent-hybrid --send
```

Optional **`--trace-id`** sets the correlation id on `task`, receipts, bundle, verification, settlement plan, and each `tx_writeback_record` (default: `trace-<task_id>`).

## Repeated small-value runs (10–50)

For operational burn-in after stabilization checks pass locally:

```bash
python3 scripts/testnet_repetition_suite.py --runs 10 --output-root results/ta-repetition
# With live txs (same env as one-shot --send):
set -a && source .env && set +a
python3 scripts/testnet_repetition_suite.py --runs 10 --output-root results/ta-repetition --send
```

Writes `repetition_summary.json` under `--output-root` plus one subdirectory per run (`run-0000`, …) each containing the usual hybrid JSON artifacts.

Outputs:

- `hybrid_settlement_result.json` — merges `offchain_plan`, bundle digest, and (with `--send`) `onchain_transactions` with **`tx_hash`**, **`chain_id`**, **`contract_address`**, **`settlement_status`**, **`onchain_status`**, `block_number`.
- `hybrid_tx_log.jsonl` — append-only JSON lines (same records).

## Stepwise scripts (debug / CI partial gates)

```bash
python3 scripts/testnet_lock.py --party buyer --amount 10000000 --tx-log results/tx.jsonl
python3 scripts/testnet_lock.py --party seller --amount 5000000 --tx-log results/tx.jsonl
export KARMA_PROOF_HASH='...' KARMA_SCOPE_HEX='0x...'
python3 scripts/testnet_create_bill.py --tx-log results/tx.jsonl
python3 scripts/testnet_confirm.py --bill-id <id> --tx-log results/tx.jsonl
python3 scripts/testnet_payout.py --bill-id <id> --tx-log results/tx.jsonl
```

## Safety

- Never commit populated `TESTNET_*_PRIVATE_KEY` values.
- Use **disposable test wallets** and small token amounts.
