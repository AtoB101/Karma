# Karma 真实场景可运行闭环 v1

> 脚本：`scripts/acceptance/real_commerce_scenario_loop.py`  
> 一键：`bash scripts/acceptance/real_commerce_scenario_loop.sh`

## 完成度（诚实评估）

| 维度 | 完成度 | 说明 |
|------|--------|------|
| 协议标准（边界/确认/字段/接入） | **~90%** | 目录与 API 齐备 |
| 接入 → 发布边界 → 可发现 | **~85%** | 模板接入完整；plain connect 会标 incomplete |
| 主人确认 Yes/No | **~80%** | 已加固；会话落盘单机可测，多实例仍需 Redis/DB |
| Important Fields 进履约脊柱 | **~80%** | fulfill 强制 MATCHED（商务场景）；生产应双方真实密文提交 |
| Voucher → 结算 SETTLED | **~70%** | 脊柱可通；`auto_complete` 为合成完单，非线下验真 |
| 卖方确认 TTL / 违约责任 (P6) | **~70%** | 超时取消+未确认档案+责任金 |
| 交付验真 (P7) | **~65%** | 三方物流+防伪标签+30min 默认确认；票务 stub；issuer API 后期 |
| 结算信誉 (P8) | **~70%** | 行业差异化结算+加密可查证明+Agent 代验；链上 attestation 后期 |
| OpenClaw / 链上默认 | **~35%** | 旁路可选，未强制 |
| 生产多实例 / 链上结算默认 | **~40%** | 仍有 sidecar/demo 软默认 |
| **真实场景可测试闭环（本脚本）** | **~75%** | 可本地无 Docker 跑通 5 大场景 |
| **生产级商业闭环** | **~55–60%** | 差持久化集群、真实交付证明、强制卖方门闩、链上默认 |

**一句话：** 协议交付脊柱约 **75%** 可做真实场景测试；生产级全闭环约 **55–60%**。

## 本脚本覆盖的闭环

```text
商家 connect-from-template（能力/责任/确认边界）
  → 用户 agent 接入
  → fulfill-intent → awaiting_owner_confirmation
  → 主人 decide confirm=true
  → Important Fields 三方 MATCHED（开发可用 auto_lock）
  → 卖方确认（OWNER_CONFIRM 场景）/ 超时取消（P6）
  → 确认后武装违约责任 → voucher accept
  → 交付验真 VERIFIED（实物三方 / 票务回执 / 数字回执）
  → settlement → SETTLED + P8 加密可查 attestation / 场景信誉
```

场景：`food_delivery` / `ride_hailing` / `hotel_booking` / `flight_booking` / `b2b_procurement`

## 运行

```bash
# 无需 Docker / Postgres
bash scripts/acceptance/real_commerce_scenario_loop.sh

# 子集
python3 scripts/acceptance/real_commerce_scenario_loop.py --scenes food_delivery,ride_hailing
```

HTTP 联调（需自行起 API + DB，见 `docs/GETTING_STARTED.md`）时，等价步骤：

1. `POST /v1/agents/connect-from-template`
2. `POST /v1/orchestration/fulfill-intent` → 看 `owner_prompt_zh`
3. `POST /v1/confirmations/sessions/{id}/decide` `{"confirm":true,"actor_agent_id":"..."}`
4. Important Fields capture → submit-encrypted → match-secure  
   （或开发环境 `auto_lock_important_fields=true`）
5. 再 `fulfill-intent` + `confirmation_session_id` + `important_fields_capture_id` + `auto_complete=true`

## 仍未完成（优先级）

1. 确认会话 / IF capture **多实例持久化**（Redis/DB）  
2. fulfill 默认走**真实买方验收**，弱化合成 `auto_complete`  
3. 票务 issuer API / 冷链温度 / 封签 NFC 生产接入；P7 已覆盖三方物流主路径  
4. Discovery **仅** Karma 已连接且 `boundary_complete` 的商家（关掉 demo 商家默认）  
5. 链上结算与生产 env 硬默认对齐  
