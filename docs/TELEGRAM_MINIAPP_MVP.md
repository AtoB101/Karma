# Telegram MiniApp ↔ karma8 alignment (main repo)

Source of truth: karma8 `integrations/telegram-miniapp/KARMA_MAIN_HANDOFF.md`.

## Boundary

| Main repo | karma8 |
|-----------|--------|
| Bot / MiniApp / initData / SIWE / Session | FeeBridge / Treasury / pools / NFT |
| Discovery / Order / Evidence / **VerificationEngine** | `/?view=miniapp` economy UI |
| Bilateral settle orchestration | GMV mirror / rewards claim |

**Do not** implement in main: fee bps setters, treasury split, ContributionNFT mint thresholds.

## Settlement wiring

1. `KarmaBilateral.setTreasury` / `setFeeBridge` (PR #141)
2. settle → `quoteFee` + `collectAndRecord` (fee=0 still records GMV)
3. `FeeBridge.core == Bilateral`
4. `developer` = BUILDER attribution (`order.builder_address`)
5. `orderId` = `bytes32(bindingId)`
6. Verification **PASS** required before finalize
7. `buyer==seller` → Mirror skips developer GMV (karma8)

## Env

```bash
TELEGRAM_BOT_TOKEN=
KARMA8_ECONOMY_HOST=https://<economy-host>
TREASURY= FEE_BRIDGE= SETTLEMENT_MIRROR= STAKE=
DEVELOPER_POOL= STAKER_POOL= CONTRIBUTION_NFT=
CONTRIBUTOR_REGISTRY= CONTRIBUTION_LEDGER= COCREATION_SCORE_VIEW=
KARMA_TOKEN= USDC= KARMA_BILATERAL=
```

ABI: karma8 `frontend/src/lib/abis.ts`.

## MVP API

```text
POST /v1/telegram/session
POST /v1/auth/siwe/challenge|verify
POST /v1/telegram/bind
POST /v1/chat/intent
GET  /v1/discovery/offers
POST /v1/commerce/orders
POST /v1/verification/runs      # PASS gate
POST /v1/settlement/lock|finalize
GET  /v1/economy/surface
```

Frontend: `apps/telegram_miniapp/`.
