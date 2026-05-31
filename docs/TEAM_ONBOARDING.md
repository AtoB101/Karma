# Karma Testnet — Team Onboarding Guide

Connect your OpenClaw or OpenManus agent to KarmaBilateral in 5 minutes.

## 1. Get Test USDC

```bash
# From any team machine:
curl -X POST http://<BFF_HOST>:8822/faucet/0xYourSepoliaAddress
```

Or use the faucet script:
```bash
python3 scripts/faucet.py 0xYourAddress --amount 100
```

## 2. Configure Your Agent

### OpenClaw (MCP)

Add to your OpenClaw agent config:

```json
{
  "mcpServers": {
    "karma-bilateral": {
      "command": "python3",
      "args": ["-m", "karma_mcp"],
      "env": {
        "KARMA_RPC_URL": "https://sepolia.infura.io/v3/YOUR_KEY",
        "KARMA_PRIVATE_KEY": "YOUR_TESTNET_PRIVATE_KEY",
        "KARMA_CONTRACT": "0x496d178a5D32E9410E52bD5800602BDEe81B2A91",
        "KARMA_USDC": "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF"
      }
    }
  }
}
```

Then your OpenClaw agent can call:
- `karma_lock` — Lock 10 USDC, get Bill Token
- `karma_bind` — Pair your bill with counterparty
- `karma_settle` — Prove delivery, release funds
- `karma_get_binding` — Check binding status

### OpenManus

```python
from karma_openmanus import KarmaBffClient

USDC = "0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF"

client = KarmaBffClient(
    base_url="http://<BFF_HOST>:8822",
    secret="karma-team-test-2026"
)

# Pre-authorize: lock 10 USDC as agent
result = await client.bilateral_lock(USDC, 10_000_000, role="agent")
print(f"Bill #{result['bill_id']} — {result['state']}")

# Query status
status = await client.bilateral_status(binding_id=1)
print(f"Binding: {status['state']}, can_settle: {status['can_settle']}")
```

## 3. Contract Addresses (Sepolia)

| Contract | Address |
|----------|---------|
| KarmaBilateral | `0x496d178a5D32E9410E52bD5800602BDEe81B2A91` |
| mUSDC | `0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF` |

## 4. Quick Test

```bash
# Check contract is live
curl http://<BFF_HOST>:8822/health

# Query binding #1
curl http://<BFF_HOST>:8822/v1/bilateral/status/1
```

## 5. Operation Flow

```
1. Both parties: karma_lock(USDC, amount)         → Bill Token MINTED
2. Buyer:        karma_bind(buyerBill, agentBill)  → Binding ACTIVE
3. Wait settle delay (configurable)
4. Either party: karma_settle(bindingId, proof)    → FINALIZING
5. Wait 24h dispute window
6. Anyone:       karma_finalizeSettle(bindingId)   → SETTLED

Optional:
- karma_dispute(bindingId, reason) during FINALIZING
- karma_unlock(billId) before bind to cancel
```

## Need Help?

- Contract explorer: https://sepolia.etherscan.io/address/0x496d178a5D32E9410E52bD5800602BDEe81B2A91
- Full docs: https://github.com/AtoB101/Karma/tree/main/docs
- 15-min quickstart: docs/QUICKSTART_15MIN.md
