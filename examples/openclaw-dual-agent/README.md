# OpenClaw dual-agent example (buyer + seller)

Two OpenClaw processes (or two MCP configs) cooperate on one `task_id` after **humans finish authorization in Karma Console**.

## Layout

| File | Purpose |
|------|---------|
| `buyer.env.example` | Buyer `KARMA_API_KEY`, optional `KARMA_RUNTIME_KEY` |
| `seller.env.example` | Seller keys |
| `handoff.template.json` | Fill after Console steps; point `KARMA_OPENCLAW_HANDOFF_PATH` here |

## Flow

1. **Console (both parties)** — lock → buyer create voucher → seller **accept** → contract + settlement create.  
2. Edit `handoff.json` from template; set `voucher_id`, identities, `manual_console_steps_completed`.  
3. **Seller Claw** — `export KARMA_OPENCLAW_HANDOFF_PATH=./handoff.json`  
   - `karma_validate_handoff`  
   - `karma_settlement_lock` → `karma_settlement_start`  
   - `karma_build_execution_receipt_step` → `karma_submit_execution_receipt` (or `karma_runtime_submit_receipt`)  
   - `karma_settlement_submit_delivery`  
4. **Buyer Claw** — same handoff file (read-only checks OK)  
   - `karma_submit_verification`  
   - `karma_settlement_buyer_accept` only if `KARMA_OPENCLAW_ALLOW_BUYER_ACCEPT=true` after Console click  

Full reference: `docs/OPENCLAW_P1_DUAL_AGENT.md`

## MCP command

```bash
pip install -e ../../packages/karma-openclaw
set -a && source buyer.env && set +a   # or seller.env
karma-openclaw-mcp
```
