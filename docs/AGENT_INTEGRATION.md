# Agent integration (public boundary)

## Principles

1. **Agent runtimes** (OpenManus, OpenClaw, Hermes, custom) own orchestration and tool execution.  
2. **KARMA** owns trust artifacts: receipts, evidence bundles, settlement mapping, and public verification surfaces.  
3. **Private** scoring, fraud, and dispute weights live in a **separate private repository** — never ship them in public SDKs.

## Integration steps

1. Record execution steps into **ExecutionReceipt**-compatible payloads (`trusted_agent_runtime/schemas.py`).  
   - SDK adapters are available in `sdk/adapters.py` for API/MCP/Agent Runtime/AI-Workflow templates.
   - For MCP calls, prefer `MCPExecutionAdapter.build_verification_template(...)` to emit normalized `mcp-v2` verification fields.
   - **OpenManus (BFF path):** install `packages/karma-openmanus` and call `KarmaBffClient` from server-side tool handlers (see `packages/karma-openmanus/README.md`).
   - **OpenClaw (MCP path):** install `packages/karma-openclaw`, run `karma-openclaw-mcp`, attach OpenClaw’s MCP bridge (stdio); see `packages/karma-openclaw/README.md` and **`docs/OPENCLAW_P1_DUAL_AGENT.md`** (P1: verify/delivery automation; voucher accept/create remain **Console manual**).
2. Build **EvidenceBundle** + `proofHash` mapping (`trusted_agent_runtime/evidence_adapter.py`).  
3. Call **structural verification** before proposing settlement (`trusted_agent_runtime/verification.py`).  
4. Submit on-chain actions through **existing** `NonCustodialAgentPayment` flows (`docs/TESTNET_RUNBOOK.md`).

## HTTP API (sketch)

See `openapi/karma-public-console-api.yaml` for public routes. Implementations must add authentication, signing, replay
protection, and rate limits server-side.
