# 安全阈值策略（Threshold Policy）— 钉版与口径

这份文档回答 `docs/SECURITY_RELEASE_GATES.md` 里 Gate B 的三条：

- `B5` 告警冷却 / 抑制口径；
- `B6` 关键路径（端点 / 路由组）的阈值 overrides；
- `B7` 当前生效的策略版本钉住并写进文档。

外加 Gate E 的 `E7`（策略中心回滚演练）的留证位置。

## 为什么要有这一页

阈值策略中心的接口（`/v1/security/policies`）**默认不能直接激活** ——
激活、灰度、回滚都必须走变更单（`/v1/security/policies/changes`）：创建 → **两人审批** → 应用。
这是刻意的：改阈值等于改「什么算异常」，等于改告警会不会响。所以「当前生效的是哪一版、
它把哪些关键路径收紧了」必须有一个**能被人读到、也能被机器校验**的地方 —— 就是下面这段。

> `B7` 的判据不是「文档写没写」，而是**文档里的版本号跟库里 active 的那一行对不对得上**。
> 对不上就 `FAIL`：文档和现实分叉，比没有文档更危险。

## 当前钉版

```text
<!-- karma-threshold-policy
active_policy_id=6cdce151-49c4-47be-a1f9-92597f94dd4e
active_version=2
activated_at=2026-10-01T18:10:43Z
pinned_at=2026-10-02
signed_by=YMZAI
-->
```

- 生效版本 **v2**，`activated_at` = `2026-10-01T18:10:43Z`（UTC；本地 2026-10-02 凌晨）。
- 上一行由 `scripts/public-beta-security-gate.sh` 的 `B7` 直接解析，并与
  `security_threshold_policies` 里 `status='active'` 的那一行逐字段比对。
- **换策略时：先走变更单激活，再把上面这段的 `active_policy_id` / `active_version` /
  `activated_at` 改成新值。** 忘了改，`B7` 就会红 —— 这正是它存在的意义。

## 这份策略收紧了什么

全站默认值（代码里的 `DEFAULT_SECURITY_POLICY_CONFIG`）对每条路径一视同仁。
v2 在**四个最关键的路由组**上单独收紧，让异常更早被发现：

| 作用域 | 阈值 | 默认 | v2 | 为什么 |
|---|---|---|---|---|
| `/v1/auth/token`（失败鉴权） | `failed_auth_threshold` | 10 | **5** | 撞登录口令是最典型的攻击面，宁早勿晚 |
| `group:auth`（失败鉴权） | `failed_auth_threshold` | 10 | **8** | 整个鉴权组的兜底 |
| `group:runtime`（限流命中） | `rate_limit_threshold` | 30 | **25** | 会动钱的那条链路的入口 |
| `group:verification`（限流命中） | `rate_limit_threshold` | 30 | **25** | 验证入口是公开面 |
| `group:verification`（私有运行时错误） | `private_runtime_error_threshold` | 5 | **3** | 验证链路的内部错误要更早暴露 |
| `group:runtime`（私有运行时错误） | `private_runtime_error_threshold` | 5 | **3** | 同上 |
| `group:verification`（错误率） | `private_runtime_error_rate_threshold` | 0.25 | **0.2** | 分母大时看比例更准 |
| `group:settlement`（状态转移被拒） | `settlement_transition_denied_threshold` | 5 | **3** | 状态机被拒是资金安全的早期信号（口径见下节：只数 `state_machine`） |

### 结算拒绝率的口径（2026-10-13 修订）

「结算迁移被拒」有两种完全不同的成因，**不能混在一个指标里**：

| denial_class | 什么时候产生 | 算不算「状态机被拒」 |
|---|---|---|
| `state_machine` | `guard_stage = route / pipeline`：业务状态机本来就禁止这一步 | **算**。这是「有人在非法穿越状态机」，也就是上面那条阈值想抓的东西 |
| `chain_gate` | `guard_stage = chain`：迁移合法，链上那一步没成，账上已退回、可重试 | 不算。钱一分没动，而且 autosettle **每一轮都会重试** → 一次故障会长成一串事件 |
| `store_conflict` | `guard_stage = store`：落库时的乐观锁冲突 | 不算 |

`settlement_transition_denied_count` / `_rate` 只数 `state_machine`；分母 = 放行的迁移数
+ 被状态机拒的数（不被重试刷大）。链上腿失败另有一条 **HIGH** 告警
`settlement_transition_chain_gate_spike`，按**结算单**去重（同一单重试 20 次 = 1 条），
好让人去查卡住的托管绑定 —— 它**不接自动刹车**：刹车拦不住链上腿失败本身，却会把
autosettle 的放款重试和人工恢复一起掐死。

**自动刹车的迟滞**：`runtime_safety_mode.manual_override_at` 记「最近一次人工放闸」。
自动刹车只认**比它更晚发生**的状态机拒绝；窗口里更早的旧证据不许再把闸拉回去。
没有这一条，人工清闸等于白清 —— 窗口（运维轮询器默认 60 分钟）里那批旧事件还在，
下一轮轮询立刻又点着（2026-10-13 线上实测：02:43 清、02:45 跳回）。

**告警冷却**：`alert_cooldown_minutes = 10`。同一个告警签名 10 分钟内只投递一次 ——
抑制的是重复投递，不是抑制检测本身（检测照跑，告警记录照写，只是不重复推送到 Telegram）。
窗口期 `window_minutes = 15`，基线漂移 `baseline_drift_multiplier = 2.5`、
`baseline_window_minutes = 1440`（24 小时）。

## 怎么改（照这个顺序）

```bash
# 1) 建新版本（draft）
POST /v1/security/policies                    # 带上完整 config（缺的键会用代码默认值补齐）

# 2) 走变更单：创建 → 两人审批 → 应用
POST /v1/security/policies/changes            # {"action":"activate","target_policy_id":"...","required_approvals":2}
POST /v1/security/policies/changes/{id}/review   # {"approver_id":"...","decision":"approve"} ×2（必须是两个不同的人）
POST /v1/security/policies/changes/{id}/apply

# 3) 回滚同理：{"action":"rollback","target_rollback_policy_id":"..."}
```

> ⚠️ **已知薄弱点**：审批里 `approver_id` 是**调用方自报**的（接口只校验调用者是管理员）。
> 所以「两人审批」目前是流程约束，不是密码学约束 —— 一个人拿同一把 admin key、
> 填两个不同的名字就能通过。要变成硬约束，得让审批人各自用自己的身份签名。
> 在此之前，**请把它当作「需要两个人点头」的流程，而不是技术保障**。

## 演练留证（`E7`）

回滚演练的结果写在服务器 `/opt/karma/state/security-policy-drill.json`：

```json
{"at": "...", "active_policy_id": "...", "active_version": 2,
 "drill_policy_id": "...", "rollback_ok": true}
```

闸门 `E7` 读它：`rollback_ok` 必须为真，且不超过 180 天。没有这个文件就记 `HUMAN`。

**2026-10-02 首次演练记录**：建 v3（临时策略）→ 激活 → 回滚到 v2，
三次变更单各不相同、每次都过两人审批，回滚后 `status='active'` 只剩 v2 一行，
版本号与上面钉版一致。演练用的 v3 保留为 `archived`（可追溯）。

## 相关

- `scripts/public-beta-security-gate.sh`（`B5` / `B6` / `B7` / `E7` 的判据）
- `docs/SECURITY_RELEASE_GATES.md`（Gate B / Gate E）
- `docs/SECURITY_INCIDENT_PLAYBOOK.md`（真出事时的处置顺序）
