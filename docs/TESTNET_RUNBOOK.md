# Testnet Runbook (KarmaBilateral)

Active path only: **`lock → bind → settle → finalizeSettle`**.

## Prerequisites

1. Deployed `KarmaBilateral` + allowlisted ERC-20 (e.g. Sepolia USDC/test token).
2. Buyer and agent wallets with token balances and approvals to the Bilateral contract.
3. Env (local, gitignored):

| Variable | Purpose |
|----------|---------|
| `TESTNET_RPC_URL` | JSON-RPC |
| `KARMA_BILATERAL_ADDRESS` | Bilateral contract |
| `ERC20_TOKEN_ADDRESS` | Settlement token |
| `TESTNET_PRIVATE_KEY` | Operator / signer for adapter scripts |
| `SETTLEMENT_MODE` | `offchain` \| `hybrid` \| `testnet` |

## Evidence / proofHash

Use `evidence_runtime` to build bundles and digests.  
Canonical pointer form: `karma-ta:v1/sha256/<64 hex>` (see `evidence_runtime/proof_hash_format.py`).  
On settle, the adapter submits a `bytes32` proof derived from the evidence digest.

## Recommended local sequence

1. Structural verify offline: `evidence_runtime.verification`
2. Build plan: `SettlementAdapter.build_offchain_plan` → expected calls `lockBuyer/lockAgent/bind/settle/finalizeSettle`
3. With `SETTLEMENT_MODE=testnet`, use `services.chain.settlement_adapter.OnChainSettlementAdapter` (requires `onchain_binding_id` for settle)

## Verify gates

```bash
bash scripts/run_public_acceptance_tests.sh -q
bash scripts/acceptance/full_chain_audit_gate.sh
python3 scripts/stress_evidence_runtime.py --agents 100 --seed 42 --output-dir /tmp/stress
```

Legacy NCPA createBill / confirmBill / requestBillPayout scripts are **not** in this repository.
