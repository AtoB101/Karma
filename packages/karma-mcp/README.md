# karma-mcp

MCP stdio server for **KarmaBilateral** — bilateral lock, bind, and settle for AI agent payments.

---

## Install

```bash
pip install ./packages/karma-mcp
# or dev mode:
pip install -e ./packages/karma-mcp
```

## Run

```bash
export KARMA_RPC_URL=https://mainnet.base.org
export KARMA_PRIVATE_KEY=0x...
export KARMA_CONTRACT=0xKARMA_BILATERAL_ADDRESS

karma-mcp
```

## MCP tools

| Tool | Purpose |
|---|---|
| `karma_lock` | Lock USDC → mint Bill Token (SBT) |
| `karma_bind` | Bilaterally bind buyer + agent bills → Binding |
| `karma_settle` | Burn both bills, release USDC atomically |
| `karma_unlock` | Withdraw MINTED (unbound) bill before binding |
| `karma_get_bill` | Read Bill Token state |
| `karma_get_binding` | Read Binding state |
| `karma_check_invariant` | Verify totalBillSupply == totalLocked on-chain |

## Protocol flow

```
[Buyer]                          [Agent]
  │                                 │
  ├─ karma_lock(USDC, 100e6)        ├─ karma_lock(USDC, 50e6)
  │  → bill_id = 1 (MINTED)         │  → bill_id = 2 (MINTED)
  │                                 │
  ├─ karma_bind(1, 2, scope_hash) ──┘
  │  → binding_id = 1
  │  Both bills: MINTED → BOUND (frozen)
  │
  │  ... task executes ...
  │
  ├─ karma_settle(1, proof_hash)
     Both bills: BOUND → BURNED
     USDC released atomically to each owner
```

## Bill Token lifecycle

```
MINTED  →  karma_bind()  →  BOUND  →  karma_settle()  →  BURNED
   ↓                           ↓
karma_unlock()          karma_dispute() → DISPUTED → resolveDispute()
(reclaim before bind)   karma_refund_on_timeout() → REFUNDED
```

**BOUND bills are frozen.** They cannot be withdrawn, transferred, or re-bound until the Binding reaches a terminal state (SETTLED / REFUNDED).

## Global invariant

At every block:

```
totalBillSupply[token] == totalLocked[token]
```

Verify anytime with `karma_check_invariant`.

## Environment variables

| Variable | Required | Description |
|---|---|---|
| `KARMA_RPC_URL` | ✅ | JSON-RPC endpoint |
| `KARMA_PRIVATE_KEY` | ✅ | Hex private key (0x-prefixed) |
| `KARMA_CONTRACT` | ✅ | KarmaBilateral contract address |
| `KARMA_GAS` | ⬜ | Gas limit per tx (default 300000) |

## Claude Desktop config example

```json
{
  "mcpServers": {
    "karma": {
      "command": "karma-mcp",
      "env": {
        "KARMA_RPC_URL":      "https://mainnet.base.org",
        "KARMA_PRIVATE_KEY":  "0x...",
        "KARMA_CONTRACT":     "0x..."
      }
    }
  }
}
```
