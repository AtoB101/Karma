# 安全审计 —— 操作台安全回执 + 资金状态机（2026-10-08）

Range: 测试网（`https://karma-network.ai`，Sepolia `TESTNET_CHAIN_ID=11155111`）。
结论先行：**没有发现可被利用的资金安全漏洞**；机器闸门与 439 条安全/状态机单测全绿。
本轮唯一实修项是操作台「安全回执」覆盖不全（见 §4）。主网未动。

## 1. 方法与证据

| 检查面 | 做法 | 结果 |
|---|---|---|
| 发布环境整体安全闸门 | 在 VPS 对活体跑 `scripts/public-beta-security-gate.sh --no-heavy` | **PASS 49 · FAIL 0 · WARN 0 · HUMAN 10**，退出码 0 |
| 代码级安全/状态机回归 | `pytest tests/unit -k "security or receipt or settlement_status or state_machine or voucher or arbitration or 2fa or console"` | **439 passed** |
| CI | 6 条必需检查（含 `Security CI` 的 Slither / ops-scripts / 发布就绪门禁） | 6/6 绿 |
| 模式扫描 | `eval/exec`、`shell=True`、`yaml.load`、f-string SQL、`verify=False`、CORS 通配、提交明文密钥 | 无命中 |
| 生产现状 | HEAD == origin/main、0 未提交、三容器 healthy、`/health`200 | 见 §6 |

## 2. 资金状态机核查

**链上（`KarmaBilateral.sol` / `docs/FINANCIAL_STATE_MACHINE.md`）**
- `BillState`：`MINTED → BOUND → BURNED`；`BOUND → SETTLED` 不存在，结算走 Binding。非法跳转 revert（`WrongBillState`/`WrongBindingState`）。
- `BindingState`：`ACTIVE → FINALIZING → SETTLED`，或 `DISPUTED → resolve/autoResolve`，或 `settleTimeout → REFUNDED`。
- 冻结 overlay：`globalFreezeUntil`（≤7 天）/ agent / bill / binding + `CircuitBreaker`；冻结期间**禁** bind/settle/finalize/分账，**允许** 查看、`unlock(MINTED)`、超时退款、举证与全额退款。

**服务端（唯一权威表 `core/settlement/engine.py`）**
- `VALID_TRANSITIONS` 覆盖全部 canonical 状态；`can_transition` 用 `VALID_TRANSITIONS.get(from, [])` —— **未知来源状态无出边，fail-closed**（不会因缺键而放行或抛 500）。
- 每条流转（**包括被拒的那条**）都写 `SettlementTransitionAuditModel` 并派发
  `SETTLEMENT_TRANSITION_AUDIT` 安全事件 —— 两条路径都有：`api/routes/settlement.py:_apply_transition`
  与 `services/settlement_transitions.py:apply_settlement_transition`（agent 下单/trade pipeline 走后者）。
- 链下事实与链上事实对齐：先落业务状态并 `commit` **放掉行锁**，再动链；链上拒绝则按快照
  `revert`（含争议冻结的解除），并补一条 `guard_stage="chain"` 的拒绝审计。这是 2026-09-30 死锁
  与「页面说结算了、链上没动」两个真实事故的根因修复。
- `api/routes/settlement.py` 与 `services/settlement_transitions.py` 的链上同步共用同一份实现
  （`_sync_escrow_settlement`），不存在两套口径。

**操作台（`apps/console/scripts/cyber-order-flow.js`）**
- 单笔订单状态图**只读**：每个阶段亮不亮只看后端状态机、`settlement_transition_audits` 流转历史、
  交付验证事件；「没依据的阶段就是没亮，不猜、不编」。阶段表按 `scene` 选（后端 `progress_rule_spec.scene_id`），
  认不出走通用兜底 —— 不存在前端自造状态。

结论：状态机的三处（链上 / 服务端 / 操作台展示）**同源、可回溯、拒绝也留痕**，符合「全系统同步、状态对齐」的要求。

## 3. 操作台安全面核查

- **第二把锁（2FA/TOTP，`services/console_2fa.py`）**：验证码不落库（只存 base32 密钥与恢复码哈希）；
  ±1 时间窗；失败按**身份**累加（不是按 IP），达阈值锁定；恢复码一次性用掉即焚；解绑同样要过码。
  动额度（`PUT /v1/capacity/{id}/allocations`）与取消授权都强制过码。
- **能力位（`api/routes/console_caps.py`）**：只回调用者自己的布尔位，判定权威仍在服务端
  `services/actor_guards.py` 的 `require_*`；前端拿到 `false` 只隐藏入口，不构成第二道门。
  三类运维角色（管理员 / 仲裁员 / 治理发放方）互不隐含，白名单只在服务端 `.env`。
- **站内提醒（安全回执）接口**：`/runtime/list-notices`、`/runtime/ack-notice` 一律按会话身份
  收敛（`_session_owned_identity`：替别人读 → 403；未登录 → 403）。已有回归测试钉住。
- **控制台 XSS**：全部 `innerHTML` 拼接都过本地 `esc()`；动态数据优先 `textContent`；
  无 `eval` / `new Function` / `document.write`。

## 4. 发现并已修：安全回执覆盖不全（中）

**问题**：站内提醒此前只有两个来源 —— `key_bound` / `key_unbound`。于是两类同样要命的变化是**静默**的：

- **授权额度**（子身份额度的加 / 减 / **清零**）：清零 = 把支配权收回来，页面闪一下就没，
  主人下次进操作台看不到任何痕迹；
- **第二把锁本身被改动**（绑上 / 解绑 / 换恢复码）：锁被拆了没有回执。

这与既定原则「凡是安全相关的变化都要让用户事后看得见」冲突，且 2FA 解绑本身是高风险动作。

**修复**（`services/console_notice.py` + `api/routes/console_2fa.py` + `api/routes/capacity.py`
+ `apps/console/scripts/cyber-unbind-keys.js` + 五份词表）：

- 新增回执类型 `allocations_changed` / `2fa_enabled` / `2fa_disabled` / `2fa_recovery_rotated`；
- 写入口收敛到一个 `add_notice_safe`：**先把真正的动作 commit，再写回执**，写失败只丢回执、
  绝不把已经生效的动作一起回滚；
- 授权额度回执带改后的合计与逐子身份额度；2FA 回执记录恢复码张数；
- 操作台画出这四条文案，五份词表都有译文（不留中文）。

**测试**：新增 `tests/unit/test_console_security_receipts.py`（真实库 + 真实路由，钉住三类动作都留回执、
回执私有、词表齐备）；扩展 `tests/js/test_console_notices.cjs`（四种语言渲染 + 不留中文）。

## 5. 观察项（未改，留给产品口径）

- **O1（低）** `GET /v1/security/policies`、`/policies/{id}`、`/policies/changes` 只要求「已登录」，
  普通身份可读安全阈值策略内容。`GET /runtime/safety-mode` 的「任何登录者可读」是**刻意**的
  （操作台首页要读，有测试钉住）；这三条策略读接口没有对应测试。建议二选一：补 `require_admin_actor`，
  或明确写成「公示口径」并加测试钉住。
- **O2（低）** `POST /runtime/ack-notice` 不传 `notice_ids` 时把「全部未读」标记已读。按钮文案
  「知道了（不再提醒）」与之一致，故不算缺陷；但若将来希望「未看到的不被清掉」，前端应传本次展示的 id 列表。
- **O3（说明，非缺陷）** 执行/进度回执的签名验的是**平台钥**：agent 只持 Runtime Key，回执由
  Runtime Gateway 现场代签（`api/routes/runtime_gateway.py` 明确注释，并有 `runtime receipt signing
  invariant failed` 断言）。该设计成立的前提是「网关是唯一签名者、平台钥不进 agent 手里」——
  轮换/托管平台钥时要按这个前提评估。

## 6. 实测快照

- 生产：`HEAD == origin/main == eb3d2ec`（本轮修复前）；未提交 0；`karma-api` healthy、
  `karma-postgres` healthy、`karma-redis` up；`/health` 200；`/usr/local/bin/karma` 与仓库副本 SAME。
- 活体安全闸门：PASS 49 / FAIL 0 / WARN 0 / HUMAN 10（10 条均为需人工签字项：白名单身份确有此人、
  回滚演练有人签字、离站备份换账号恢复过、测试钱包有资金、私有仓版本锁、OpenClaw/Manus/链上冒烟等）。

## 7. 残留人工项（`docs/SECURITY_RELEASE_GATES.md` 的 `[人工]`）

A4d、E4b、E6b、F6、H2、H3、H9、H10、H11、H12 —— 机器判不了，必须有人签字，`--strict` 下算失败。