# Execution Receipt Standard V2 — KarmaBilateral

**Status:** Draft  
**Supersedes:** [EXECUTION_RECEIPT_STANDARD.md](./EXECUTION_RECEIPT_STANDARD.md) (V1, bill-based)  
**Last updated:** 2026-05-31

## Overview

Version 2 updates the execution receipt standard to align with `KarmaBilateral`'s
bilateral binding model. Receipts are now **binding-based** rather than **bill-based**.
A binding links two Bill Tokens (buyer + agent) into an atomic settlement unit; the
receipt proves correct execution of the task defined by the binding's `scopeHash`.

---

## 1. Core Changes from V1

| Aspect | V1 (NCPA) | V2 (KarmaBilateral) |
|--------|-----------|---------------------|
| Receipt anchor | `billId` | `bindingId` |
| Parties referenced | `buyer` + `seller` | `buyer` + `agent` |
| Proof hash purpose | Informational / audit | Required for `settle()` on-chain |
| Evidence bundle scope | Single bill lifecycle | Bilateral lock lifecycle |
| Settlement timing | Immediate after confirmation | Two-phase: `settle()` + `finalizeSettle()` |
| Dispute window | None on-chain | 24h after `settle()` |
| Attestation path | Not supported | N-of-M via `KarmaAttestationGateway` |

---

## 2. Receipt Schema (V2)

### 2.1 Required Fields

```json
{
  "receipt_id": "string — UUID or sequential",
  "binding_id": "uint256 — KarmaBilateral binding ID",
  "buyer_bill_id": "uint256 — buyer's Bill Token ID",
  "agent_bill_id": "uint256 — agent's Bill Token ID",
  "task_id": "string — off-chain task identifier",
  "scope_hash": "bytes32 — keccak256(task-scope)",
  "agent_id": "string — executing agent identifier",
  "tool_name": "string — tool or API invoked",
  "step_index": "uint — execution step order within task",
  "input_hash": "string — SHA-256 of serialized input",
  "output_hash": "string — SHA-256 of serialized output",
  "started_at": "ISO-8601 timestamp",
  "ended_at": "ISO-8601 timestamp",
  "duration_ms": "uint",
  "status": "success | failure | timeout | skipped"
}
```

### 2.2 KarmaBilateral-Specific Fields (V2 additions)

| Field | Type | Description |
|-------|------|-------------|
| `settlement_layer` | `uint8` | `1` = Optimistic, `2` = TEE (reserved), `3` = ZK (reserved) |
| `attestation_task_id` | `bytes32` | Present only if `bindWithAttestation()` was used |
| `proof_hash` | `bytes32` | `keccak256(evidenceBundle)` — the value submitted to `settle()` |
| `binding_created_at` | `uint256` | Block timestamp of `bind()` |
| `settle_after` | `uint256` | Earliest timestamp `settle()` can be called |
| `finalize_after` | `uint256` | Earliest timestamp `finalizeSettle()` can be called |
| `dispute_window_seconds` | `uint256` | Configured dispute window duration |

### 2.3 Template Type: `bilateral` (new)

```json
{
  "template": "bilateral",
  "template_version": "v2.0",
  "binding_id": 42,
  "buyer_bill_id": 15,
  "agent_bill_id": 28,
  "scope_hash": "0xabc123...",
  "proof_hash": "0xdef456...",
  "settlement_layer": 1,
  "dispute_window_seconds": 86400
}
```

---

## 3. Proof Hash Format

### 3.1 Construction

The `proofHash` submitted to `settle(bindingId, proofHash)` is computed as:

```
proofHash = keccak256(
    abi.encodePacked(
        bindingId,
        scopeHash,
        evidenceBundleCid
    )
)
```

Where:
- `bindingId` — `uint256`, the on-chain binding identifier
- `scopeHash` — `bytes32`, matches the `scopeHash` from `bind()`
- `evidenceBundleCid` — `bytes32`, keccak256 of the IPFS CID of the full evidence bundle

### 3.2 Example (Solidity)

```solidity
bytes32 proofHash = keccak256(
    abi.encodePacked(
        uint256(42),                              // bindingId
        keccak256("search:latest-pricing"),       // scopeHash
        keccak256("bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi") // IPFS CID hash
    )
);
```

### 3.3 Example (JavaScript/TypeScript)

```typescript
import { keccak256, solidityPacked, toUtf8Bytes } from "ethers";

const proofHash = keccak256(
  solidityPacked(
    ["uint256", "bytes32", "bytes32"],
    [
      42n,
      keccak256(toUtf8Bytes("search:latest-pricing")),
      keccak256(toUtf8Bytes("bafybeigdyrzt5sfp7udm7hu76uh7y26nf3efuylqabf3oclgtqy55fbzdi")),
    ]
  )
);
```

---

## 4. Evidence Bundle Structure for Bilateral Locks

### 4.1 Schema (V2)

```json
{
  "bundle_id": "string — UUID",
  "bundle_version": "v2.0-bilateral",
  "binding_id": 42,
  "scope": {
    "scope_hash": "0x...",
    "scope_description": "search:latest-pricing — pricing data retrieval"
  },
  "parties": {
    "buyer": {
      "address": "0x...",
      "bill_id": 15,
      "locked_amount": "100000000",
      "token": "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    },
    "agent": {
      "address": "0x...",
      "bill_id": 28,
      "locked_amount": "50000000",
      "token": "0x036CbD53842c5426634e7929541eC2318f3dCF7e"
    }
  },
  "receipts": [
    { "...": "array of execution receipts (see §2.1)" }
  ],
  "binding_tx": "0x... (tx hash of bind())",
  "settle_layer": 1,
  "attestation": null,
  "sealed_at": "ISO-8601",
  "sealed_by": "agent public key or EOA address"
}
```

### 4.2 Attestation Path Extension

When `bindWithAttestation()` is used, the evidence bundle includes attestation metadata:

```json
{
  "attestation": {
    "task_id": "0x...",
    "verifiers_required": 3,
    "verifiers_total": 5,
    "attestations": [
      {
        "verifier": "0x...",
        "attestation_hash": "0x...",
        "submitted_at": "ISO-8601",
        "signature": "0x..."
      }
    ],
    "gateway_tx": "0x..."
  }
}
```

### 4.3 IPFS Anchoring

Evidence bundles are stored on IPFS. The CID is hashed into `proofHash` (see §3).

```
IPFS CID → keccak256(CID bytes) → bytes32 inserted into proofHash
```

This creates a cryptographically verifiable link between the on-chain settlement
and the full audit trail stored off-chain.

---

## 5. Receipt Chain for Bilateral Bindings

Receipts within a binding are linked via `parent_receipt_id` to form an unbroken chain.

```
Receipt #1 (step_index=1)  ←  no parent
Receipt #2 (step_index=2)  ←  parent = Receipt #1
Receipt #3 (step_index=3)  ←  parent = Receipt #2
                        ...
Receipt #N (step_index=N)  ←  parent = Receipt #N-1
```

Chain integrity is verified by:
1. Checking every receipt's `parent_receipt_id` matches the preceding receipt's `receipt_id`
2. Confirming `step_index` increases monotonically
3. Validating that `input_hash(step N)` matches `output_hash(step N-1)` where applicable

---

## 6. Verify Receipt Example

### 6.1 Off-Chain Verification (Python)

```python
from karma_sdk import KarmaBilateralSDK
from karma_sdk.receipts import ReceiptVerifierV2

sdk = KarmaBilateralSDK(
    rpc_url="https://sepolia.base.org",
    contract_address="0x...",
)

verifier = ReceiptVerifierV2(sdk)

# Verify a single receipt against the on-chain binding
result = verifier.verify_receipt(
    receipt_path="./evidence/receipt_001.json",
    binding_id=42,
)

if result.valid:
    print(f"Receipt verified: proofHash={result.proof_hash.hex()}")
    print(f"Settlement layer: {result.settlement_layer}")
else:
    print(f"Verification failed: {result.errors}")
```

### 6.2 On-Chain Verification (Solidity, read-only)

```solidity
// Verify that a proofHash was submitted for a binding
KarmaBilateral.Binding memory b = karma.getBinding(bindingId);
require(b.state == KarmaBilateral.BindingState.SETTLED, "not settled");
require(b.proofHash == expectedProofHash, "proof mismatch");
```

### 6.3 Full Bundle Verification Flow

```
1. Fetch binding from KarmaBilateral.getBinding(bindingId)
2. Decompose proofHash → extract IPFS CID hash
3. Fetch evidence bundle from IPFS
4. Validate bundle structure (parties, amounts, scopeHash match)
5. Verify receipt chain integrity
6. Recompute proofHash from bundle → compare to on-chain value
7. Check settlement state (SETTLED / DISPUTED)
```

---

## 7. Compatibility with V1

V1 receipts (bill-based) can be wrapped into V2 bundles by:

```json
{
  "bundle_version": "v2.0-bilateral",
  "migration": {
    "v1_bill_id": 99,
    "v1_proof_hash": "0x...",
    "migrated_at": "ISO-8601",
    "migration_note": "Bill 99 wrapped into bilateral binding 42"
  }
}
```

This enables backward compatibility for legacy NCPA bills migrating to KarmaBilateral.

---

## 8. SDK Reference

| Adapter | Location | Description |
|---------|----------|-------------|
| `BilateralReceiptBuilder` | `karma-core/sdk/receipts/builder.py` | Build V2 receipts |
| `ReceiptVerifierV2` | `karma-core/sdk/receipts/verifier_v2.py` | Verify V2 receipts |
| `EvidenceBundleV2` | `karma-core/sdk/evidence/bundle_v2.py` | Build/seal bilateral bundles |
| `BilateralFlowSDK` | `karma-core/sdk/bilateral.py` | Full lock→bind→settle flow |

---

## See Also

- [Migration NCPA → Bilateral](./MIGRATION_NCPA_TO_BILATERAL.md)
- [Evidence Bundle Standard](./EVIDENCE_BUNDLE_STANDARD.md)
- [Proof Layer](./PROOF_LAYER.md)
- [Execution Receipt Standard V1](./EXECUTION_RECEIPT_STANDARD.md)
- [KarmaBilateral contract](../karma-core/contracts/core/KarmaBilateral.sol)
