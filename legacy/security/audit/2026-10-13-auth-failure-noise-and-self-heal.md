# 401 噪声定性 + 会话过期自愈 + 证据窗口（2026-10-13）

承接上一轮（`2026-10-13-stranded-auto-confirm-and-self-deal.md`）留下的一个未查信号：
告警回放 1440m 窗口里有一大片 `auth_failure_spike`（`/v1/security/runtime/safety-mode: 20`、
`/v1/capacity/…: 254`……）。本轮把它查清、定性，并在**源头**补上自愈，不靠调阈值糊过去。

## 1. 结论先说

**不是攻击，是一个客户端拿过期会话在轮询。** 证据（线上 `security_events.jsonl`，6887 行）：

```
failed_auth 总数        : 6746（2026-10-01 → 2026-10-13）
status                  : 6746/6746 全是 401
actor_id                : 6746/6746 全是 anonymous（压根没带上有效凭证）
method                  : GET 6692 / POST 44 / PUT 10
撞的路径                : 全是操作台读接口 —— /v1/capacity/<kid>[+/allocations|/chain]、
                          /v1/identity/role-profiles、/v1/payments/ledger、/v1/escrow/<kid>、
                          /v1/agents/mine、/v1/console/capabilities、/v1/security/runtime/safety-mode
登录/换 token 端点       : group:auth 只有 3 条
时间形状                : 按「人开着操作台的那些小时」成簇，跨 12 天；不是一次性尖峰
最后一次                : 2026-10-13 03:25 UTC，之后 12h+ 一条没有
```

判定依据（逐条排除「像攻击」的形状）：

* **没有撞密钥**：真正的 credential stuffing 会堆在 `/v1/auth/*`、`/v1/identities/*/verification`，
  而且 `actor_id` 会是各种不同账号名。这里 `group:auth` 只有 3 条，且全是 `anonymous`。
* **不是分散来源**：命中路径全是**同一套操作台读接口**、且集中在路径里那个固定身份 id。
* **量级就是轮询**：峰值约 250 条/小时/端点 ≈ 每 15 秒一次 —— 正好是操作台
  `data-sync-interval-ms` 的默认节拍，不是压测/爆破的量级。

对照 `build_security_ops_alert_report` 的实测：

```
window=15m   alerts=0   escalation=none      ← 实时窗口：干净
window=60m   alerts=0   escalation=none      ← 告警出口 poller 用的 60m：也干净
window=1440m alerts=19  escalation=watch     ← 只有「回放 24h」才把这批历史噪声捞出来
```

也就是说：**线上现在没响**，那批 401 只是躺在 24h 回放窗口里的历史噪声。但它的存在本身是个
问题 —— `auth_failure_spike` 是 HIGH，噪声会把真信号淹掉（告警疲劳），所以要在源头治。

## 2. 根因（操作台不是没处理，是漏了一条路径）

操作台**已经**有会话自愈：`karma-public-api.js` 的 `karmaFetch` 遇到会话类失败会静默
`KarmaWalletAuth.reauth()` 续签一次，续不上就 `markExpired()`。问题出在 `markExpired()`：

```js
function markExpired() {
  if (expiredNotified) return;
  expiredNotified = true;
  setStatus("会话已过期 · 请重新连接钱包", false);
  emitEvent("karma-session-expired");   // 只提示 + 关入口门禁，令牌没清
}
```

它**没有清掉 `KARMA_ACCESS_TOKEN`**。而 `console-sync.js` 的 `refreshAll()` 是这么判「要不要发
受保护读」的：

```js
var authed = !!(global.KARMA_ACCESS_TOKEN || global.KARMA_API_KEY);
if (!authed) { ...; return; }
```

令牌还在 → `authed` 仍为 true → 定时器（`startAuto` 里那个 `setInterval`）继续每 15 秒把那一串
受保护读打出去，每次都被 401 挡回、`reauth` 又续不上、`markExpired` 因 `expiredNotified` 直接
return —— 于是**稳定产出匿名 401**，直到用户手动重连或关掉页面。

## 3. 这一轮改了什么

### 3.1 源头自愈（前端）
`apps/console/scripts/console-sync.js`：

* 监听 `karma-session-expired` → **`stopAuto()`**：会话死了就别再轮询；
* `karma-wallet-connected` / `karma-session-restored` 时 → 除了 `refreshAll()` 再
  `startAuto(_autoRoot || document.body)`：重新连上钱包后刷新恢复；
* `startAuto` 记下 `_autoRoot`，恢复时用同一个 root（保住页面自定义的刷新节拍）。

只动前端定时器，不碰令牌生命周期、不碰后端。

### 3.2 告警可定性（后端）
光看计数，「1 个客户端刷」和「一堆来源撞」长得一模一样。补上来源维度：

* `api/app.py`：401 / 429 的 `failed_auth` / `rate_limit_exceeded` 事件带上
  `client_ip` —— 取 `api.middleware.rate_limit.real_client_ip(request)`，它只在 socket peer 是
  可信代理（loopback / 私网）时才信 `X-Real-IP` / `X-Forwarded-For`，**调用方伪造不了**。
* `services/security_monitoring.py`：
  * 新增 `failed_auth_by_source_counter`（按 `client_ip`，老事件的 `unknown` 不算一个来源，
    否则会把单来源轮询误报成分布式攻击）；
  * 全局 `AUTH_FAILURE_SPIKE` 告警的 message 带上 `from N source(s)`，metadata 带
    `distinct_source_count` 与 `top_sources`；
  * `recommended_actions` **三分**：恰好**一个**来源 → 「先查是不是过期会话在轮询，再考虑轮换
    密钥」；**两个及以上** → 「轮换密钥 + 查 top 来源」；**0 个来源**（升级前写下的老事件没有
    `client_ip`）→ 老实说「分不清是单来源轮询还是分布式」，不硬给方向；
  * `SecurityOpsSummary.failed_auth_by_source`（`core/schemas.py` 同步加字段）。

没有调低任何阈值，没有关掉任何检测 —— 检测照旧，只是从「一个数」变成「能分辨性质的数」。

### 3.3 证据窗口（运维）
`deploy/docker-compose.testnet.yml`：

* 之前**完全没有** `logging` 段 → 用 docker daemon 默认（`json-file` 不封顶）；线上实际给的是
  `10m x 3`（≈ 2h 就滚没，出事回头看什么都没有）。
* 现在显式钉死 `json-file 50m x 5`（≈ 250MB/容器），postgres / redis / api 三个服务都挂。
* 顺带记一笔：线上 nginx 这个站点**没有 access_log**（`nginx -T` 里只有 TCP / 全局的），
  出事后拿不到「哪个 IP 打了哪个路径」。真实客户端 IP 现在通过事件里的 `client_ip` 兜住了，
  access_log 这项留作独立运维任务。

## 4. 测试

`tests/unit/test_security_ops.py` 新增 3 例：

* 单来源 → `distinct_source_count == 1`、`top_sources == [那个来源]`、
  `failed_auth_by_source[0]` 对得上，建议文案是「查过期会话」而非「轮换密钥」；
* 多来源 → `distinct_source_count == 6`，建议文案含「rotate」；
* **没有 `client_ip` 的老事件** → `distinct_source_count == 0`、`top_sources == []`
  （不把 unknown 当一个来源）。

`tests/unit/test_console_session_expiry_polling.py` 新增 2 例：钉死
`karma-session-expired` → `stopAuto()`、`karma-wallet-connected`/`karma-session-restored`
→ 恢复 `startAuto(`。

## 5. 这一轮**没有**做的

* **没碰主网**；没改任何资金路径、阈值、状态机。
* **没动前端令牌生命周期**（`markExpired` 仍然不清 token）—— 只停定时器。要不要在过期时
  直接清掉会话，是 UX 取舍（清了会强制回入口门禁），留产品定。
* **access_log** 没开（见 3.3）。
* 那 25 张卡单的「最终怎么结」产品口径、自成交那条脏单的处置，仍等拍板（见上一轮文档 §6）。