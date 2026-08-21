# karma8 待办清单（相对主仓 Telegram MiniApp V1）

主仓已补齐 MiniApp 侧：Registry / Quote·Negotiation·Intent Package·Bill / Bot webhook / Risk·Dispute / settle→Reputation / Merchant·Developer UI。  
以下必须由 **karma8** 完成或确认，主仓不会实现国库费率 / split / NFT 铸造阈值。

---

## A. 部署与地址（阻塞联调）

- [ ] 部署并提供主网/测试网地址，写入主仓 `deploy/.env.miniapp`（或 CI secrets）：
  - `TREASURY`
  - `FEE_BRIDGE`
  - `SETTLEMENT_MIRROR`
  - `STAKE`（如启用）
  - `DEVELOPER_POOL` / `STAKER_POOL`
  - `CONTRIBUTION_NFT`
  - `CONTRIBUTOR_REGISTRY` / `CONTRIBUTION_LEDGER` / `COCREATION_SCORE_VIEW`
  - `KARMA_TOKEN` / `USDC`
  - `KARMA_BILATERAL`（主仓 Bilateral；FeeBridge.core 必须指向它）
- [ ] 导出 ABI 到主仓可消费路径，或保证 `frontend/src/lib/abis.ts` 与主仓 `services/economy_surface` / 前端嵌入一致。
- [ ] 文档化链 ID、RPC、冷启动 `feeBps=0` 策略。

## B. FeeBridge ↔ Bilateral（结算闭环）

- [ ] `FeeBridge.core == KarmaBilateral`（主仓 PR #141 已支持 `setFeeBridge` / settle→`quoteFee`+`collectAndRecord`）。
- [ ] Bilateral admin 调用：`setTreasury` + `setFeeBridge` 指向 karma8 部署地址。
- [ ] 验证：`fee=0` 时仍写入 GMV / Mirror 记录。
- [ ] `orderId` 约定：`bytes32(bindingId)`（与主仓 finalize 返回字段一致）。
- [ ] `developer` 字段：使用主仓传入的 `builder_address`（BUILDER 归因）。

## C. Settlement Mirror（GMV 规则）

- [ ] `buyer == seller` **不得**给 developer 记 GMV（自成交）。
- [ ] 正常成交：developer GMV 累计 → DeveloperRewardPool 可 claim 逻辑可用。
- [ ] 与主仓 `fee_bridge.collectAndRecord.self_deal` 语义对齐（主仓只标注，不改链上）。

## D. 经济面嵌入（`/?view=miniapp`）

- [ ] Economy host 支持 `/?view=miniapp`（或等价 query），可被主仓 iframe `GET /v1/economy/surface` 的 `embed_url` 打开。
- [ ] MiniApp 视图：余额 / claim / NFT 进度等（**不含 VerificationEngine**）。
- [ ] CORS / CSP：允许主仓 MiniApp origin 嵌入。
- [ ] `KARMA8_ECONOMY_HOST` 文档化（主仓 env）。

## E. 共创 / 激励链（若 V1 启用）

- [ ] ContributionNFT mint 阈值与 DeveloperRewardPool（70% GMV / 30% NFT）按 karma8 设计上线。
- [ ] 主仓 `docs/COCREATION_SCORE_V1.md` / `cocreation_score.v1.yaml` 的链上读接口（`COCREATION_SCORE_VIEW`）可查询。
- [ ] （可选 Phase-2）主仓 API `setSettleRep` 对接 —— 链上共创已在 karma8 时，只需读视图。

## F. revenueMode / 产品配置

- [ ] 明确 `revenueMode`（cold-start fee=0 vs 开启费率）切换开关与治理。
- [ ] 费率变更只在 karma8 Treasury/FeeBridge，**不要**要求主仓改合约常量。

## G. 联调验收（与主仓一起）

| 步骤 | 主仓 | karma8 |
|------|------|--------|
| Session + SIWE + bind | ✅ | — |
| Registry Offer → Order | ✅ | — |
| Verification PASS → finalize | ✅ | — |
| Bilateral settle → collectAndRecord | 编排返回参数 | ✅ 链上执行 |
| Mirror GMV / self-deal | 标注 self_deal | ✅ 执行规则 |
| iframe Wallet/Rewards | embed_url | ✅ `view=miniapp` |
| Bot /start deep link | webhook API | Bot Token + setWebhook |

## H. 明确不在主仓做的事（karma8 负责）

- Treasury fee bps / split 比例
- ContributionNFT mint 阈值与元数据
- Developer/Staker pool claim UI 与合约细节
- FeeBridge / Mirror 内部实现（主仓只消费）
- 完整链上 lock/settle 交易代发（可由 karma8 relayer 或前端钱包；主仓只编排状态机）

---

**主仓对接入口**：`docs/TELEGRAM_MINIAPP_MVP.md` · API 前缀 `/v1/*` · 前端 `apps/telegram_miniapp/`
