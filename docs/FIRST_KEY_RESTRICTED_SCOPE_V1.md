# 受限首把钥匙（First Key）· 权限范围版

> 状态：已实现范围记账 + 中间件强制（本分支 `feat/order-contract-dispute-anchor`）。
> 目标：新用户/新 agent 拿到的**第一把钥匙**只能用来发起消费授权申请，不能直接花钱。

## 1. 要解决什么问题

agent 接入 Karma 的第一步需要一把 API key，但这把钥匙如果和正式钥匙一样全权限，
就等于把花钱能力交给了第一次接进来的进程。更安全的做法是分两段：

1. **首把钥匙**：只能 `POST /v1/spending-grants/approval-request`（发起授权申请），
   走官方审批页让主人用钱包签名批准 grant；
2. **授权后**：agent 在 grant 额度内花钱（这一步仍由现有 spending-grant 门控制，
   与首把钥匙无关）。

## 2. 本轮已实现

- `services/agent_bootstrap_credentials.py`
  - `mint_restricted_api_key(agent_id, scope=..., ttl_seconds=...)`：铸一把带
    `scope` 与可选 `expires_at` 的受限钥匙；拒绝 `*` 通配范围。
  - `mint_agent_api_key`：现有全量钥匙，默认 `scope=["*"]`、无过期（行为不变）。
  - `minted_key_scope` / `minted_key_expired` / `revoke_minted_api_key`：查范围、
    查过期、按 agent id 撤销（含持久化）。
  - `verify_minted_api_key`：过期钥匙一律验签失败（不可再用）。
- `api/middleware/auth.py`
  - `_minted_api_key_scope`：只识别**铸造出来的**受限钥匙；`AUTH_API_KEYS` 里
    配置的钥匙永远是全量。
  - `_enforce_minted_key_scope`：受限钥匙只在白名单前缀
    （`/v1/spending-grants/approval-request`、`/v1/spending-grants/approval/`）
    放行，其余路径 403。
  - `get_current_agent_id` 现在带 `request`，所有走该依赖的受保护路由自动获得
    上述强制，无需逐路由改动。

安全底线对照：

| 底线 | 状态 |
| --- | --- |
| 不发 `p1_ready`、不直接给花钱能力 | 受限钥匙到不了任何花钱路由 |
| 只发最低权限钥匙 | `scope=["grant:apply"]`，其余一律拒绝 |
| 短效可撤 | `ttl_seconds` 硬过期 + `revoke_minted_api_key` |
| 花钱仍回官网审批页批准 grant | 未改变；受限钥匙只能发起审批 |
| 设备/IP 绑定 + 一次性 challenge | 待做（见下） |

## 3. 测试

```powershell
python -m pytest tests/unit/test_restricted_first_key.py -q
python -m pytest tests/unit/test_grant_approval.py tests/unit/test_auth_security.py -q
```

覆盖：范围记账、`*` 拒绝、过期失效、撤销失效、非白名单路径 403、白名单路径放行、
以及受限钥匙经真实 HTTP 依赖打开 `approval-request` 返回 200。

## 4. 尚未完成（下一增量的顺序）

1. **公开的首把钥匙铸造端点**：把 `mint_restricted_api_key` 接到一个带
   `agent_pairing_rate_limit` / `register_agent_rate_limit` 限流的公开端点，
   并要求一次性 challenge（防机器人批量铸造）。
2. **设备/IP 绑定**：铸造时记录 `device_id` 与来源 IP，同一设备/IP 短时窗口只
   允许铸造一次，可撤销。
3. **授权后升级路径**：主人批准 grant 后，要么给 agent 换发全量钥匙，要么让
   grant 本身成为花钱凭据（不依赖钥匙全量）——当前实现没有升级步骤，受限钥匙
   即便拿到 grant 也仍不能走花钱路由。这是下一步必须补上的闭环缺口。
4. **生产收紧**：`AUTH_ENFORCE_PROTECTED_ROUTES=true` 下验证上述端点与
   官方审批页端到端，确认匿名不能绕过。

> 注意：`mint_restricted_api_key` 目前只作为服务函数存在，未被任何路由调用，
> 因此现有行为零变化；等第 4 点做完才真正接入用户流程。
