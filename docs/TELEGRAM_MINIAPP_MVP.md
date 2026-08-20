# Telegram MiniApp ↔ karma8 alignment (main repo)

Source of truth: karma8 `integrations/telegram-miniapp/KARMA_MAIN_HANDOFF.md` + V1.0 product flow.

## Boundary

| Main repo | karma8 |
|-----------|--------|
| Bot / MiniApp / initData / SIWE / Session | FeeBridge / Treasury / pools / NFT |
| Discovery / Registry / Order / Quote / Bill | `/?view=miniapp` economy UI |
| Evidence / **VerificationEngine** / Risk / Dispute | GMV mirror / rewards claim |
| settle → Reputation (off-chain surface) | on-chain cocreation / claim |

**Do not** implement in main: fee bps setters, treasury split, ContributionNFT mint thresholds.

karma8 待办清单见：[`KARMA8_REMAINING_CHECKLIST.md`](./KARMA8_REMAINING_CHECKLIST.md)。

## Settlement wiring

1. `KarmaBilateral.setTreasury` / `setFeeBridge` (PR #141)
2. settle → `quoteFee` + `collectAndRecord` (fee=0 still records GMV)
3. `FeeBridge.core == Bilateral`
4. `developer` = BUILDER attribution (`order.builder_address`)
5. `orderId` = `bytes32(bindingId)`
6. Verification **PASS** required before finalize; Risk **hold** blocks settle
7. `buyer==seller` → Mirror skips developer GMV (karma8)

## Env

```bash
TELEGRAM_BOT_TOKEN=
TELEGRAM_BOT_USERNAME=
TELEGRAM_WEBHOOK_SECRET=
TELEGRAM_MINIAPP_URL=
KARMA8_ECONOMY_HOST=https://<economy-host>
TREASURY= FEE_BRIDGE= SETTLEMENT_MIRROR= STAKE=
DEVELOPER_POOL= STAKER_POOL= CONTRIBUTION_NFT=
CONTRIBUTOR_REGISTRY= CONTRIBUTION_LEDGER= COCREATION_SCORE_VIEW=
KARMA_TOKEN= USDC= KARMA_BILATERAL=
```

ABI: karma8 `frontend/src/lib/abis.ts`.

## API surface (main)

```text
# Auth
POST /v1/telegram/session
POST /v1/auth/siwe/challenge|verify
POST /v1/telegram/bind
POST /v1/identity/policy
POST /v1/telegram/bot/webhook
GET  /v1/telegram/bot/deeplink

# Registry
POST /v1/registry/businesses|agents|capabilities|offers
GET  /v1/registry/businesses|agents|capabilities|offers

# Commerce
POST /v1/chat/intent
GET  /v1/discovery/offers
POST /v1/commerce/quotes
POST /v1/commerce/negotiations[/propose|/agree]
POST /v1/commerce/orders
POST /v1/commerce/orders/sign|policy-check
POST /v1/commerce/intent-packages[/sign]
GET  /v1/commerce/bills/{order_id}

# Trust + settle
POST /v1/settlement/lock|finalize
POST /v1/evidence/bundles
POST /v1/risk/assess
POST /v1/verification/runs
POST /v1/disputes[/resolve]
GET  /v1/miniapp/reputation/{identity_id}
GET  /v1/activity/history
GET  /v1/economy/surface
```

Frontend: `apps/telegram_miniapp/`（Chat / Activity / Identity / Merchant / Developer / Wallet）.
