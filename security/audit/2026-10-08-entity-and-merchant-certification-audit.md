# 安全审计 —— 企业 / 个体户认证 + 资金硬保障（2026-10-08）

Range: 测试网（`https://karma-network.ai`，Sepolia `TESTNET_CHAIN_ID=11155111`）。主网未动。

结论先行：**认证链条的骨架是严谨的**（服务端权威状态机 + 官网控制权硬证据 + 复核方闸门 +
原件只存密文包），但**档案层有一条可被本人利用的越权写入漏洞**：`POST/PUT /v1/identity/role-profiles`
直接照收客户端自报的 `kyc_status`，本人一次调用就能把企业 / 个体户档案写成「已验证」；
KYC 载荷里的「复核结论」键同样能自写，且建 / 改档案路径没有明文原件红线。
本轮已按「为消费者负责」的口径把这三条一并堵死，相关回归 134 条全绿。资金硬保障一侧核查未见可被利用的漏洞。

## 1. 方法与证据

| 检查面 | 做法 | 结果 |
|---|---|---|
| 认证流程代码走查 | `services/entity_verification.py`、`api/routes/entity_verification.py`、`api/routes/identity_kyc.py`、`api/routes/identity_role_profiles.py`、`api/routes/reviews.py`、`services/auto_verification.py` | 见 §2 / §3 |
| 活体越权实测（修复前） | 直接 `POST` / `PUT` 角色档案带 `kyc_status=verified` | **201 / 200**，本人可自报「已验证」——见 §4 |
| 认证 + 治理 + 刷脸回归 | `pytest`（角色档案 / 企业认证 / KYC / 治理质押 / 刷脸 / 操作台复核） | **134 passed**（65 + 69） |
| 资金硬保障走查 | `core/settlement/engine.py`、`services/capacity_ledger.py`、`services/entity_verification.py`、`security/registry/financial_functions.yaml`、`docs/FINANCIAL_SECURITY_PROOF.md` | 见 §5 |
| CI | 6 条必需检查（含 `Security CI` 的 Slither / ops-scripts / 发布就绪门禁） | 见 §7 |

## 2. 企业主体认证核查（`class=enterprise` / 主体验证）

**状态机**（`services/entity_verification.py` 的 `ENTITY_TRANSITIONS`）：
`none → draft → pending → verified | rejected`，`rejected → draft/pending` 可改后重交；`verified` 是终态（无出边）。
`assert_can_submit` / `assert_can_decide` 一律走 `ENTITY_TRANSITIONS.get(current, set())` —— **fail-closed，缺键不放行**。

**四道闸门，缺一不可**（`api/routes/entity_verification.py`）：

- **官网控制权是硬证据，且由服务端回读**：`website-verify` 服务端主动 GET
  `https://{official_domain}/.well-known/karma-entity-verify.txt`（`fetch_website_proof`），
  只允许 `https`、**不跟随跳转**、响应体限长 4096；校验文件里的 token 必须与 challenge 一致且在 7 天 TTL 内。
- **防 SSRF**：`_assert_public_host` 先做 DNS 解析，任一解析结果为 private / loopback / link-local /
  reserved / multicast / unspecified 立即拒（内网跳板被堵死）。
- **防同域名抢注**：`_assert_domain_unclaimed` 保证一个官网域名只能认证给一个主体（提交与复核两处都查）。
- **复核方闸门**：`_require_reviewer` 要求复核人持有 `class=verifier` 档案、**不是主体本人**，
  且 `assert_governor_active`（质押开出来的岗，押金被划走即当场失去复核权）。

**红线**：`build_submission` 走 `assert_no_plaintext_payload` —— 证件 / 人脸明文、data URL 一律 400；
库表只存密文包 + sha256 摘要 + 脱敏展示字段。对外 `public_view` 只暴露工商公示信息，不露证件包。

## 3. 个体户（商户）认证核查（`class=merchant` + KYC）

个体户认证落在商户档案的 KYC 状态机上（`api/routes/identity_kyc.py`）：
`none → pending → verified | rejected`，`rejected → pending` 可重交。同一条复核规则：
必须 verifier 岗、非本人、`assert_governor_active`。

**提交前自检**（`api/routes/reviews.py` 的 `POST /v1/reviews/precheck` → `services/auto_verification.py`）：

- 统一社会信用代码**校验位**核算（`check_registration_no`）；
- 企业邮箱域名 **MX** 记录查询（纯 Python UDP DNS，不引第三方依赖；查不到标「无法确认」，**不阻断**提交）；
- 邮箱域名与官网是否**同站点**（`same_site`，多级域名归一比较）。

**红线同上**：提交载荷先过 `assert_no_plaintext_payload`，正文明文原件 400。

## 4. 发现并已修（高）：档案层自报认证状态 + 自写复核结论 + 绕过明文红线

**问题 A —— 可自报 `kyc_status`**（`api/routes/identity_role_profiles.py`）。修复前实测：

- `POST /v1/identity/role-profiles` 带 `{"kyc_status":"verified"}` → **201**，建档即「已验证」；
- `PUT /v1/identity/role-profiles/{id}` 带 `{"kyc_status":"verified"}` → **200**，返回 `kyc_status:"verified"`。

即本人一次调用就能把企业 / 个体户档案写成「已验证」——操作台 badge 与对外列表都如实转述这个状态，
而**证件一份没交、复核一个人没看**。对消费者而言这是最危险的失真：认证标记是「能不能跟你做生意」的依据。

**问题 B —— 可自写「复核结论」**：KYC 载荷里的 `verification` 键是复核方的结论，但
`POST /kyc`（提交）与 `POST/PUT` 建 / 改档案都原样收下，本人可以自己写一份「已通过」。

**问题 C —— 建 / 改档案绕过明文原件红线**：提交路径有 `assert_no_plaintext_payload`，
但 `POST/PUT` 的 `kyc_payload` 是**直接入库**的——证件原图 / 人脸明文可从这条路塞进来，
绕过「服务端永不接收明文」的设计红线。

**修复**（`api/routes/identity_role_profiles.py` + `api/routes/identity_kyc.py`）：

- 新增 `_reject_self_declared_kyc`：建 / 改档案时任何非 `none` 的 `kyc_status` 一律 **422**；
  建档恒从 `kyc_status="none"` 开始；
- 新增 `_without_client_verdict`：客户端写入路径（建 / 改档案、提交 KYC）**一律摘掉**
  载荷里的 `verification` 键；
- 新增 `_sanitize_client_kyc_payload`：建 / 改档案的 `kyc_payload` 与提交路径走**同一条明文红线**
  （`assert_no_plaintext_payload`，`IdentityVerificationError` → 对应 HTTP 状态）；
- **服务端权威写入路径原样保留**：`identity_kyc.submit → pending`、
  `identity_kyc.verify → decision`（verifier 且非本人且岗在任）、`face-consistency → verified`（同人刷脸）。

**测试**：新增 `tests/unit/test_role_profile_kyc_authority.py`（7 条：建 / 改不许自报、载荷 verdict 被摘、
明文 400、复核方结论仍被服务端写入并保留），并合并原临时探针后删除 `tests/unit/_tmp_kyc_probe.py`。
`pytest`（认证 + 治理 + 刷脸 + 操作台复核）**134 passed**。

## 5. 资金硬保障核查（企业 / 个体户「敢接入」的底气）

**链上（`KarmaBilateral.sol` + `security/registry/financial_functions.yaml` INV-1…INV-10）**：
没有合法结算条件资金不得释放（INV-1）；Verification Result 不得单独授权放款（INV-2）；
非法状态转换失败（INV-3）；不得重复结算（INV-4）；未授权 Actor 不得动资金（INV-5）；
收款人不匹配失败（INV-6）；金额不匹配失败（INV-7）；Nonce / 签名不合法失败（INV-8）；
争议态不得普通结算（INV-9）；**后端被完全攻破也拿不到用户锁定资金**（INV-10，非托管 + 合约守卫，
后端仅能提交交易、无提款权限）。每条都有 `forge` 用例钉住（`test_INV*`）。

**服务端守恒**（`services/capacity_ledger.py`）：

- `total_bill_credits == active`、`total_locked_usdc >= active` 两条守恒式（`assert_capacity_invariants`）；
- 在有责任额度时**不许释放锁仓**（`assert_can_release_locked_funds`）；
- `heal_capacity_conservation` 只在漂移时**抬高**锁仓自愈，并大声记日志（`capacity_conservation_repaired`）——
  自愈不会凭空造出可用额度。

**结算状态机**（`core/settlement/engine.py`）：`VALID_TRANSITIONS` 单一权威，未知来源状态 fail-closed。

**接入门槛**（`services/wallet_funding.py`）：注册钱包未注资时**限流**而非直接拒（`enforce_registration_funding_gate`），
把「开场就砸链」的成本抬起来。

**冻结 overlay**（`docs/FINANCIAL_STATE_MACHINE.md`）：`globalFreezeUntil`（≤7 天）/ agent / bill / binding
+ CircuitBreaker；冻结期禁 bind/settle/finalize/分账，但**保留**查看、`unlock(MINTED)`、超时退款与全额退款通道。

结论：资金这一侧**非托管 + 合约条件链 + 服务端守恒 + 冻结兜底**四条腿都在，未见可被利用的空档。

## 6. 观察项（未改，留给产品 / 权限口径）

- **O1（设计边界，非缺陷）** `POST /v1/identity/role-profiles/{pid}/face-consistency`（同人刷脸）会把档案
  直接置 `verified`。这等于「主身份已通过同人验证的追加身份」——认证强度等于主身份的同人验证，
  **不等于**企业资质的工商审核。企业 / 个体户想拿到「资质已审」的标记，必须走 §2 / §3 的提交 → 复核路径。
  建议操作台在刷脸开的档案上显示不同的文案，别和「资质已审」混为一谈。
- **O2（口径记录）** `assert_governor_active` 的白名单 **或** `stake_amount == 0`（运维直接建档 / 历史行）
  都放行，只有质押开的岗跟押金走。API 开不出 `stake_amount == 0` 的治理岗，故此路径仅限运维建档。
- **O3（长度约束分层）** 企业 `service_scope` 等字段的约束分两层：Pydantic body 用 `max_length`，
  服务层另有 `sanitize_entity_profile` 兜底截断。两层口径一致，无需改。

## 7. 实测快照

- 生产：见文末 CI / 发布快照（HEAD、容器、`/health`、CLI 一致性）。
- 回归：认证 + 治理 + 刷脸 + 操作台复核 **134 passed**（`putmp_kyc3` 65 / `putmp_kyc4` 69）。

## 8. 残留人工项（`docs/SECURITY_RELEASE_GATES.md` 的 `[人工]`）

A4d、E4b、E6b、F6、H2、H3、H9、H10、H11、H12 —— 机器判不了，必须有人签字，`--strict` 下算失败。