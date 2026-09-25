# Agent 配对接入 v1（自助接入）

让你的 agent 自己走进 Karma：agent 发起 → 主人在操作台批准 → 主人在操作台**签发一串交接码** →
把交接码交给 agent → agent 自己把凭据领走。

全程没有「把密钥复制给 agent」这一步，也没有「agent 向用户索要密钥」这个动作。
两个短码方向相反、互相咬合：**配对码**证明「你就是当初申请的那一个进程」，
**交接码**证明「主人真的把凭据交到了你手上」—— 缺一个都领不走。

---

## 1. 为什么要有这一版

在此之前，把一个 agent 接进 Karma 只有两条路：

- **操作台手动版**：主人在「授权向导」里生成 API Key / Runtime Key，再复制到 agent 的运行环境
  （「交给 Agent」面板做的事）。安全，但用户要抄一串密钥。
- **owner-connect**：主人点「一键接入 Agent」，Karma 服务端托管该 agent 的 Ed25519 运行密钥。
  仍然只有主人这一侧能发起。

两条路都要求**主人先动手**。配对把顺序倒过来：agent 先发起并拿到一串短码，主人只做两个决定
（批准接入 / 划多少额度），凭据由 Karma 直接交给持配对码的那个进程。

**方向不能反。** 「把授权好的 key 交给 agent」是正当的（agent 拿到的是 Runtime Key，
带着权限集、单笔上限、每日上限、到期时间）；但「agent 向用户索要 key」是标准钓鱼话术。
本协议只实现前者：控制台是唯一能铸造凭据的地方，agent 只能**领取**已经铸造好、且属于
自己这次配对的凭据。

---

## 2. 四个码 · 两把锁

| 码 | 谁持有 | 方向 | 作用 | 存储 |
|----|--------|------|------|------|
| `pairing_code` | agent | agent → 服务端 | 轮询领取凭据的凭证（申请时只回一次） | 只存 SHA-256 |
| `user_code` | 屏幕上 | agent → 主人 | 主人在操作台里对上号（如 `K4QP-3M2X`） | 明文（单独给到它也没有任何权限） |
| `handoff_code` | 操作台屏幕上 | **主人 → agent** | 证明「主人真的把凭据交给了这个进程」 | 只存 SHA-256，3 分钟 |
| 交付内容 | 服务端暂存 | — | API Key（+ 可选的 Runtime Key） | 领取后立刻清除，只发一次 |

`user_code` 和 `handoff_code` 都用 `ABCDEFGHJKMNPQRSTUVWXYZ23456789`（去掉 I/L/O/0/1），
因为两者都是**人从一块屏幕读到另一处**的短码（`user_code` 是 agent 屏幕 → 主人，`handoff_code`
是操作台屏幕 → agent）。

**两把锁各管一半，缺一个都领不走凭据：**

- 只有 `pairing_code`（它申请时拿到的）：`claim` 回 `status=awaiting_handoff`，没有凭据。
- 只有 `handoff_code`（比如聊天记录被人看到）：它换不到任何东西 —— 还要对上 `pairing_code`。
- 两个都对：凭据发出去，两串码同时作废。

正因为「单独一串码换不到任何东西」，这两串码**就算出现在聊天记录、截图、日志里也不要紧**；
`pairing_code` 明文只在 `request` 的响应里出现一次，`handoff_code` 明文只在 `handoff`
的响应里出现一次，两者落库都只有 SHA-256。

---

## 3. 端到端时序

```
agent                          Karma API                      主人（操作台 · Agent 接入 · 配对接入）
  |                                |                                     |
  |-- POST /v1/agent-pairing/request -->                                |
  |<-- pairing_code + user_code + verification_uri + 15 分钟有效期 -----|
  |                                |                                     |
  |  把 user_code / verification_uri 给主人 ----------------------------->|
  |                                |<-- GET  /v1/agent-pairing/lookup ---|  看：谁在申请、公钥指纹、申请方向/行业
  |                                |--- 200 (pending) ------------------>|
  |                                |<-- POST /v1/agent-pairing/approve --|  批准：建 agent 身份 + 铸造 bootstrap API Key
  |                                |<-- POST /v1/agent-pairing/attach-runtime-key --  （可选）挂上刚签发的 Runtime Key
  |                                |                                     |
  |-- POST /v1/agent-pairing/claim -->                                  |  只有 pairing_code：还不够
  |<-- {"status":"awaiting_handoff","handoff_state":"none"} ------------|
  |                                |<-- POST /v1/agent-pairing/handoff --|  主人点「签发交接码」
  |                                |--- 200 {handoff_code, 3 分钟有效} -->|  明文只在这一条响应里
  |  主人在屏幕上看到，读给 / 输给 agent ------------------------------->|
  |-- POST /v1/agent-pairing/claim {pairing_code, handoff_code} ------>  |
  |<-- credentials（api_key[, runtime_key]）+ env_snippet ---------------|  ← 只有这一次
  |-- POST /v1/agent-pairing/claim -->                                  |
  |<-- {"status":"claimed"}（没有任何凭据）------------------------------|
```

---

## 4. API 参考

### 4.1 `POST /v1/agent-pairing/request`（公开，限流 10 次/分钟）

agent 侧发起。返回体里的 `pairing_code` **只出现这一次**。

```json
{
  "agent_name": "OpenClaw 采购助手",
  "platform": "openclaw",
  "public_key": "ed25519:...",
  "endpoint_url": "https://agent.example.com/karma",
  "self_description": "替我向供应商下单",
  "requested_side": "seller",
  "requested_vertical": "food",
  "answers": {"industry_ids": ["food_delivery"], "service_specs": {...}}
}
```

`answers` 是 agent 对自己业务的申报（行业硬指标）。**它是草稿，不是最终值**：

- 操作台的配对面板会按 `requested_vertical` 解析出的行业，拉出这个行业的
  `required_service_spec`，把申报值预填进表单，主人在屏幕上核对 / 直接改；
- 提交时以主人面前那份表单为准 —— 行业（`industry_ids`）和该行业的
  `service_specs[industry_id]` 都会被主人的选择覆盖；
- 服务端仍会用同一套行业契约再校验一遍（`_validate_service_specs`），
  不合规的硬指标在批准那步被 400 拒掉，责任仍在申报方。

`requested_vertical` 可以是目录里的 `industry_id`，也可以是 `services/agent_one_click.py`
里的别名（`food` → `food_delivery`、`hotel` → `hotel_booking` …）。服务端在 `request`
时就归一成 `industry_id`，并通过 `requested_industry_id` 回给操作台；两边因此不会
各认一套行业名。`service_specs` 的键请用归一后的 `industry_id`。

返回：

```json
{
  "pairing_code": "<只在这里出现，agent 自己存好>",
  "user_code": "K4QP-3M2X",
  "verification_uri": "https://karma-network.ai/console/?pair=K4QP-3M2X",
  "expires_at": "2026-09-18T09:14:16Z",
  "poll_interval_seconds": 3,
  "claim_endpoint": "/v1/agent-pairing/claim"
}
```

同一个 IP 最多同时挂 10 个未处理的请求；超过返回 429。

### 4.2 `POST /v1/agent-pairing/claim`（公开，限流 10 次/分钟）

```json
{"pairing_code": "...", "handoff_code": "K4QP-3M2X"}
```

- `status=pending`：主人还没批。返回 `poll_interval_seconds`，按它轮询即可。
- `status=awaiting_handoff`：批准了，但第二把锁还没对上。带 `handoff_state`
  （`none` 没签发 / `expired` 过期了 / `active` 签了但没传码），按 `poll_interval_seconds`
  继续轮询；主人签发之后带上 `handoff_code` 再来。
- `status=approved`：**凭据在这里返回，且只返回这一次**，并带
  `"handoff": {"required": true, "consumed": true}`。
- `status=claimed|denied|expired`：没有凭据可交。

`handoff_code` 对不上返回 403；**连着错 5 次**（`HANDOFF_MAX_ATTEMPTS`）就地作废这次配对
（`status=expired`、交付内容清空），只能重新申请。

`approved` 的返回体：

```json
{
  "status": "approved",
  "agent_id": "agent-1b4bb344ebfb",
  "owner_identity_id": "kid_...",
  "credentials": {
    "api_key": "karma_agent-..._...",
    "agent_public_key": "ed25519:...",
    "runtime_key": "KRM_RT_...",
    "runtime_key_id": "....",
    "store_now": true
  },
  "env_snippet": {
    "KARMA_AGENT_ID": "agent-...",
    "KARMA_RUNTIME_URL": "https://karma-network.ai",
    "KARMA_API_KEY": "karma_agent-..._...",
    "KARMA_RUNTIME_KEY": "KRM_RT_..."
  }
}
```

### 4.3 主人侧接口（都要登录态：SIWE JWT / API Key / 身份头）

| 方法 | 路径 | 说明 |
|------|------|------|
| `GET` | `/v1/agent-pairing/lookup?user_code=` | 看清楚谁在申请（名称、平台、公钥指纹、回调地址、申请方向/行业、自述、有效期）。不含任何密钥。 |
| `POST` | `/v1/agent-pairing/approve` | 批准：建 agent 身份 + 铸造 bootstrap API Key，放进这次配对的交付里。**响应里不含密钥**。 |
| `POST` | `/v1/agent-pairing/deny` | 拒绝：清空交付内容。 |
| `POST` | `/v1/agent-pairing/attach-runtime-key` | 把已经签发的 Runtime Key 挂进这次配对（校验归属身份 + agent 绑定）。 |
| `POST` | `/v1/agent-pairing/handoff` | **签发交接码**（批准后才可签）：3 分钟有效、明文只在响应里出现一次、重签当场作废旧码。 |
| `GET` | `/v1/agent-pairing/mine` | 本身份名下发生过的配对（含状态与「有没有凭据」）。 |

---

## 5. 安全边界

- **一次性**：凭据只在第一次 `claim` 返回；返回后服务端立即清除该次配对的明文。
  第二次 `claim` 只会拿到 `{"status": "claimed"}`。
- **两把锁（见 §2）**：光有 `pairing_code` 领不走凭据，还必须带上主人当场签发的
  `handoff_code`；光有 `handoff_code` 也换不到东西。所以 key 被「捡到」不等于被「领走」——
  捡到的人既没有 agent 那半串，也没在主人操作台上点过「签发」。
- **交接码 3 分钟 + 5 次尝试上限**：`HANDOFF_TTL_SECONDS = 180`，超时即失效、重签作废旧码；
  连错 5 次作废整次配对。窗口故意做短：主人把码读给 agent 是即时动作，不需要长窗口。
- **身份绑定**：`approve` 用的是已认证的主身份；`attach-runtime-key` 会核对 Runtime Key
  的 `karma_identity_id` 是否就是这个主人，且 `agent_binding` 与配对里的 agent 一致。
- **额度仍然是服务端硬约束**：`Runtime Key` 自带 `permissions[]` / `single_limit` /
  `daily_limit` / `expire_time`，超限在服务端 403，不靠 agent 自律。
- **但 `agent_binding` 不是访问控制**（现状，别误读）：它只在 `attach-runtime-key`
  这一步用来防两笔配对串号；`/runtime/*` 的每个请求都不会校验调用方是不是被绑定的那个
  agent。也就是说 Runtime Key 是**不记名令牌** —— 谁拿到它，谁就能在这把钥匙的
  `permissions` / 单笔 / 当日额度内动用主人授权的钱。要做到「只许指名的 agent 用」，
  还需要在 `api/routes/runtime_gateway.py::get_runtime_context` 增加一步调用方身份证明。
- **撤销**：`POST /v1/agents/owner-revoke` 停用 agent 并销毁 Karma 托管的运行密钥，
  与手动接入完全同一套。
- **过期**：`user_code` 默认 15 分钟（`DEFAULT_TTL_SECONDS`）。过期后既不能批准，
  也不能领取，凭据被清空。
- **限流**：公开的两个端点各 10 次/分钟（按客户端 IP），`request` 还有每 IP 10 个未处理请求的上限。
- **不落密钥**：`pairing_code` 与 `handoff_code` 都只存 SHA-256（与
  `services/agent_bootstrap_credentials.py` 同一口径）；控制台侧的
  `lookup` / `mine` 响应永远含 `handoff_state`、永不含 `handoff_code` 明文，也不含
  `api_key` / `runtime_key`，有专门的测试钉住这一点（`tests/unit/test_agent_pairing.py`）。

---

## 6. 和另外两条路的关系

| 路径 | 谁发起 | 凭据怎么到 agent | 适用 |
|------|--------|------------------|------|
| 授权向导 + 交给 Agent | 主人 | 主人复制粘贴 env | 单机、自己看着 agent 跑 |
| owner-connect | 主人 | 主人把 API Key 交给 agent | 主人替 agent 建档 |
| **配对（本文）** | **agent** | **agent 自己来领，一次性** | 第三方 agent、远程 agent、要「用户点一下」的场景 |

三条路最终落到同一套凭据与同一套限额，撤销也是同一个接口。

---

## 7. Agent 侧最小示例

```bash
# 1. 发起配对，把 user_code 给主人
curl -s -X POST https://karma-network.ai/v1/agent-pairing/request \
  -H 'Content-Type: application/json' \
  -d '{"agent_name":"OpenClaw 采购助手","platform":"openclaw","requested_side":"seller","requested_vertical":"food"}'

# 2. 主人批准后，先用 pairing_code 探一次 —— 会拿到 awaiting_handoff
curl -s -X POST https://karma-network.ai/v1/agent-pairing/claim \
  -H 'Content-Type: application/json' \
  -d '{"pairing_code":"<上一步的 pairing_code>"}'

# 3. 主人点「签发交接码」并把那串码给你，再带上它领凭据（只成功一次）
curl -s -X POST https://karma-network.ai/v1/agent-pairing/claim \
  -H 'Content-Type: application/json' \
  -d '{"pairing_code":"<上一步的 pairing_code>","handoff_code":"<主人给你的那串>"}'

# 4. 用拿到的凭据自检
curl -s https://karma-network.ai/v1/agents/mine -H "X-Karma-Api-Key: $KARMA_API_KEY"
curl -s https://karma-network.ai/runtime/policy  -H "X-Karma-Runtime-Key: $KARMA_RUNTIME_KEY"
```

MCP 不是前提：任何会发 HTTP 的 agent 都能接入（`X-Karma-Api-Key` / `X-Karma-Runtime-Key`）。
见 [mcp-adapter-guide.md](./mcp-adapter-guide.md)。

不想手写这三个请求的，`packages/karma-openclaw` 已经把它包成 MCP 工具：

```text
karma_pairing_start(agent_name="claw-001", requested_side="seller", requested_vertical="food")
karma_pairing_status()                       # 等批准 / 等交接码 / 已交付
karma_pairing_claim(handoff_code="K7P2-9RVX")  # 凭据只写 ~/.karma/agent.env（0600）
karma_pairing_local_status()                 # 本机握着什么（只报指纹）
```

`karma_pairing_start` 把 `pairing_code` 落到 `~/.karma/pairing/<user_code>.json`（0600），
返回值里没有它；`karma_pairing_claim` 返回值里没有明文凭据，只有 `sha256:…` 指纹。
所以整个接入过程可以放心地出现在聊天记录里。

---

## 8. 相关代码

| 位置 | 作用 |
|------|------|
| `services/agent_pairing.py` | 配对存储与状态机（request → approve → handoff → claim，两把锁 + 一次性交付） |
| `api/routes/agent_pairing.py` | 公开端点 + 主人端点，`api/app.py` 里分成两个 router 挂载 |
| `api/routes/agents.py::connect_owner_agent` | 与 `/v1/agents/owner-connect` 共用的建 agent 逻辑 |
| `apps/console/scripts/cyber-pairing.js` | 操作台「配对接入」面板 |
| `tests/unit/test_agent_pairing.py` | 端到端 + 一次性交付 + 静态接线 + 六语言文案 |
