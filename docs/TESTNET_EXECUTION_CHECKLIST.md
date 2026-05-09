# Testnet execution checklist — local repetition (`--send`)

Use this for **controlled real-world** runs of `scripts/testnet_repetition_suite.py`.  
Do **not** commit populated keys or logs that contain secrets.

---

## 1. Required `.env` variables

Copy `.env.testnet.example` to a **local gitignored** `.env` and set at minimum:

| Variable | Purpose |
|----------|---------|
| `TESTNET_RPC_URL` | HTTPS JSON-RPC for your testnet |
| `NONCUSTODIAL_AGENT_PAYMENT_ADDRESS` | Deployed `NonCustodialAgentPayment` |
| `ERC20_TOKEN_ADDRESS` | Test ERC20 used for `lockFunds` / `createBill` |
| `TESTNET_BUYER_PRIVATE_KEY` | Buyer EOA (pays gas; `createBill`, `confirmBill`, `requestBillPayout`) |
| `TESTNET_SELLER_PRIVATE_KEY` | Seller EOA (pays gas; `lockFunds` for bond path) |
| `TESTNET_SELLER_ADDRESS` | Seller **address** string; must **not** equal buyer address |

Optional (defaults exist in scripts / contract reads):

| Variable | Purpose |
|----------|---------|
| `BILL_AMOUNT_WEI` | Bill principal (default `1000000` smallest units) |
| `BUYER_LOCK_WEI` / `SELLER_LOCK_WEI` | Lock capacity overrides (defaults scale from amount + `sellerBondBps`) |
| `BILL_DEADLINE_UNIX` | `createBill` deadline |
| `SETTLEMENT_MODE` | Informational (`hybrid` / `testnet` typical) |
| `TESTNET_CHAIN_ID` | Optional if RPC reports chain id |

Load before running:

```bash
set -a && source .env && set +a
```

---

## 2. Required funded wallets

- **Buyer EOA** (`TESTNET_BUYER_PRIVATE_KEY`): enough **native gas** on the testnet for multiple txs per run × number of runs (approvals, locks, `createBill`, `confirmBill`, `requestBillPayout`).
- **Seller EOA** (`TESTNET_SELLER_PRIVATE_KEY`): enough **native gas** for approvals + `lockFunds` each run.
- **Addresses must differ**; `TESTNET_SELLER_ADDRESS` must match the seller key’s address.

---

## 3. Required test ERC20 balance / allowance

Per run, scripts roughly:

1. `approve` **max** (or large) allowance to the payment contract for **both** buyer and seller.
2. `lockFunds` for buyer and seller with amounts derived from `BILL_AMOUNT_WEI` and `sellerBondBps()`.

**Before the suite:** ensure **both** wallets hold enough **ERC20** balance so locks + bill principal do not revert, across **all** runs (e.g. 10× the per-run worst case, plus buffer).

**Allowance:** first txs per wallet set approval; if you use a token that requires reset or has quirks, watch for allowance-related reverts (see §7).

---

## 4. Exact command to run

```bash
set -a && source .env && set +a
python3 scripts/testnet_repetition_suite.py --runs 10 --output-root results/ta-repetition --send
```

---

## 5. Expected files generated

Under `results/ta-repetition/` (or your `--output-root`):

| Path | Content |
|------|---------|
| `repetition_summary.json` | All runs, exit codes, aggregates, `failures` list |
| `operational_log.jsonl` | One JSON line per run (trace / verification / settlement / tx snapshot) |
| `run-0000/` … `run-0009/` | Per-run artifacts from `testnet_full_flow.py` |

Inside each `run-NNNN/`:

| File | Content |
|------|---------|
| `task_contract.json` | Task + `trace_id` |
| `receipt_chain.json` | Demo receipt chain |
| `evidence_bundle.json` | Bundle + `trace_id` |
| `verification_result.json` | Structural verification + `trace_id` |
| `hybrid_settlement_result.json` | Off-chain plan + on-chain block + paths |
| `hybrid_tx_log.jsonl` | Append-only tx writeback rows (`tx_hash`, `chain_id`, `trace_id`, …) |

---

## 6. Expected success criteria

- Process **exits with status 0**.
- `repetition_summary.json`: **`failures` is empty** (or only acceptable reruns you explicitly allow).
- `aggregates.runs_with_trace_correlation_ok` equals **number of runs** (each run should have matching non-empty trace across task / bundle / verification / hybrid when using `--trace-id` from the suite).
- Each `verification_result.json`: **`decision` = `STRUCT_OK`**.
- Each `hybrid_settlement_result.json` → `onchain.onchain_transactions`: **non-empty** list with consistent `chain_id` and `contract_address`; **`tx_count`** matches the expected step count for your flow (same pattern every run).
- `operational_log.jsonl`: no `trace_correlation_mismatches`; **`idempotency_key_unique`: true** per line.

---

## 7. Failure cases to watch

| Symptom | Likely cause |
|---------|----------------|
| Immediate message **`Missing TESTNET_RPC_URL`** (or similar) | `.env` not loaded or variable unset |
| **`insufficient funds`** / underpriced / stuck pending | **Insufficient native gas** on buyer or seller |
| ERC20 **`transfer` / `transferFrom` revert** | **Insufficient token balance** for lock + bill |
| **`approve` then still transferFrom revert** | **Allowance** not set, wrong spender, or token non-standard behavior |
| **`execution reverted`** on specific step | Contract rule (deadline, bond, state); read revert reason in explorer or client |
| Same bill / payout intent executed twice unintentionally | **Duplicate settlement** attempt; compare `tx_hash` sequences and bill ids across runs; on-chain state is source of truth |
| `trace_correlation_ok: false` or mismatches in log | **Trace mismatch** between artifacts; stop and fix orchestration before publishing |

---

## 8. What to screenshot / save for public proof

Save (or redact safely) these **paths** from a successful `--output-root` tree:

1. **`tx_hash`** — from `hybrid_tx_log.jsonl` and/or `hybrid_settlement_result.json` → `onchain.onchain_transactions[]`.
2. **`receipt_chain.json`** — per run.
3. **`evidence_bundle.json`** — per run.
4. **`verification_result.json`** — per run (`STRUCT_OK`, `trace_id`).
5. **`hybrid_tx_log.jsonl`** — full append-only log for the run directory.
6. **`repetition_summary.json`** — rollup + `aggregates`.

Optional: one **block explorer** link per distinctive `tx_hash` (public testnet), and a short note of **chain id** + **contract addresses** copied from the JSON.

---

**End of checklist.** No architecture changes; run locally when `.env` and balances are ready.
