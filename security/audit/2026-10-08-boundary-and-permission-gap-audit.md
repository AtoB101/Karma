# 安全审计 —— 边界与权限缺口盘点（2026-10-08）

Range: 测试网（`https://karma-network.ai`，Sepolia `TESTNET_CHAIN_ID=11155111`）。主网未动。

结论先行：认证 / 资金状态机的**判定逻辑**是严谨的 —— 本轮把 408 条路由的依赖图逐条拉出来
核对，未发现可绕过的资金漏洞（金额守恒、状态机 fail-closed、业主 / 复核员 / 质押在任、
节点自有 key 签名、跨租户 party 绑定都在）。但**「谁能对谁做这件事」这一层，有一批路由
没有对象级授权**：4 个模块「只要登录就能跨租户写」、若干读接口只要登录、治理岗的
「发给他人 / 收回」只有数据模型、**没有 API 入口**。

## 0. 风险总览

| 编号 | 缺口 | 级别 | 状态 |
|---|---|---|---|
| G1 | `/v1/identities/*` 全模块无归属校验（含改**他人** automation-policy） | 高 | **已落地（本轮）** |
| G2 | `/v1/identity/{id}/credentials\|class` 无归属校验（MiniApp 身份库，可代他人签发 / 吊销凭证、改身份类别） | 高 | **已落地（本轮）** |
| G3 | `GET /v1/capacity/{id}` 无归属校验（可读他人额度 / 锁仓） | 中 | **已落地（本轮）** |
| G4 | POD 交付验证：`actor_agent_id` 自报，未绑会话身份 | 中 | **已落地（本轮）** |
| G5 | 治理岗「发给他人」/「收回」无 API（`require_governance_verifier` 零调用、`GOVERNANCE_OPEN_JOIN` 关） | 中 | 未落地 |
| G6 | 换绑操作钱包无「刷脸 / 应急」闸门（已绑再换只验新钱包签名） | 中 | **已落地（本轮）** |
| G7 | `GET /v1/security/policies*`、`/v1/arbitration/pool`、`/v1/receipts/*` 等读接口只要登录 | 低 | **已落地（本轮）** |
| G8 | `update_role_profile` 的 `status` 由本人自报、无枚举校验 | 低 | **已落地（本轮）** |
| G9 | `face-consistency` 直接把档案置 `verified`（审计 O1 的「操作台文案区分」未做） | 低 | **已落地（本轮）** |
| G10 | 发布门槛 10 项 `[人工]` 未签（A4d/E4b/E6b/F6/H2/H3/H9/H10/H11/H12） | 人工 | 未签 |
| G11 | KYC 侧对外公开留痕接口 | 待产品 | 待拍板 |

## 1. 方法与证据

| 检查面 | 做法 | 结果 |
|---|---|---|
| 全量路由权限面 | 用 FastAPI 自身路由表 dump 408 条端点的依赖图，逐条分类 | 见 §2 / §3 |
| 无授权模块扫描 | 对 `api/routes/*.py` 扫「有端点、但通篇没有 `require_*` / `resolve_actor*` / `403`」的模块 | 命中 `identities.py`、`identity_card.py`、`delivery_verification.py`、`receipts.py`、`evidence.py` |
| 逐 handler 复核 | 对命中模块逐个读源码，看是否在 handler 内做了归属判定 | 见 §3 |
| 生产只读核对 | VPS `root@47.82.74.68` 读 `/opt/karma/.env` 与容器 env | 见 §4 |
| 交叉既有审计 | `2026-10-08-console-and-money-state-machine-audit.md` 的 O1 / O2 / O3 | 见 §3 / §5 |

## 2. 已落地的边界（核对通过，不是缺陷）

- **能力位 ↔ 真闸门逐字对齐**：`api/routes/console_caps.py` 的六个布尔位全部能在服务端找到对应
  的 `require_*` / `_require_verifier`（`services/actor_guards.py`、`api/routes/reviews.py`）。
  前端 `false` 只隐藏入口，判定权威在后端；`can_open_review_queue` 与 `_require_verifier`
  **同口径**（含 `assert_governor_active` 在任判定）。
- **仲裁**：`POST /v1/arbitration/cases` 立案人必须是本案当事人（`api/routes/arbitration.py:198`）；
  派庭 `assign-auto` / 执行 `execute` 走 `require_arbitration_operator`（`:351` / `:698`）；
  投票要**本人**（`require_identity_binding`，`:587`）、派庭后**再校验抵押覆盖案值**（`:600`）、
  运维代投落 `ARBITRATOR_ACTION` 安全事件（`:657`）；案件详情 / 材料 / 事件只对当事人与运维开（`_require_case_reader`，`:167`）。
- **主体认证 / KYC**：owner（`entity_verification.py:94`、`identity_kyc.py:65`、`identity_verification.py:122`）
  + 复核员（非本人 + verifier 岗 + `assert_governor_active`）+ 明文原件红线（`assert_no_plaintext_payload`）
  三重都在；`verified` 唯一出口是合规撤销（`services/compliance_revocation.py`）。
- **资金守恒**：`services/capacity_ledger.py` 的两条守恒式 + `assert_can_release_locked_funds`；
  额度读接口有 owner 校验（`get_allocations`，`capacity.py:166`）；PUT 额度强制 2FA（`capacity.py:218`）。
- **节点自有 key 签名**：`services/verifier_wallet.py` 的写接口签名闸门，
  生产 `VERIFIER_REQUIRE_NODE_SIGNATURE=true`（见 §4），没签名 401、重放 409、地址不符 403。
- **跨租户 party 绑定**：`services/ledger_party_access.require_ledger_identity` 用在
  capacity 写（lock / release / stake / claim）、vouchers、confirmations、orchestration、trade、x402；
  `services/settlement_party_access` 用在 settlement / progress。
- **设计上公开 / 无状态**（非缺陷）：`/v1/standards`（公开目录，无 router 依赖）、
  `/v1/entities` 公开视图、`/v1/skills` 公开读、`/v1/developers` 公开档案、
  `/v1/identity/{id}/verification/provider-callback`（服务商回调，靠自身签名）。

## 3. 未落地（逐条）

### G1（高）`/v1/identities/*` 整个模块没有对象级授权

`api/routes/identities.py` 通篇没有 `403` / `require_*` / `resolve_actor_identity_id`，
路由只挂了 `require_auth_if_enabled`（登录即可）。`identity_id` 直接来自路径，**没有一处校验
调用者就是该身份本人**。任何持有效会话的身份可以：

- `PUT /v1/identities/{受害者}/automation-policy`（`:314`）—— 改**别人**的自动化资金边界：
  `single_limit` / `daily_limit` / `preauth_enabled` / `permissions` / `trusted_counterparty_ids` /
  `auto_execute_pipeline`。**这是资金相邻的写**：它决定该身份的 agent 能不能自动下单、能花多少。
  操作台自己是按「本人 id」调这个接口的（`apps/console/scripts/karma-public-api.js:588/595`），
  加 owner 校验不会破坏操作台。
- `POST /v1/identities/{受害者}/rotate-display-id`（`:157`）—— 改**别人**对外可展示的 display_id。
- `POST` / `DELETE /v1/identities/{受害者}/sub-identities[...]`（`:190` / `:225`）—— 建 / 删**别人**的子身份。
- `POST /v1/identities/{受害者}/profile/init`（`:104`）、`POST /v1/identities/project-from-did`（`:44`）。

对照：同一套「子身份 / 档案」的读写在别的模块都有 owner 校验（`identity_role_profiles.py`、
`identity_disclosures.py`）。**这是本模块独有的缺口。**

### G2（高）`/v1/identity/{id}/credentials|class` 无归属校验

`api/routes/identity_card.py` 同样通篇没有授权判定，`identity_id` 取自路径：

- `POST /v1/identity/{受害者}/credentials`（`:61`）—— 代**别人**签发凭证；
- `POST .../{credential_id}/verify|reject|revoke`（`:80` / `:94` / `:106`）—— 代**别人**核验 / 拒绝 / 吊销凭证；
- `PUT /v1/identity/{受害者}/class`（`:143`）—— 改**别人**的身份类别（`user|business|agent`）；
- `GET /v1/identity/{受害者}/card`（`:122`）、`/v1/trust/ledger|alerts|health`（`:169`–`:190`）—— 读。

读接口是**脱敏**的（`store.identity_card` 不吐 2FA / 完整钱包），所以读风险低；**写才是问题**：
代他人签发 / 吊销凭证、改身份类别，是跨租户写入。

**影响面**：这套接口读写的是 MiniApp 的 `identity_gateway` store（`services/identity_gateway/store.py`），
不是主 Karma 身份（`identity_role_profiles` / `entity_verification`）。但生产环境这套路由是**活着**的
（`api/app.py:521` 无条件挂载，`/v1/identity/{id}/credentials` 在 408 条路由里）。

### G3（中）`GET /v1/capacity/{id}` 无归属校验

`api/routes/capacity.py:47-52` 的 `get_capacity` 只 `validate_public_url_segment` + 读库，
**没有** `require_ledger_identity`。同文件的 `get_allocations`（`:166`）却明确做了
`actor != identity_id → 403`。于是任何登录身份可读任意身份的额度状态（锁仓 USDC、可用额度）。
其余写路径（lock / release / stake / claim）都过了 `require_ledger_identity`。

### G1 / G2 / G3 —— 已落地（本轮）

统一补上「身份归属」闸门，做法与 ``services/ledger_party_access`` /
``services/settlement_party_access`` 同一套路：

- 新增 ``services/identity_owner_access.py`` 的 ``require_identity_owner``：调用者必须
  映射到该 ``identity_id`` 本人（agent→owner_identity 两个命名空间都认），或属于
  ``ADMIN_ACTOR_IDS`` 运维白名单。
- 新增开关 ``IDENTITY_REQUIRE_OWNER_BINDING``（默认 true）；与
  ``AUTH_ENFORCE_PROTECTED_ROUTES`` 同时为真才强制 —— 生产两条都 fail-closed 必须为真
  （生产校验已在 ``config/settings.py`` 加上），本地 / 联调不受影响。
- 接入点：``api/routes/identities.py`` 的 10 个端点全部补 ``request`` + 守卫；
  ``api/routes/identity_card.py`` 的 5 个写端点（签发 / 核验 / 拒绝 / 吊销凭证、改 class）
  补守卫（读接口 ``card`` / ``trust`` 保持「最小披露」口径不变）；
  ``api/routes/capacity.py`` 的 ``GET /v1/capacity/{id}`` 补守卫。
- 回归：``tests/unit/test_identity_owner_binding_api.py``（5 条：跨租户 403、本人 200、
  运维白名单 200）。相关套件（绑定 / 自动化策略 / AP2 / SDK / 投影 / 生产开关）
  全绿。

### G4（中）POD 交付验证：`actor_agent_id` 自报

`api/routes/delivery_verification.py` 的 12 个端点都不带 `request`、不做身份绑定；
当事人是请求体里**自报**的 `actor_agent_id`。服务层只校验「自报值 == 会话里记的当事人」
（`services/delivery_verification.py:477/540/606/895`），**不校验「调用者 == 自报值」**。
知道会话内容（不是秘密）的任何登录身份，就能以买家 / 卖家 / 物流的名义推进：
`seller-ship`、`logistics-intake`、`proofs`、`logistics-deliver`、`buyer-confirm`、`verify`、
`apply-silent-default` —— 其中 `buyer-confirm` / `verify` 是结算「买方验收」闸门的输入。
同一仓里已有现成范式（`services/settlement_party_access.require_actor`，`progress.py` 在用），本模块没用。

### G4 —— 已落地（本轮）

与 G1/G2/G3 同一口径：当事人不再靠请求体**自报**，而是校验「调用者 == 当事人本人」。

- `api/routes/delivery_verification.py` 的 6 个**写 / 推进**端点补 `request` + 守卫：
  `POST /sessions`（按 `body.seller_agent_id`）、`/{id}/seller-ship`、`/{id}/logistics-intake`、
  `/{id}/proofs`、`/{id}/logistics-deliver`、`/{id}/buyer-confirm`（均按 `body.actor_agent_id`）——
  统一 `await require_identity_owner(db, request, actor, what=...)`（跨身份 403，运维白名单放行）。
- 纯读端点（`GET /sessions`、`GET /{id}`、`GET /{id}/capture-challenge`）与 `verify` /
  `apply-silent-default` 本轮未动（前者最小披露；后者属 G5 治理动作范围，另行处理）。
- 回归：`tests/unit/test_identity_owner_binding_api.py` 追加 2 条（跨身份发起 POD 会话 403、
  跨身份 `buyer-confirm` 403）；`test_identity_owner_binding_api.py` + `test_delivery_verification.py`
  共 **16 passed**。

### G5（中）治理岗「发给他人」/「收回」没有 API

- `services/actor_guards.require_governance_verifier`（`:90`）定义了「治理身份发放方」闸门，
  但**全仓零调用**（只有定义行）。
- `api/routes/identity_role_profiles.py:_resolve_governance_stake` 的闸门要求
  `owner_identity_id == 调用者`（`create_role_profile:196`），所以**白名单里的人也只能给自己开岗**。
- 生产实测：`GOVERNANCE_OPEN_JOIN` 未设（= 关，见 §4），`GOVERNANCE_VERIFIER_IDS` 只有
  `ops-governance,kid_5f0a...`。

结论：**「把 verifier / arbitrator 岗发给某个人」这条路在当前代码里根本没有入口** ——
只能运维直接改 `.env` 白名单，或（开了 `GOVERNANCE_OPEN_JOIN` 后）本人自助质押。
配套的「收回岗」同样只有两种隐式方式：从 `.env` 摘掉，或抽走锁仓（质押岗靠
`assert_governor_active` 当场失效）。**没有退岗 / 收回的管理动作。**

### G6（中）换绑操作钱包无「刷脸 / 应急」闸门

`api/routes/identity_role_profiles.py:409-446` 的 `bind_role_profile_wallet`：只要求
owner + **新钱包**的 personal_sign。若该档案**已经绑过一个钱包**，再绑就是**直接覆盖**
（`:442`），**不要求刷脸、不触发应急 / 锁定、不留安全回执**。
口径要求是「修改 / 更换钱包地址要触发状态机应急或锁定，只有本人刷脸通过才能更换」——
这一条**未落地**。

### G6 —— 已落地（本轮）

`bind-wallet` 拆成两条路，只有**换绑**（这张子身份已经绑过另一个钱包）才升级到刷脸：

- **首次绑定**：规矩不变，只要新钱包自己的 `personal_sign`（证明「这个钱包愿意代表这张子身份」）。
- **换绑**：先照旧验新钱包签名，再要求**本人刷脸通过** —— 复用 `services/face_activation.assert_same_person`
  那一整套判据（签名 / 参考模板一致 / 非重放 / 分数过线）；签名的钱包必须是这个身份的
  **绑定钱包（身份根）**，不是被换掉的那个操作钱包。不走刷脸 → 409，且不动已绑钱包。
- 动作落 `SecurityMonitoringEventType.IDENTITY_WALLET_REBIND` 安全事件（可追溯 / 可告警）
  + `NOTICE_WALLET_REBOUND` 站内回执（操作台 `cyber-unbind-keys.js` 渲染，五语词表齐全）。
- 回归：`tests/unit/test_wallet_rebind_face_gate.py`（4 条：首次只认新钱包签名 / 无刷脸 409 且不动钱包 /
  刷脸成功换绑并留痕 / 刷脸结论签自非根钱包 403）。相关套件（身份认证 / 刷脸 / 回执 / 词表纯净度 /
  节点层）全绿。
- **未做**：操作台「换绑」交互入口。当前操作台只在新建子身份时绑一次，换绑只能走 API；
  前端刷脸换绑向导列为后续 UI 项（不影响闸门本身）。

### G7（低）若干读接口只要求「已登录」

- `GET /v1/security/policies`、`/policies/{id}`、`/policies/changes`、`/policies/changes/{id}`
  （`api/routes/security.py`，审计 O1）—— 普通身份可读安全阈值策略与变更单内容（限流阈值、baseline 窗口、
  冷却、审批状态）。同一文件里策略的**写**全部是 `require_admin_actor`。
- `GET /v1/arbitration/pool`（`arbitration.py:141`）—— 任何登录身份可列出全部仲裁员身份 id + 质押额。
- `GET /v1/receipts/{receipt_id}`、`/v1/receipts/task/{task_id}`（`receipts.py:77/85`）—— 可读任意任务的执行回执。
- `GET /v1/verifiers`、`/{id}`、`/network/stats`、`GET /v1/verifiers/attestations/*` —— 可读节点与出证明细。

这些**可能**是刻意的公示口径（网络看板要公开），但**没有测试钉住**，所以归为「未定口径」。

### G8（低）`update_role_profile` 允许本人改 `status`

`api/routes/identity_role_profiles.py:327` 直接 `row.status = data["status"]`，`status` 只受
`max_length=16` 约束，**无枚举校验**。它会影响 `console_caps._can_open_review_queue` 的
`status == "active"` 判定（但对治理岗而言开岗仍受 G5 闸门约束，所以不可直接提权）。

### G9（低）`face-consistency` 直接置 `verified`

`identity_role_profiles.py:345` 的 `confirm_role_profile_same_person` 复核通过后直接
`row.kyc_status = "verified"`。审计 O1 的结论：同人刷脸 ≠ 工商资质审核；建议操作台对
刷脸开的档案显示**不同文案**，不与企业 / 个体户的「资质已审」混同。**文案区分未落地。**

### G7 / G8 / G9 —— 已落地（本轮）

**G7（读接口口径）**：

- 收紧：`/v1/security/policies`、`/policies/{id}`、`/policies/changes`、`/policies/changes/{id}`
  四条 **GET** 补 `require_admin_actor`（与该文件的写端点同口径）—— 限流阈值 / baseline
  窗口 / 冷却 / 审批状态属内部运维参数，普通身份不该读。
- 顺带修掉一个**路由遮蔽** bug：`GET /policies/changes` 声明在 `GET /policies/{policy_id}`
  之后，被当成 `policy_id="changes"` 吃掉、永远 404；已把两条 `changes` 读路由提到前面。
- 明确「公示口径」并用测试钉住：`/v1/arbitration/pool`、`/v1/verifiers*`、`GET /v1/receipts/*`
  **有意**对任意已登录身份开放（去中心化成员名册 + 带签名的可验证回执），不是漏配。
- 回归：`tests/unit/test_platform_privilege_boundaries.py` 追加 3 条（策略读管理员专属、
  changes 列表不再被遮蔽、公示读不是运维专属）。

**G8（档案 status）**：`identity_role_profiles.py` 的 `RoleProfileCreate.status` /
`RoleProfileUpdate.status` 从自由字符串改成枚举 `^(active|disabled)$`（对齐已有的
`class` / `kyc_status` / `visibility` 写法）；未知值 422。回归：
`tests/integration/test_identity_role_profiles.py`。

**G9（文案区分）**：操作台子身份行按 `kyc_payload.face_consistency` 区分「同人刷脸已核验」
与走资质复核的「已通过」，不再混同；顺手把 `人脸 {0}` 这句接上源文案表（此前键在词表里、
代码却是硬拼中文）。回归：`tests/unit/test_console_last_mile.py`。

### G10（人工）发布门槛 10 项未签

`docs/SECURITY_RELEASE_GATES.md` 的 `[人工]`：A4d（运维白名单身份确有其人）、E4b（告警阈值已调）、
E6b（回滚演练签字）、F6（baseline 漂移策略复核）、H2（测试钱包有资金）、H3（锚定按笔写入）、
H9（Karma2 版本锁）、H10（OpenClaw MCP A/B）、H11（OpenManus 冒烟）、H12（混合上链冒烟）。
`--strict` 下算失败。

### G11（待产品）KYC 对外公开留痕接口

主体认证有 `GET /v1/entities/{id}/revocations`（公开）；KYC 一侧只有 `_serialize_kyc.revocation`
随档案下发，**没有独立公开历史接口**，且本人重新提交后旧留痕会被新载荷覆盖
（权威记录仍在 `verification_revocation_requests` 的 executed 行）。是否补公开接口**待产品拍板**。

## 4. 生产实测快照（测试网，只读）

`/opt/karma/.env`（`root@47.82.74.68`，值不落仓）：

| 变量 | 值 |
|---|---|
| `APP_ENV` | `production` |
| `AUTH_ENFORCE_PROTECTED_ROUTES` | `true` |
| `ADMIN_ACTOR_IDS` | `ops-admin,kid_5f0aa8ccf7483983a8a2a5a9` |
| `ARBITRATOR_ACTOR_IDS` | `ops-arbitrator` |
| `GOVERNANCE_VERIFIER_IDS` | `ops-governance,kid_5f0aa8ccf7483983a8a2a5a9` |
| `GOVERNANCE_OPEN_JOIN` | 未设（= 关 → 治理岗只能靠白名单） |
| `VERIFIER_REQUIRE_NODE_SIGNATURE` | `true` |
| `LEDGER_REQUIRE_PARTY_ACTOR` | `true` |
| `SETTLEMENT_REQUIRE_PARTY_ACTOR` | `true` |
| `RECEIPT_REQUIRE_SIGNATURE` | `true` |

（容器 env 与 `.env` 一致。）

## 5. 建议落地顺序

1. **G1 / G2 / G3**：给三处无授权路由补 owner 校验（复用 `resolve_actor_identity_id`；
   与现有 `require_ledger_identity` / `_require_owner` 同口径），并加回归测试钉住 403。
   G1 的 `automation-policy` 必须优先 —— 它是资金相邻写。
2. **G6**：换绑钱包加「已绑需刷脸 / 应急」分支 —— 已落地（本轮）。
3. **G5**：接上 `require_governance_verifier` —— 开一条「治理发放方给他人开 / 收回 verifier·arbitrator 岗」
   的路由（含退岗动作），并把它接到操作台。
4. **G7 / G8 / G9**：已落地（本轮）。
5. **G10**：人工签核；**G11**：产品拍板。

—— 本报告只做盘点，未改任何代码 / 状态机。主网未动。
