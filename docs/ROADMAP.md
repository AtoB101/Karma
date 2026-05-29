# Roadmap

Karma is building the accountability layer for autonomous commerce, starting with proof receipts for paid agent actions.

This roadmap describes the staged evolution from **proof layer** → **verification network** → **settlement & reputation economy**.

---

## Current: Proof Layer (Phase 0–1) ✅

**Status: Available now**

Core proof primitives for agent actions:

- ✅ Execution Receipts — signed, hashable records of agent/tool/API calls
- ✅ Evidence Bundles — portable audit packages with receipts + payment refs + metadata
- ✅ Verification API — structural checks on receipts and bundles
- ✅ OpenClaw MCP Proof Plugin — stdio MCP server for OpenClaw runtimes
- ✅ OpenManus HMAC Client — proof client for OpenManus agents
- ✅ Python SDK + TypeScript SDK
- ✅ x402 payment reference integration
- ✅ AP2 authorization intent reference

> **Focus:** Get developers generating real receipts and bundles. Build adoption data.

---

## Next: Verification Network (Phase 2–3) 🔄

**Status: In development**

Decentralized proof verification and advanced integrations:

- 🔄 N-of-M attestation gateway (contract ready, deployment pending)
- 🔄 x402 hybrid settlement — proof-linked API payments on Sepolia
- 🔄 AP2 mandate evidence — scope verification against payment intents
- 🔄 Solana SDK with Merkle anchor proofs
- 📋 Multi-verifier node deployment (target: 5 nodes, 3-of-5 threshold)
- 📋 Verifier reputation tracking on-chain
- 📋 Open verification — third-party verifiers can join and attest

> **Focus:** Open verification to independent verifiers. Build the trust layer.

---

## Future: Settlement & Reputation Economy (Phase 4–5) 📋

**Status: Planned**

Full agent commerce infrastructure:

- 📋 Decentralized verifier staking and slashing
- 📋 Protocol fees for verification services
- 📋 Agent reputation from verified execution data
- 📋 Dispute resolution with evidence-based arbitration
- 📋 Multi-chain proof anchoring (EVM + Solana + more)
- 📋 Policy-as-code governance for verifier networks
- 📋 CLI tools for one-command proof generation
- 📋 Public benchmarks for verification throughput

> **Focus:** Scale verification network into a self-sustaining reputation and settlement economy.

---

## Design Principles

1. **Proof first, network second.** Build usage before network effects.
2. **Complement, don't compete.** Work with x402, AP2, MCP — don't replace them.
3. **Real data drives token utility.** Token mechanisms emerge from verified usage, not speculation.
4. **Open verification, not closed trust.** Anyone can verify proofs independently.

---

## Phase Timeline

```
Proof Layer ──────── Verification Network ──────── Settlement Economy
   (now)                 (next 3-6 months)             (6-18 months)

Receipts + Bundles    N-of-M attestation           Verifier staking
Verification API      Third-party verifiers         Reputation network
MCP Plugin            x402/AP2 deep integration     Dispute arbitration
SDK (Python + TS)     Solana proofs                 Multi-chain
```

---

## See Also

- [Proof Primitives](./PROOF_LAYER.md) — Deep dive on receipts, bundles, verification
- [Integrations](./INTEGRATIONS.md) — How Karma fits with x402, AP2, MCP, OpenClaw
- [API Reference](./API_REFERENCE.md) — Full endpoint documentation
