# Karma 使用说明书

> 面向使用者：从「打开操作台」到「agent 之间完成结算」的完整流程。
> 操作台 = Cyber Console（`apps/console/pages/cyber/index.html`）。

---

## 1. Karma 是什么

Karma 是面向 **AI agent 之间（M2M）** 的非托管结算协议：

- 买家锁 **USDC** → 铸造 1:1 内部责任额度（Bill）
- 买卖双方 **bind** 账单 → 交付验证 → **settle** → 销毁额度、释放 USDC
- 核心不变量：`totalBillSupply == totalLocked`（永远 1:1 锚定）

一个钱包 = 一个 **master 身份卡** + **N 个身份档案**（个人/商家/企业/验证者/仲裁员），每个档案可独立发 agent key、独立记账、独立可见性。

---

## 2. 完整用户流程（操作台）

### ① 连接钱包 · 认证
1. 打开操作台 → 左侧导航「🔑 认证」页。
2. 点「连接钱包 · 认证」→ MetaMask 签名（SIWE）。
3. 认证成功后自动领取 **master 身份卡**（返回 identity_id）。
4. 点「🎫 领取身份卡」→ 查看你的身份卡（Identity ID / Class / Verification / Status）。

### ② 创建身份档案（一卡多身份）
1. 左侧导航「身份」页 → 「身份档案管理」。
2. 选 class（individual / merchant / enterprise / verifier / arbitrator）+ 填 display name → 点「创建档案」。
   - **enterprise（企业）默认 `visibility=private`（涉密）**，其余默认 public。
3. 档案会出现在**侧边栏「身份档案切换器」**里。

### ③ 一键切换身份
- 侧边栏下拉框选择档案 → 即切换。
- 切到 **enterprise（private）** 档案时，右上角出现「🔒 涉密 · CONFIDENTIAL」徽标，金额自动模糊。

### ④ 授权披露（企业涉密 · 只给授权方看明细）
1. 选中企业档案 → 身份页「授权披露」填「授权方 identity」+ scope（`transaction` 逐笔 / `ledger` 整本）。
2. 授权后，被授权方才能查 `GET /v1/identity/role-profiles/{profile_id}/ledger` 看到被披露的明细。

### ⑤ KYC（认证资料）
1. 身份页「提交 KYC」→ kyc_status 变 `pending`。
2. 验证者（class=verifier 的档案）调用 verify → `verified` / `rejected`。

### ⑥ 锁仓 USDC（额度）
- 顶部「增加锁仓额度」输入金额 → 锁仓，可用额度进入 capacity 账本。
- 真链模式下，settlement 的 lock 步骤会触发链上锁仓（需钱包已 approve + 有 USDC）。

### ⑦ 给 agent 发 Runtime Key（绑定身份卡）
1. 设置页（Settings）→ 保存「自动授权策略」（单笔/日限额 + 权限）。
2. 点「钱包签名铸造 Runtime Key」→ **key 会绑定当前选中的档案（profile_id）**。
3. 把 `KARMA_RUNTIME_KEY` 交给 agent 进程。

### ⑧ agent 之间结算（M2M）
- 买方 agent（持 Runtime Key）创建 voucher → 卖方验证 → 锁仓 → 交付 → 回执 → 结算 → 链上 finalize → USDC 到账。

---

## 3. API 概览（主要端点）

| 模块 | 端点 | 说明 |
|---|---|---|
| 身份档案 | `POST/GET /v1/identity/role-profiles` | 创建 / 列表（private 对非 owner 脱敏） |
| | `GET/PUT /v1/identity/role-profiles/{id}` | 单查 / 更新（仅 owner） |
| 身份卡 | `GET /v1/identity/{identity_id}/card` | 读取 master 身份卡 |
| 授权披露 | `POST/GET/DELETE /v1/identity/role-profiles/{id}/disclosures` | 授权 / 列出 / 撤销（owner） |
| 台账 | `GET /v1/identity/role-profiles/{id}/ledger` | 档案明细（private 需授权） |
| KYC | `POST /v1/identity/role-profiles/{id}/kyc` | 提交 KYC（owner） |
| | `POST /v1/identity/role-profiles/{id}/kyc/verify` | 验证（verifier 档案） |
| 锁仓 | `POST /v1/capacity/{identity_id}/lock` | 锁仓额度（可带 profile_id） |
| | `POST /v1/capacity/{identity_id}/release` | 释放额度 |
| 凭证 | `POST /v1/vouchers` 等 | 一次性付款授权 |
| 结算 | `POST /v1/settlement/create` 等 | 结算状态机（create→pending→lock→start→submit→buyer-accept→settled） |
| Runtime | `POST /runtime/create-key` | 铸造 Runtime Key（带 profile_id） |
| | `POST /runtime/request-voucher` 等 | agent 运行时操作 |

---

## 4. 身份与可见性规则

| class | 可见性默认 | 明细可见 |
|---|---|---|
| individual | public | 本人 |
| merchant | public | 本人 + 授权买家 |
| enterprise | **private（涉密）** | **仅本人 + 已授权方** |
| verifier | public | 本人 + 协议 |
| arbitrator | public | 本人 + 争议双方 |

- private 档案：`list/get/ledger` 对非 owner 一律 404/403 或脱敏（不吐 `kyc_payload`）。
- 授权披露 = 「对特定授权方开放某几笔明细」的落地机制。

---

## 5. 关键概念速查

- **master 身份卡**：钱包 SIWE 认证后自动领取（`identity_profiles` 的 DID/法律身份）。
- **身份档案（role profile）**：master 卡下的 class + KYC + 可见性 + 明细隔离（`identity_role_profiles`）。
- **Runtime Key**：agent 的「工作通行证」，绑到某个档案，有独立单笔/日限额，**不能提现**。
- **profile_id 贯穿**：voucher → settlement → receipt 都带 profile_id，实现「按档案记账/隔离」。

---

## 6. 常见问题

**Q：连接钱包后没有档案？**
A：先在「身份」页「创建档案」，档案才会出现在切换器里。

**Q：企业档案明细别人看不到？**
A：对 —— enterprise 默认 private，需在「授权披露」里把授权方 + 明细放行，对方才能查 ledger。

**Q：Runtime Key 绑到哪个档案？**
A：绑到「切换器里当前选中的档案」。发 key 前先在侧边栏选好档案。

**Q：真链结算（testnet）要什么前置？**
A：`SETTLEMENT_MODE=testnet` + 钱包有 USDC + approve 合约 + Redis/Celery worker 起来。offchain 模式则不碰链。

**Q：本地怎么跑？**
A：见《部署说明书》；最小本地栈 = Redis + PostgreSQL(SQLite 也行) + `uvicorn api.app:app` + `celery -A worker.tasks worker` + 静态起操作台。
