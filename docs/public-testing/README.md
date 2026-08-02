# Public testing packs

Current acceptance docs for the Bilateral + P1–P8 stack:

| Doc | Focus |
|-----|-------|
| [FULL_CHAIN_AUDIT_ACCEPTANCE-zh.md](./FULL_CHAIN_AUDIT_ACCEPTANCE-zh.md) | Full-chain audit gate |
| [CONSOLE_LAST_MILE-zh.md](./CONSOLE_LAST_MILE-zh.md) | Console wiring |
| [PHASE1_OPEN_WALLET_ACCEPTANCE.md](./PHASE1_OPEN_WALLET_ACCEPTANCE.md) | Open Wallet / EIP-712 |
| [PHASE2_X402_ACCEPTANCE.md](./PHASE2_X402_ACCEPTANCE.md) | x402 |
| [PHASE3_AP2_ACCEPTANCE.md](./PHASE3_AP2_ACCEPTANCE.md) | AP2 |
| [PUBLIC_TESTNET_GO_LIVE-zh.md](./PUBLIC_TESTNET_GO_LIVE-zh.md) | Public testnet go-live |

Run:

```bash
bash scripts/acceptance/full_chain_audit_gate.sh
python3 scripts/acceptance/adversarial_whole_project_suite.py
```
