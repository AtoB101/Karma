# Runtime Key 指南

Runtime Key（`KRM_RT_…`）是 **Agent 工作通行证**，用于调用公开的 **Runtime Gateway**（`/runtime/*`）。它不是钱包私钥，不能提现、不能转走 USDC、不能修改锁仓额度。

## 用户只在官方 Console 授权钱包

1. 在 Console「设置 → AI Agent 自动授权中心」配置自动授权策略与额度（演示页将策略保存在浏览器 `localStorage`；生产环境应接入账户级持久化）。
2. 使用钱包对固定文本做 **EIP-191 personal_sign**，调用 `POST /runtime/create-key`。
3. 服务器返回的 `runtime_key` **只显示一次**；关闭后无法再次查看明文，只能吊销后重新生成。

## Agent 只拿 Runtime Key

- SDK：`from karma import KarmaRuntime` 或 `from sdk.runtime_client import KarmaRuntime`。
- 环境变量：`KARMA_RUNTIME_URL`、`KARMA_RUNTIME_KEY`、可选 `KARMA_EXPECTED_CHAIN_ID`、`KARMA_APP_SECRET`（用于校验响应 HMAC）。

## 绑定 agent 公钥（使用时刻硬校验）

Runtime Key 是**不记名令牌**：谁拿到那串 KRM_RT_…，谁就能在额度内花你的钱。
所以铸出 key 之后，agent 应该把自己的 Ed25519 公钥钉在这把钥匙上。

1. agent 侧配好三样东西：

   ```
   KARMA_RUNTIME_KEY=KRM_RT_…
   KARMA_AGENT_ID=<操作台里那个 agent 的 id>
   KARMA_AGENT_PRIVATE_KEY=<base64(32 字节种子) 或 64 位 hex>
   ```

2. agent 启动时先「申请」——这一步只拿到一串匹配码：

   ```python
   rt = KarmaRuntime.from_env()
   pending = await rt.ensure_bound()   # 还没绑：返回 status=pending_activation
   print(pending["activation_code"])   # 例：K7Q2-M4XP —— 把这串码交给主人
   ```

   等价写法：`await rt.bind_key()`；一次性的服务端调用是 `POST /runtime/bind-key`。
   服务端只把公钥存进「待确认」位（`pending_binding`），**绑定还没生效**。
   重复申请（同一把公钥）是幂等的，回 `status=active`，不再发新码。

3. **主人在操作台输入这串匹配码**，绑定才真正落库。确认之后 agent 这边：

   ```python
   await rt.await_binding_activation()   # 轮询到 key_binding=agent，自动打开签名
   ```

   匹配码 3 分钟有效、最多试错 5 次；过期或用完就让 agent 重新申请（旧码同时作废）。
   主人也可以拒绝这次接入，key 本身不受影响。

   为什么非要这一步：Runtime Key 是不记名令牌。以前「谁先调 bind-key 谁就绑上」——
   偷到 key 的人抢先绑自己的公钥，主人反而被挡在门外。现在码在 agent 手里、在主人手里
   各一份，偷 key 的人两样都没有。

4. 绑定之后**每个请求**都要带这四个头，缺一个就是 401：

   | 头 | 内容 |
   | --- | --- |
   | X-Karma-Runtime-Key | KRM_RT_… 明文 |
   | X-Karma-Agent-Signature | Ed25519 签名（base64） |
   | X-Karma-Runtime-Timestamp | UTC 秒，如 2026-09-18T12:00:00Z，容忍正负 300 秒 |
   | X-Karma-Runtime-Nonce | 每次都要不同；重复即 409 |

   签名覆盖下面这段文字（时间戳规范化成 YYYY-MM-DDTHH:MM:SSZ，路径不含查询串，
   body_sha256 对原始请求体字节取 sha256）：

   ```
   Karma Runtime Request
   key_id:<key_id>
   method:<METHOD>
   path:<path>
   timestamp:<timestamp>
   nonce:<nonce>
   body_sha256:<sha256 of raw body>
   ```

5. 换绑不做静默替换：已经绑过别的公钥时一律 409，先吊销再铸新的
   （否则拿到 key 的人可以把真 agent 顶掉）。

操作台侧（都要钱包签名，消息格式见 `services/runtime_wallet.py`）：

| 端点 | 作用 |
| --- | --- |
| `POST /runtime/list-bind-requests` | 拉出「agent 已申请、还没输码确认」的待确认请求（要钱包签名） |
| `POST /runtime/confirm-bind-key` | 输入匹配码 + 钱包签名 → 绑定生效 |
| `POST /runtime/reject-bind-key` | 拒绝这次接入 → 清掉待确认请求 |

还有一条**不需要钱包签名**的：

| 端点 | 作用 |
| --- | --- |
| `POST /runtime/list-pending-binds` | 只认会话（SIWE bearer / `X-Karma-Identity-Id`），返回同名的待确认请求 |

分工：`list-bind-requests` 要钱包签名，身份不可辩驳，适合用户主动发起的动作；
`list-pending-binds` 只认会话，好让操作台一进页面（或每 60 秒轮询一次）就能提示
「有 agent 在申请接入」，看一眼提示不该惊动钱包。返回里只有指纹 / 有效期 / 剩余试错次数，
匹配码本身服务端只存 HMAC，两条都拿不到明文。

`POST /runtime/list-keys` 与 `GET /runtime/permissions` 的返回里都带 `pending_binding`
（没有就是 null），操作台据此显示「有 agent 正在申请接入」。

**没绑公钥的 key 行为完全不变**（服务端托管，认 key 不认人）——升级不会把已经在跑的 agent 打掉。
绑不绑由 agent 决定；但只有绑了，「被偷走的 key 单独没用」才成立。

其它硬约束：

| 约束 | 值 | 为什么 |
| --- | --- | --- |
| key 最长有效期 | 90 天 | 「十年有效的钥匙」等于没有到期时间，出事时没有兜底 |
| 时间戳容忍窗口 | 正负 300 秒 | 拦住原样重放 |
| nonce_required | 含 place_order / request_settlement 时为 true | 会动钱的 key 每请求强制 nonce |
| 匹配码有效期 | 3 分钟 | 码要人念、人敲，暴露窗口越短越好；过期只是这次申请作废，钥匙不用重铸 |
| 匹配码试错上限 | 5 次 | 8 位码（去掉 0/O/1/I）空间足够大，仍然限制暴力尝试 |
| 绑定生效点 | 主人输入匹配码 + 钱包签名 | 「偷到 key 的人抢先绑自己的公钥」这条路被堵死 |

POST /runtime/create-key 的返回里会带绑定声明 binding_scope 与平台签名
binding_scope_signature（配 service_public_key 核对），agent 据此确认「这把 key 是发给我的」。

## 权限子集

允许的权限名：`request_voucher`、`verify_voucher`、`submit_receipt`、`update_progress`、`request_settlement`、`sync_task_status`、`discover_agents`、`place_order`。

| 权限 | 能做什么 | 钱会不会动 |
| --- | --- | --- |
| `discover_agents` | 按需求发现可结算的 agent / 商家 | 不会（只读） |
| `place_order` | 在额度内自己发起一笔委托 | 只出凭证，验收通过才划转 |
| `request_voucher` | 替主人要一份付款凭证 | 凭证即责任，需验收 |
| `verify_voucher` | 核验对方凭证真实、已锁定 | 不会（只读） |
| `submit_receipt` / `update_progress` | 交付后写证据哈希 / 进度 | 不会 |
| `request_settlement` | 验证通过后请求划转 | 会（按结算状态机） |
| `sync_task_status` | 读本身份相关的任务 | 不会 |

## agent 先读边界再干活

```
GET /runtime/policy      # 我能自己拍板到什么程度
GET /runtime/capacity    # 我还有多少额度
```

`/runtime/policy` 只返回调用者自己那把 Runtime Key 对应的策略，不返回任何其他身份的数据。
其中 `per_order_auto_approve_usdc` 是「不问我就能下单」的上限，`per_order_hard_cap_usdc`
是硬上限（超过直接 403）。超过自动额度但没超硬上限时，`POST /runtime/place-order`
不会建单、不会扣额度，而是返回 `status=awaiting_owner_confirmation`，等主人在操作台确认。

## 发现与下单

```
POST /runtime/discover      # {requirement_text, amount?, limit?, client_nonce}
POST /runtime/place-order   # {requirement_text, amount, seller_identity_id?, client_nonce, auto_complete?}
```

`place-order` 的边界全部在服务端计算：Runtime Key 的单笔 / 每日上限、已保存的
automation-policy（`auto_enabled`、`responsibility_acknowledged`、`single_limit`）。
客户端传什么都不能放宽。

禁止的能力（Runtime Key **永远不能**执行）包括：提现、转 USDC、修改锁仓、提升额度、改钱包、改安全规则、删除账单、篡改已接受任务、绕过争议与结算状态机等——详见 `docs/security-boundary.md`。

## 查一把钥匙现在绑没绑

```
GET /runtime/permissions
```

返回里的 key_binding 为 service（没绑）/ agent（已绑），agent_fingerprint 是绑定公钥的指纹
（前 16 位给用户肉眼对照），nonce_required 表示这个 key 是否每请求强制 nonce。

`pending_binding` 不为 null 表示「有 agent 申请了、主人还没输匹配码」：里面带
`agent_fingerprint`、`expires_at`、`attempts_left`、`expired`。**它不算绑定生效**——
此时 key 仍是服务端托管，agent 带签名调用会被拒（403）。

## 铸造时指明给某个 agent 的钥匙：未激活不能花钱

上面那套绑定是**事后生效**的：绑上之后光有 key 字符串花不出钱。但「铸造 → 激活」这段
窗口期以前是敞开的 —— 钥匙还没绑任何公钥，谁抄到那串 KRM_RT_… 谁就能在额度内花。
现在这条堵上了。

铸造时 `agent_binding` 非空（这把钥匙明确是给某个 agent 的；该字段在钱包签名消息里，
用户授权过）的钥匙，落到 `key_binding = agent_pending`：

* 拿它调任何动作端点（`/runtime/place-order`、`/runtime/request-voucher`、
  `/runtime/request-settlement`、`/runtime/capacity` …）一律 **403**，理由是
  `runtime key is not activated yet`；
* 只有 `GET /runtime/permissions` 放行 —— agent 得能读到 `activation_required: true` 与
  `activation_code_ttl_seconds`（匹配码有效期 180 秒），知道自己差哪一步；
* 用户输码 + 钱包签名（`POST /runtime/confirm-bind-key`）后 `key_binding` 变成 `agent`，
  之后按「逐请求验签」那一套走；
* **没有「钥匙激活期限」这回事**：只要没输对匹配码，这把钥匙就一直不能用（不是「过期
  就废」，是「没激活就废」）。有 3 分钟时限的只是**匹配码**（`BIND_CODE_TTL_SECONDS = 180`）：
  码过期表示这次申请作废，让 agent 重新申请一次就会给新码，钥匙本身不用重铸；
* 拒绝一次接入**不等于**放行：待确认位清掉了，钥匙仍停在 `agent_pending`，照样花不了钱；
* **没指明 agent 的托管钥匙不受影响**（`key_binding = service`，认 key 不认人），
  已经在跑的 agent 不会被这次改动打掉。

换句话说：偷到 key 的人能做的最坏一件事，是让那把还没激活的钥匙不能用；他要花你的钱，
仍然必须过你钱包那一关。

`POST /runtime/create-key` 与 `POST /runtime/list-keys` 的返回里带 `activation_required`；
`POST /runtime/create-key` 与 `GET /runtime/permissions` 另有 `activation_code_ttl_seconds`。
操作台的交付包卡片据此标「未激活（等匹配码）」。

## 吊销 / 取消绑定

`POST /runtime/revoke-key`，携带与创建时一致的钱包签名（消息格式见服务端 `services/runtime_wallet.py`）。
吊销是终局：这把钥匙从此花不了钱，也再绑不上 agent。

只想把 agent 摘掉、钥匙留着，用**一键取消绑定**（操作台「设置 → 已授权 · 一键取消绑定」）：

```
POST /runtime/list-bound-keys   # 会话鉴权：列出已绑 agent 公钥的钥匙
POST /runtime/unbind-key        # 钱包签名：摘掉公钥，钥匙回到 agent_pending
```

`unbind-key` 摘掉公钥后把 `key_binding` 置回 `agent_pending`：**这把钥匙谁都花不了**，
要用就重新走一次接入（agent 再申请、主人再输一次匹配码）。它不会退回 `service`（托管）
状态 —— 那等于把钥匙变回不记名令牌，谁抄到谁能花，正好和用户按这个按钮的意思相反。
想彻底作废用 `revoke-key`。

## 看得见：最近调用 + 站内提醒

额度表只回答「今天花了多少」，回答不了「哪一次花掉的、哪一次被拒了」。所以另有两件事：

```
POST /runtime/key-calls      # 会话鉴权：这把钥匙最近调了哪些动作端（默认 20 条，最多 100）
POST /runtime/list-notices   # 会话鉴权：自己的站内提醒（unread_only=true 只给未读）
POST /runtime/ack-notice     # 会话鉴权：点过就算读过；不给 notice_ids 就是「全部已读」
```

`key-calls` 记的是**动作端的每一次调用**，成功（`ok`）、被权限/额度/nonce/状态拒掉
（`rejected`，带 HTTP 码与服务端原话）、异常（`failed`）都记。只记成功等于把最有价值的
一半藏起来——主人展开卡片，最想确认的恰恰是「有没有被拒、为什么被拒」。

写入是**旁路**：日志写不进数据库绝不连累 agent 的请求（见 `services/runtime_call_log.py`）。
读路径（`/runtime/permissions`、`/runtime/task-status/*`）不记，否则「最近调用」会被自己刷屏。

三条接口都只认会话（SIWE bearer 或 `X-Karma-Identity-Id`），且只放本人：别人的会话 403，
拿别人名下的 `key_id` 来查是 404 —— 连「这把钥匙存不存在」都不给非本人看。列一下、
看一眼历史都不该惊动钱包签名。

站内提醒目前两个来源：`key_bound`（agent 接入生效）与 `key_unbound`（主人亲手取消绑定）。
取消绑定是不可逆动作，闪一行提示关掉就没了；落一条记录、点过才消，才对得起这个位置。
操作台侧栏「设置」会挂紫点，卡片也会高亮。

**邮件通道没有做**：现网没有 SMTP 凭据（`config/settings.py` 里没有任何 SMTP 配置），
凭空写一段发信代码等于没验证过的代码。要发信请先给 SMTP（主机/端口/账号/发件人），
再补这一段。

## 相关文档

- `docs/sdk-quickstart.md` — 安装与 30 分钟接入路径  
- `docs/agent-runtime-integration.md` — Agent 生命周期与 Runtime 对齐  
