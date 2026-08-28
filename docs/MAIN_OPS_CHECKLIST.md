# 主仓运维清单（对齐 karma8 KARMA_MAIN_HANDOFF + USER_OPS_CHECKLIST）

来源：
- https://github.com/AtoB101/karma8/blob/cursor/telegram-go-live-e9e8/integrations/telegram-miniapp/KARMA_MAIN_HANDOFF.md
- USER_OPS_CHECKLIST.md（域名 / Bot Token / 私钥只能人工完成）

---

## 一、链上接线（阻塞联调）— 代码已就绪，部署后执行

| 项 | 状态 |
|----|------|
| `setTreasury` / `setFeeBridge`（PR #141） | ✅ 合约已有 |
| settle 内 `quoteFee` → `collectAndRecord`（fee 精确等于 quote） | ✅ `_collectEconomyFee` |
| 冷启动 fee=0 仍 `collectAndRecord` 记 GMV | ✅ |
| `orderId = bytes32(bindingId)` | ✅ |
| `developer = builder`（`setBindingDeveloper`；默认 seller） | ✅ 本轮补齐 |
| 接线脚本 | `deploy/wire_feebridge.sh` |

**部署后人工执行：**

```bash
# 地址从 karma8 deployments/<network>.json 读取
export RPC_URL=... PRIVATE_KEY=<bilateral-admin>
export KARMA_BILATERAL= TREASURY= FEE_BRIDGE= SETTLEMENT_MIRROR=
bash deploy/wire_feebridge.sh
# 确认 FeeBridge.core == Bilateral
```

字段约定（BFF 已返回 `settle_plan`）：

- `orderId = bytes32(bindingId)`（禁止重放）
- `developer = builder_address`（lock/finalize 提示 `setBindingDeveloper`）
- `buyer==seller` → `self_deal=true`；勿当正常 GMV 业务

---

## 二、业务（主仓代码）

| 优先级 | 内容 | 状态 |
|--------|------|------|
| 必须 | SIWE + Identity + Session | ✅ |
| 必须 | Bot + MiniApp + initData 服务端验签 | ✅ |
| 必须 | Discovery → Quote/Order → 双方签名 | ✅ |
| 必须 | Evidence + VerificationEngine；仅 PASS 才 settle | ✅ |
| 必须 | Policy（限额/类目/Agent allowlist）；无无限 approve | ✅ |
| 建议 | Reputation；经济面嵌入 | ✅ |

---

## 三、Telegram / 经济面嵌入（需运维填 env）

```bash
KARMA8_ECONOMY_HOST=https://economy.<your-domain>
MINIAPP_ORIGIN=https://web.telegram.org,https://webk.telegram.org,https://webz.telegram.org,https://<miniapp-host>
TELEGRAM_BOT_TOKEN=          # 勿进 git
TELEGRAM_WEBHOOK_SECRET=
# + TREASURY FEE_BRIDGE … 见 deploy/.env.miniapp.example
```

- Wallet/Rewards iframe：`https://<economy-host>/?view=miniapp`（可选 `&tab=rewards`）
- BFF：`GET /v1/economy/surface`（字段对齐 karma8 `economy-surface.example.json`）
- Bot：`setWebhook` 指向主仓 `/v1/telegram/bot/webhook`
- 把 `miniapp_origin_for_karma8` 告诉 karma8 写入 `MINIAPP_ORIGIN`

---

## 四、验收（主仓视角）

```text
□ TG 打开 MiniApp → Session 识别
□ 下单 → Evidence → Verify PASS → Bilateral settle
□ FeeBridge 成功；Mirror 有账单；冷启动 fee=0
□ self_deal：developer GMV 不涨
□ 经济面 iframe 可打开并显示状态
```

---

## 五、明确不要在主仓做

- Treasury 费率 / 分账常量
- NFT mint 阈值、池子 claim 细节
- FeeBridge / Mirror 内部实现
- Verification 之外的经济合约逻辑

---

## 给主仓 Agent 的一句话（已落实）

Verify PASS 后才 Bilateral settle；settle 用 quoteFee 精确值调用 FeeBridge.collectAndRecord；
setTreasury+setFeeBridge；orderId=bytes32(bindingId)；developer=builder；
冷启动 fee=0 仍 collectAndRecord。MiniApp Wallet/Rewards 嵌入 karma8 `/?view=miniapp`。
