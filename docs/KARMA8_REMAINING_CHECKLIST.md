# karma8 待办清单（相对主仓 Telegram MiniApp V1）

主仓代码侧（Verify PASS → Bilateral settle → quoteFee/collectAndRecord、Registry、Bot、经济面 BFF）已就绪。  
下列为 **karma8 + 运维** 仍需完成项（私钥/域名/部署主仓 Agent 无法代劳）。

主仓运维勾选见：`docs/MAIN_OPS_CHECKLIST.md` · 接线脚本：`deploy/wire_feebridge.sh`

---

## A. 部署与地址（阻塞联调）

- [ ] 部署并写入双方 env（`deployments/<network>.json`）：
  - `TREASURY` · `FEE_BRIDGE` · `SETTLEMENT_MIRROR` · `STAKE`
  - `DEVELOPER_POOL` / `STAKER_POOL` · `CONTRIBUTION_NFT`
  - `CONTRIBUTOR_REGISTRY` / `CONTRIBUTION_LEDGER` / `COCREATION_SCORE_VIEW`
  - `KARMA_TOKEN` / `USDC` · `KARMA_BILATERAL`
- [ ] ABI 对齐 `frontend/src/lib/abis.ts`
- [ ] 文档化 chainId / RPC / 冷启动 `feeBps=0`

## B. FeeBridge ↔ Bilateral

- [ ] `FeeBridge.core == KarmaBilateral`（DeployEconomy `KARMA_CORE_ADDRESS`）
- [ ] 主仓 admin 执行：`setTreasury` + `setFeeBridge`（`deploy/wire_feebridge.sh`）
- [ ] `make verify-wiring` / karma8 `verify_wiring.sh` → RESULT: OK
- [ ] 冷启动 `enableRevenueMode=false`；fee=0 仍 collectAndRecord

## C. Settlement Mirror

- [ ] `buyer == seller` 不给 developer 记 GMV
- [ ] 正常成交 developer GMV → DeveloperRewardPool claim 可用

## D. 经济面嵌入

- [ ] HTTPS `economy.<domain>` + `/?view=miniapp`
- [ ] `MINIAPP_ORIGIN` 含 Telegram + 主仓 MiniApp origin（主仓 BFF 返回 `miniapp_origin_for_karma8`）
- [ ] CSP `frame-ancestors` / CORS
- [ ] 主仓设 `KARMA8_ECONOMY_HOST`

## E–F. 共创 / revenueMode

- [ ] NFT mint / pools（karma8）
- [ ] 观察期后再开 `enableRevenueMode`

## G. 联调验收

| 主仓 | karma8 / ops |
|------|----------------|
| Session → Verify PASS → finalize `settle_plan` | Bilateral settle 上链 |
| `orderId=bytes32(bindingId)` · `developer=builder` | FeeBridge + Mirror |
| iframe embed_url | `view=miniapp` 可见 |
| Bot webhook API | Token + setWebhook |

## H. 不在主仓做

Treasury fee/split · NFT mint 阈值 · FeeBridge/Mirror 内部 · 经济合约 claim 细节
