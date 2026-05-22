# Karma Solana Integration SDK 🛡️⚡

**Plugs Karma's verifiable execution (signed receipts + evidence bundles) into the Solana agent ecosystem.**

[![Python 3.11+](https://img.shields.io/badge/python-3.11+-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-Apache%202.0-green.svg)](LICENSE)
[![Solana](https://img.shields.io/badge/Solana-devnet%20%7C%20mainnet-purple.svg)](https://solana.com)

---

## Overview

The **Karma Solana SDK** extends [Karma Trust Protocol](https://github.com/AtoB101/Karma) to Solana, enabling:

- ✅ **Verifiable Execution** — Cryptographic proof of agent tool execution (signed receipts)
- ✅ **Evidence Bundles** — Merkle-verifiable audit packages stored on Arweave/IPFS
- ✅ **On-Chain Settlement** — Verification results recorded on Solana via SPL Memo instructions
- ✅ **x402 Payments** — Agent-to-Agent micropayments using SPL tokens (USDC, SOL)
- ✅ **Cross-Chain Parity** — Same API surface as Karma BNB Chain, different settlement backend

This package is designed for **Solana Grant applications**, **Hackathon submissions**, and **production deployments** with the Solana agent ecosystem.

---

## Comparison: Karma on BNB Chain vs Solana

| Feature | BNB Chain (ERC-8183) | Solana |
|---------|---------------------|--------|
| **Verification** | Karma Runtime (off-chain) | Karma Runtime (off-chain) |
| **Evidence Storage** | BSC calldata / events | Arweave / IPFS |
| **Settlement** | `router.settle(jobId, evidence)` | SPL Memo / Program instruction |
| **Payment** | x402 (EVM, ERC-20) | x402 (SPL, USDC/SOL) |
| **Transaction Speed** | ~3 seconds | ~0.4 seconds |
| **Transaction Cost** | ~$0.03 | ~$0.0002 |
| **Agent Standard** | ERC-8183 / bnbagent | x402 / Solana Agent Kit |
| **SDK Import** | `pip install "bnbagent[karma]"` | `pip install karma-solana` |

---

## Installation

```bash
# From the Karma monorepo
cd packages/karma-solana
pip install -e ".[dev]"

# Or as a standalone package
pip install karma-solana

# With x402 payment support
pip install "karma-solana[x402]"
```

### Prerequisites

- Python 3.11+
- Solana CLI tools (optional, for keypair generation)
- Karma Runtime API access (for verification)
- Arweave wallet (optional, for permanent evidence storage)

---

## Quickstart

```python
from karma_solana import KarmaSolanaVerifier, ArweaveUploader, SolanaX402Hook
from solders.keypair import Keypair
from karma.sdk import KarmaClient

# ── 1. Initialize Karma Client ────────────────────────────────────
client = KarmaClient(
    agent_id="solana-agent-001",
    runtime_url="https://api.karma.xyz",
    api_key="karma_your_api_key",
)

# ── 2. Initialize Solana Verifier ──────────────────────────────────
verifier = KarmaSolanaVerifier(
    karma_endpoint="https://api.karma.xyz",
    api_key="karma_your_api_key",
    solana_rpc="https://api.mainnet-beta.solana.com",
    evidence_store=ArweaveUploader(wallet_path="./arweave-key.json"),
    x402_hook=SolanaX402Hook(network="solana-mainnet"),
)

# ── 3. Execute and Settle ──────────────────────────────────────────
keypair = Keypair.from_base58_string("your_base58_private_key")

# Agent executes tool calls (automatic receipt generation)
result, receipts = await client.run_task("task-solana-001", my_task_fn)

# Build evidence bundle
bundle = await client.build_bundle("task-solana-001")

# Verify + Upload + Settle on Solana
settlement = await verifier.verify_and_settle(
    task_id="task-solana-001",
    evidence_bundle=bundle,
    signer_keypair=keypair,
)

print(f"Solana Tx  : {settlement.solana_tx_signature}")
print(f"Evidence   : {settlement.evidence_uri}")
print(f"Verdict    : {settlement.verdict}")
print(f"Confidence : {settlement.confidence:.2%}")
```

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                   KARMA SOLANA SDK                      │
├─────────────────────────────────────────────────────────┤
│                                                         │
│  ┌─────────────────┐    ┌──────────────────────────┐   │
│  │ KarmaSolana     │    │ Karma Runtime (off-chain)│   │
│  │ Verifier        │───▶│ POST /v1/verify           │   │
│  │                 │    │ - Receipt hash check      │   │
│  │ verify_and_     │    │ - Signature validation    │   │
│  │ settle()        │    │ - Merkle proof verify     │   │
│  └───────┬─────────┘    │ - Confidence scoring      │   │
│          │              └──────────────────────────┘   │
│          │                                             │
│          ▼                                             │
│  ┌─────────────────┐    ┌──────────────────────────┐   │
│  │ Evidence        │    │ Arweave / IPFS           │   │
│  │ Store           │───▶│ Content-addressed storage │   │
│  │                 │    │ ar://<tx_id>             │   │
│  │ upload/retrieve │    │ ipfs://<cid>             │   │
│  └───────┬─────────┘    └──────────────────────────┘   │
│          │                                             │
│          ▼                                             │
│  ┌─────────────────┐    ┌──────────────────────────┐   │
│  │ Transaction     │    │ Solana Blockchain        │   │
│  │ Builder         │───▶│ - SPL Memo (verdict)     │   │
│  │                 │    │ - SPL Transfer (x402)    │   │
│  │ send_memo /     │    │ - Future: Karma Program  │   │
│  │ send_spl_transfer│   └──────────────────────────┘   │
│  └─────────────────┘                                   │
│                                                         │
│  ┌─────────────────┐    ┌──────────────────────────┐   │
│  │ x402 Hook       │    │ Agent-to-Agent Payment   │   │
│  │                 │───▶│ - HTTP 402 challenge      │   │
│  │ execute_payment │    │ - SPL token transfer      │   │
│  │                 │    │ - PaymentProof (audit)    │   │
│  └─────────────────┘    └──────────────────────────┘   │
│                                                         │
└─────────────────────────────────────────────────────────┘
```

---

## Package Structure

```
packages/karma-solana/
├── __init__.py              # Public API surface
├── verifier.py              # KarmaSolanaVerifier — core engine (~320 lines)
├── transaction_builder.py   # SolanaTransactionBuilder — tx construction (~250 lines)
├── evidence_store.py        # ArweaveUploader, IPFSUploader, MockUploader (~260 lines)
├── x402.py                  # SolanaX402Hook — x402 payments (~200 lines)
├── pyproject.toml           # Package config with extras
├── README.md                # This file
├── examples/
│   └── solana_integration.py  # Full end-to-end demo
└── tests/
    ├── __init__.py
    └── test_verifier.py      # 15+ tests covering verifier, evidence, settlement
```

---

## Usage Examples

### Standalone Verifier (without Karma Client)

```python
from karma_solana import KarmaSolanaVerifier
from karma_solana.evidence_store import MockUploader

verifier = KarmaSolanaVerifier(
    karma_endpoint="http://localhost:8000",
    api_key="karma_dev_key",
    solana_rpc="https://api.devnet.solana.com",
    evidence_store=MockUploader(),  # In-memory for testing
)

# Verify only (no on-chain settlement)
result = await verifier.verify_only(
    task_id="task-001",
    evidence_bundle=my_bundle,
)
print(f"Decision: {result.decision}, Confidence: {result.confidence}")
```

### x402 Payment Integration

```python
from karma_solana import SolanaX402Hook
from solders.keypair import Keypair

hook = SolanaX402Hook(
    solana_rpc="https://api.devnet.solana.com",
    network="solana-devnet",
)

# Execute payment
proof = await hook.execute_payment(
    signer_keypair=payer_keypair,
    accept=payment_accept,  # From HTTP 402 response
    task_id="task-001",
)

# Verify payment signature
is_valid = hook.verify_payment_signature(proof)
print(f"Payment valid: {is_valid}")  # True
```

### Custom Evidence Storage

```python
from karma_solana import SolanaEvidenceStore
from core.schemas import EvidenceBundle

class S3EvidenceStore(SolanaEvidenceStore):
    """Store evidence bundles in AWS S3."""

    async def upload(self, bundle: EvidenceBundle) -> str:
        # Upload to S3, return presigned URL
        return f"https://s3.amazonaws.com/my-bucket/bundles/{bundle.bundle_id}.json"

    async def retrieve(self, uri: str) -> dict | None:
        # Download from S3
        ...

verifier = KarmaSolanaVerifier(
    ...,
    evidence_store=S3EvidenceStore(),
)
```

---

## Running the Demo

```bash
cd packages/karma-solana
pip install -e ".[dev]"
python examples/solana_integration.py
```

Expected output:

```
🛡️  KARMA SOLANA — FULL INTEGRATION DEMO
   Task ID     : solana-demo-abc12345
   Agent ID    : solana-agent-001

📋 STEP 1: Karma Agent executes tool calls (Solana agent)
   ✓ rcpt-solana-demo-abc12345-0001 | solana.getBalance | status=SUCCESS
   ✓ rcpt-solana-demo-abc12345-0002 | solana.swap | status=SUCCESS
   ✓ rcpt-solana-demo-abc12345-0003 | llm.verify_result | status=SUCCESS

📦 STEP 2: Build evidence bundle
   Bundle ID: bundle-solana-demo-abc12345
   Receipts : 3/3 successful

🔍 STEP 3: Karma Runtime Verification (off-chain)
   ✓ PASS | receipt_hash_consistency
   ✓ PASS | step_ordering
   ...
   Decision: RELEASE (confidence: 0.98)

📤 STEP 4: Upload evidence to decentralized storage
   Arweave URI: ar://karma-bundle-abc12345

⚡ STEP 5: Solana On-Chain Settlement
   Solana Tx Signature: SIMULATED_TX_abc12345

💸 STEP 6: x402 Payment on Solana (Agent-to-Agent)
   Asset: 5.0 USDC

🔄 STEP 7: Full Round-Trip Verification
   ✅ ALL CHECKS PASSED

📊 DEMO SUMMARY
   Pipeline: Tool Execution → Signed Receipt → Evidence Bundle
             → Karma Runtime → Arweave → Solana Settlement
             → x402 Payment → Audit Trail Complete
```

---

## Testing

```bash
# Run all tests
pytest tests/ -v

# With coverage
pytest tests/ -v --cov=karma_solana --cov-report=term-missing

# Run a specific test
pytest tests/test_verifier.py::TestKarmaSolanaVerifier::test_compute_bundle_hash_deterministic -v
```

---

## Roadmap / Future Work

- [ ] **Dedicated Karma Solana Program** — Replace SPL Memo with a typed on-chain Program for structured evidence storage
- [ ] **CPI Integration** — Cross-Program Invocation with Solana Agent frameworks (SendArc, Solana Agent Kit)
- [ ] **Anchor IDL** — Generate Anchor IDL for the Karma Solana Program
- [ ] **Rust SDK** — Native Rust crate for high-performance Solana integration
- [ ] **Solana Pay Support** — QR-based payment intent for x402
- [ ] **Jupiter Integration** — Any-to-any token swaps as part of x402 payment
- [ ] **Compressed NFTs** — Use cNFTs for evidence bundle attestation (low cost)
- [ ] **Solana Mobile Stack** — SMS-compatible x402 payment link generation

---

## Related Projects

- [Karma Trust Protocol](https://github.com/AtoB101/Karma) — Main repository
- [Karma BNB Chain Integration](https://github.com/bnb-chain/bnbagent-sdk) — BNB Chain equivalent (`pip install "bnbagent[karma]"`)
- [ERC-8183](https://eips.ethereum.org/EIPS/eip-8183) — Agentic Commerce standard
- [x402 Protocol](https://x402.org) — HTTP 402 Payment Required for agents
- [Solana Agent Kit](https://github.com/sendaifun/solana-agent-kit) — Solana agent framework
- [Anchor](https://www.anchor-lang.com/) — Solana program framework (for future Karma Program)

---

## License

Apache 2.0 — see [LICENSE](../../LICENSE) in the parent repository.

---

## Contributing

See [CONTRIBUTING.md](../../CONTRIBUTING.md) in the parent repository.

For Solana-specific contributions, please ensure:
- All Solana RPC calls are mocked in tests
- Evidence store implements the `SolanaEvidenceStore` interface
- x402 payment proofs are independently verifiable
- Transaction builders handle all Solana-specific edge cases (blockhash expiry, priority fees)
