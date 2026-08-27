# Karma Financial Security Registry — 信任边界与攻击面图谱

登记表：`financial_functions.yaml`（39 个合约函数 + 7 个后端函数 + 10 条不变量 + 资金状态超时表）。
本文是图谱层速览，供审核与后续 Control Plane 消费。

## 资金信任边界（谁能做什么，不能做什么）

| 角色 | 能做 | 不能做 |
|---|---|---|
| 用户（buyer/agent） | lock 自己的资金、bind、dispute、refundOnTimeout、unlock、authorize | 动别人的资金 |
| Verifier | submitAttestation、publishEvidence、raiseChallenge | 直接触发 payout（只能积累 quorum/发起阻断） |
| Gateway 合约 | 在 quorum + 无 challenge + 绑定匹配时代为 settle | 绕过 Bilateral 的状态机与守卫 |
| Arbitrator（链下） | 调 /disputes/resolve 提交仲裁结果 | 直接动链上资金（必须走 admin 多签的 resolveDispute） |
| Backend/API | 提交结算/退款交易、跑超时 sweep | 持有用户资金、绕过合约守卫、单方改金额/收款人 |
| Admin（多签） | 改资金规则参数、resolveDispute、resolveChallenge | 提取用户锁定资金、暂停退款路径、无限期冻结（freeze 有时效） |
| Security Control Plane | 监控、告警、触发链上 freeze | 直接执行任何资金转移 |

**资金出口只有 5 条**：settle / finalizeSettle / refundOnTimeout / resolveDispute(auto) / unlock。
任何新增出口都必须：登记 registry → 不变量测试 → 攻击矩阵追加 → 用户审核合并。

## 攻击面登记（入口 → 指向的资金函数）

1. 合约直接调用（任何人）→ lock/bind/settle/finalizeSettle/dispute/refundOnTimeout/autoResolve
2. Gateway attestation 通道 → settleWithAttestation（P0-1/P0-2 已封）
3. TEE/ZK 证明通道 → settleWithTEE / settleWithZKProof
4. 后端 API（session 劫持）→ 订单锁款/确认/争议/履约状态机
5. 仲裁 API（arbitrator 凭据）→ /disputes/resolve（P1-3 白名单已封）
6. 后端服务密钥（热钱包）→ lock_funds/release/refund（P1-6 守卫 + 合约二次校验）
7. admin 密钥 → 参数/费率/仲裁（多签部署断言 P1-5；freeze 时效待 Phase 2）
8. admin 不作为（不仲裁、不解冻）→ 超时兜底路径（P2-7/P2-8 已补）
9. **JWT 信任根泄露（红队 §A1）** → 伪造任意 agent_id/伪 admin（P0，待 KMS 化）
10. **Sybil 刷分（红队 §A4）** → 高信誉身份骗取真实 escrow（P1，待 SBT 铸造门槛）
11. **仲裁凭据被盗批量滥用（红队 §A2）** → 大额争议判给攻击方（已补审计/告警）
12. **admin 多签单点（红队 §A3）** → setFeeBridge 吸血 10%（多签阈值待固化）

> 红队评估全文：`security/redteam/2026-08-27-redteam-assessment.md`

## 资金状态超时表（摘要）

每态必有时效，到期去向唯一：

- LOCKED(未绑定) → owner unlock
- BOUND → settle_timeout → **买家全额退款**
- SETTLE_PENDING → finalize 窗口 → **任何人 finalizeSettle**
- DISPUTED → 大额超时 → **autoResolveArbitration 规则分账**
- FROZEN（Phase 2）→ freeze_duration → **自动解冻回冻结前状态，走既有超时路径**

核心原则：admin 失联 / 后端宕机 / 监控失效，任何一态的资金都能凭时间+状态机走到终点，不存在无限期悬置。

## 维护规则（永久机制）

新增任何涉及资金的函数/合约/Agent/支付方式时：
1. 在 `financial_functions.yaml` 登记条目（risk_level 按定义分级）
2. 新函数必须映射到 10 条不变量之一或申请新不变量并加测试
3. Phase 3 的 Control Plane 将按 registry 的 `audit_event` 与 `emergency_action` 字段自动接入监控与冻结策略——**不登记 = 不被监控 = 不允许合入 main**
