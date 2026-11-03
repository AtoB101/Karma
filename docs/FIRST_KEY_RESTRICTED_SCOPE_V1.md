# 受限首把钥匙（First Key）· 权限范围版

> 状态：已实现（本分支 `feat/order-contract-dispute-anchor`）。公开铸造端点 +
> 一次性 challenge + 设备/IP 绑定 + 授权后升级，四段闭环均已在代码与测试中落地。

## 1. 要解决什么问题

agent 接入 Karma 的第一步需要一把 API key，但这把钥匙如果和正式钥匙一样全权限，
就等于把花钱能力交给了第一次接进来的进程。更安全的做法是分两段：

1. **首把钥匙**：只能发起消费授权申请（`POST /v1/spending-grants/approval-request`），
   走官方审批页让主人用钱包签名批准 grant；
2. **授权后升级**：主人批准 grant 后，agent 用首把钥匙调升级端点，换发一把
   全量钥匙，之后在 grant 额度内花钱。

## 2. 已实现

- `services/agent_first_key.py`
  - `issue_challenge`：签发一次性 challenge，绑定 `device_id` 与来源 IP，
    并对同一设备/同一 IP 的 pending 数量设上限（`MAX_PENDING_PER_DEVICE` /
    `MAX_PENDING_PER_IP`）。
  - `claim`：一次性 challenge + 设备 + IP 三者都核对通过才铸受限钥匙
    （`scope=["grant:apply"]`，默认 24h TTL）；明文只回一次，challenge 只存 SHA-256。
  - `upgrade`：仅在 agent 存在**活跃未过期**的 spending grant 时，把受限钥匙
    换发为全量钥匙（旧受限密钥立即失效）。
- `api/routes/agent_first_key.py`（公开挂载，无会话依赖，带 `agent_pairing_rate_limit`）
  - `POST /v1/agents/first-key/challenge`
  - `POST /v1/agents/first-key/claim`
  - `GET  /v1/agents/first-key/status/{challenge_id}`（只回状态，不回 challenge）
  - `POST /v1/agents/first-key/upgrade`（要求有效钥匙 + 活跃 grant）
- `services/agent_bootstrap_credentials.py`
  - `mint_restricted_api_key` / `minted_key_scope` / `minted_key_expired` /
    `revoke_minted_api_key`；`mint_agent_api_key` 默认全量。
- `api/middleware/auth.py`
  - 受限钥匙只在白名单前缀放行（`approval-request`、`approval/`、
    `first-key/upgrade`），其余路径一律 403。

安全底线对照：

| 底线 | 状态 |
| --- | --- |
| 不发 `p1_ready`、不直接给花钱能力 | 受限钥匙到不了任何花钱路由 |
| 只发最低权限钥匙 | `scope=["grant:apply"]` |
| 设备/IP 绑定 + 一次性 challenge | `issue_challenge` + `claim` 双向核对 |
| 短效可撤 | 24h TTL + `revoke_minted_api_key` |
| 花钱仍回官网审批页批准 grant | 升级端点必须有活跃 grant 才放行 |

## 3. 测试

```powershell
python -m pytest tests/unit/test_agent_first_key.py -q
python -m pytest tests/unit/test_restricted_first_key.py tests/unit/test_grant_approval.py -q
```

覆盖：challenge 签发与脱敏、错 challenge/错设备/错 IP 拒绝、一次性消费、
设备/IP 数量上限、过期拒绝、无 grant 升级 403、有 grant 升级成功且旧密钥失效、
以及受限钥匙经真实 HTTP 依赖被花钱路由拒绝、在升级路径放行。

## 4. 尚未完成（生产收紧，下一步）

1. **生产模式验证**：`AUTH_ENFORCE_PROTECTED_ROUTES=true` 下把
   `challenge → claim → approval-request → 官方审批页 → upgrade` 端到端跑一遍，
   确认匿名不能绕过。
2. **SDK/操作台接入**：把首把钥匙的 `device_id` 生成、challenge/claim 调用
   封进 SDK 与操作台，普通用户按模板流程点授权即可。
3. **更强防机器人**：当前 challenge 是“一次往返 + 设备/IP 绑定 + 限流”，
   没有 PoW/人机验证；若被批量刷铸造，可再加 work-factor 或邮箱/钱包验证。
