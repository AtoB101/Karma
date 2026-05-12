#!/usr/bin/env bash
# Legacy demo: the LockPoolManager / BillManager forge stack was removed when aligning
# with the current contract layout (NonCustodialAgentPayment). Use Trusted Agent + testnet docs instead.
set -euo pipefail
echo "This script is deprecated after merge with main."
echo "  - Offchain Trusted Agent: python3 scripts/trusted_agent_minimal_flow.py"
echo "  - Testnet / hybrid:        docs/TESTNET_RUNBOOK.md"
echo "  - Contracts:               forge test (see foundry.toml contracts paths)"
exit 1
