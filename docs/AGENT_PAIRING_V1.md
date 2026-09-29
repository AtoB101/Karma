# Agent 配对接入 v1（自助接入）

让你的 agent 自己走进 Karma：**agent 发起并出码 → 主人在操作台输入这串码、核对、
划额度、点批准** → 批准就是交付，agent 下一次轮询自己把凭据领走。

全程没有「把密钥复制给 agent」这一步，也没有「agent 向用户索要密钥」这个动作。

**方向只有一个，不能反：** 码由 agent 产生、由主人输入操作台。「操作台生成一串码、
主人再念给 agent」是错的方向 —— 它把一次可能被偷听的转述塞进了必经之路，而且让主人
多做一个没有信息量的动作。主人如果仍想加一道手递手的确认，可以在操作台**主动**点
「签发交接码」：签了，agent 领取时就必须带上它（3 分钟有效）；不签，就是批准即交付。

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

## 2. 三个码 · 必需要的 + 可选的

| 码 | 谁产生 / 谁持有 | 方向 | 作用 | 存储 |
|----|----------------|------|------|------|
| `user_code` | agent 申请时产生，打在屏幕上 | **agent → 主人** | 主人在操作台里对上号（如 `K4QP-3M2X`） | 明文（单独给到它也没有任何权限） |
| `pairing_code` | agent 申请时拿到 | agent → 服务端 | 领取凭据的凭证（申请时只回一次） | 只存 SHA-256 |
| `handoff_code` | **可选** —— 主人主动点「签发交接码」才产生 | 操作台 → agent | 主人加的第二把锁：证明「凭据是手递手交出去的」 | 只存 SHA-256，3 分钟 |
| 交付内容 | 服务端暂存 | — | API Key（+ 可选的 Runtime Key） | 领取后立刻清除，只发一次 |

`user_code` 与 `handoff_code` 都用 `ABCDEFGHJKMNPQRSTUVWXYZ23456789`（去掉 I/L/O/0/1），
它们都是**人从一块屏幕读到另一处**的短码。

**默认路径（不签发交接码）：** 主人一批准，`pairing_code` 就是唯一的钥匙 ——
agent 直接 `claim` 拿到凭据，回执里标 `"handoff": {"required": false, "consumed": true}`。

**加固路径（主人主动签发交接码）：** 从签发那一刻起，`claim` 必须同时带上 `pairing_code`
和 `handoff_code`，回执里标 `"required": true`。没带码会拿到 `status=awaiting_handoff`；
连错 5 次（`HANDOFF_MAX_ATTEMPTS`）就地作废整次配对。

**为什么这样就够安全：** `pairing_code` 是 256 位随机串、只在申请响应里出现过一次、
磁盘上只有 SHA-256。别人光知道 `user_code`（它印在屏幕上、可能被旁观）什么都拿不到 ——
没有 `pairing_code` 就换不到凭据。所以「码被看到」不等于「钱被领走」。
无论走哪条路径，这两串码出现在聊天记录、截图、日志里都不要紧：
`handoff_code` 明文只在 `handoff` 的响应里出现一次，落库同样只有 SHA-256。

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
  |                                |<-- POST /v1/agent-pairing/approve --|  主人核对 -> 划额度 -> 批准（= 交付）
  |                                |<-- POST /v1/agent-pairing/attach-runtime-key --  （可选）挂上刚签发的 Runtime Key
  |                                |                                     |
  |-- POST /v1/agent-pairing/claim {pairing_code} -->                   |  默认：这就够了
  |<-- credentials（api_key[, runtime_key]）+ env_snippet ---------------|  一次性；回执 handoff.required=false
  |                                |                                     |
  |  ---- 只有主人额外点了「签发交接码」时，下面这条附加锁才生效 ----        |
  |-- POST /v1/agent-pairing/claim {pairing_code} -->                   |
  |<-- {"status":"awaiting_handoff","handoff_state":"active"} ----------|  没带码 -> 领不走
  |                                |<-- POST /v1/agent-pairing/handoff --|  主人点「签发交接码」
  |                                |--- 200 {handoff_code, 3 分钟有效} -->|  明文只在这一条响应里
  |  主人把那串码交给 agent --------------------------------------------->|
  |-- POST /v1/agent-pairing/claim {pairing_code, handoff_code} ------>  |
  |<-- credentials（api_key[, runtime_key]）+ env_snippet ---------------|  一次性；回执 handoff.required=true
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
- `status=awaiting_handoff`：**只有主人主动签过交接码**才会走到这里。带 `handoff_state`
  （`none` 没签发 / `expired` 过期了 / `active` 签了但没传码），按 `poll_interval_seconds`
  继续轮询；主人签发之后带上 `handoff_code` 再来。主人没签过时不会出现这个状态。
- `status=approved`：**凭据在这里返回，且只返回这一次**。回执里的
  `"handoff": {"required": …, "consumed": true}` 如实说明这次有没有附加锁。
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
- **领取凭证（见 §2）**：`pairing_code` 是 256 位随机串，只在申请响应里出现过一次、磁盘上只有
  SHA-256。光知道 `user_code` 领不走任何东西。key 被「捡到」不等于被「领走」。
- **可选加固 — 交接码 3 分钟 + 5 次尝试上限**：主人主动签发后，`HANDOFF_TTL_SECONDS = 180`，
  超时即失效、重签作废旧码；连错 5 次作废整次配对。窗口故意做短：这是可选的即时动作，
  不需要长窗口。
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

# 2. 主人批准后直接领 —— 默认不需要任何其它码（只成功一次）
curl -s -X POST https://karma-network.ai/v1/agent-pairing/claim \
  -H 'Content-Type: application/json' \
  -d '{"pairing_code":"<上一步的 pairing_code>"}'

# 2b. 万一主人额外点过「签发交接码」：上一步会回 awaiting_handoff，
#     那就带上主人给你的那串，再领一次
curl -s -X POST https://karma-network.ai/v1/agent-pairing/claim \
  -H 'Content-Type: application/json' \
  -d '{"pairing_code":"<上一步的 pairing_code>","handoff_code":"<主人给你的那串>"}'

# 3. 用拿到的凭据自检
curl -s https://karma-network.ai/v1/agents/mine -H "X-Karma-Api-Key: $KARMA_API_KEY"
curl -s https://karma-network.ai/runtime/policy  -H "X-Karma-Runtime-Key: $KARMA_RUNTIME_KEY"
```

MCP 不是前提：任何会发 HTTP 的 agent 都能接入（`X-Karma-Api-Key` / `X-Karma-Runtime-Key`）。
见 [mcp-adapter-guide.md](./mcp-adapter-guide.md)。

不想手写这三个请求的，`packages/karma-openclaw` 已经把它包成 MCP 工具：

```text
karma_pairing_start(agent_name="claw-001", requested_side="seller", requested_vertical="food")
karma_pairing_status()                       # 等批准 / 已交付
karma_pairing_claim()                        # 批准即交付：凭据只写 ~/.karma/agent.env（0600）
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
