# Security Release Gates (Public Test Launch)

This checklist is blocking for broad public test rollout.

## 怎么用

这份清单分两种条目：

- **`[机器]`** —— `scripts/public-beta-security-gate.sh` 能判，跑一遍就有结论。
- **`[人工]`** —— 脚本判不了（告警有没有真的送达、演练做没做过、密钥什么时候轮换的、
  日志留存的合规口径）。脚本对这些打印 `HUMAN`，**不会替你勾上**。必须有人签字。

对发布环境跑一遍：

```bash
./scripts/public-beta-security-gate.sh \
  --env-exec 'docker exec karma-api env' \
  --base-url https://karma-network.ai
```

- `--env-exec` 从运行中的容器取**真实**环境变量（不传就用当前 shell 的）。
- `--base-url` 打开活体探测：告警端点鉴权、请求 ID、错误面是否泄内部细节。
- `--strict` 把未签字的 `HUMAN` 也计入失败，给「全自动放行」用。
- 退出码 `0` = 无阻塞项。

三条关于「机器判的项到底算不算数」的约定：

- 探针每次用**新建的临时目录**，解释器要**真能跑起来**才算数。踩过一次假绿灯：
  Windows 上的 `python3` 是 Store 占位程序，`command -v` 找得到、一执行就
  `Permission denied`，于是探针根本没联网，却把上一轮留在固定目录里的响应读回来
  当成这次的结论 —— 没验过的条目报了 PASS。现在解释器逐个真跑一次再选，目录用
  `mktemp -d`，文件读不到就是读不到。
- 探不到不等于通过：活体探测拿不到响应的条目记 `HUMAN`（要人签），不记 `WARN`。
- 凭证类缺失记 `HUMAN`，不记 `FAIL`。判据只有一条：**这件事我们自己能不能修好**。
  `APP_SECRET_KEY` 没设、限流没走 Redis、没人调度备份 —— 自己能修，记 `FAIL`。
  离站存储的端点、告警该发给谁 —— 要外部账号或人拍板，记 `HUMAN`，并写清楚缺什么。

配套：`scripts/acceptance/public_testnet_preflight.sh`（`PUBLIC_TESTNET_STRICT=true` 时
还强制 Redis fail-closed、PostgreSQL `DATABASE_URL`、on-call 变量、Bilateral RPC 地址）。

---

## 最近一次发布环境实测

| 项 | 值 |
|---|---|
| 时间 | 2026-10-01 |
| 版本 | `main`（部署后再实测一遍，结论与 `340641d` 那轮一致） |
| 环境 | `https://karma-network.ai`（Sepolia `TESTNET_CHAIN_ID=11155111`，`CHAIN_ALLOWANCE_ESCROW_ENABLED=true`） |
| 结果 | **PASS 27 · FAIL 0 · WARN 0 · HUMAN 17** |
| 阻塞项 | 无。剩下 17 条是脚本判不了的，要人签字 |
| 已消项 | `A4b` 警告 + `A4c` 待签：`AUTH_API_KEYS` 拆成 3 把，每个 service agent 一把（见 Gate A） |
| 已消项 | `E5` 值班联系人已配（值只在服务器 `.env`，仓库是公开的所以不入库） |
| 已消项 | `F1`–`F4` 备份与恢复：每小时快照 + 每天 03:17 恢复演练（实测 56 张表行数全一致） |
| 待签 | `F5`–`F6` 离站副本未配；`G4`–`G5` 告警出口未配（缺外部凭证） |

---

## 运维 service agent 钥匙一览（2026-10-01）

生产只认这三把静态钥匙，每把只覆盖它自己那个角色，**互不隐含**。任何一把泄漏只影响
它自己；换钥匙只改 `/opt/karma/.env` 再重建 `karma-api`，不动代码。

| 钥匙（`X-Karma-Api-Key`） | 角色 | 对应白名单 | 能做什么 |
|---|---|---|---|
| `karma_ops-admin_…` | 平台管理员 | `ADMIN_ACTOR_IDS` | 刹车（safety-mode）、安全阈值策略、平台资金面、运维告警 |
| `karma_ops-arbitrator_…` | 争议仲裁员 | `ARBITRATOR_ACTOR_IDS` | 仲裁派庭、执行裁决、运维报表 |
| `karma_ops-governance_…` | 治理身份发放方 | `GOVERNANCE_VERIFIER_IDS` | 开 verifier / arbitrator 治理岗 |

交接与轮换：明文写在服务器 `/opt/karma/.service-agent-keys-<时间戳>.txt`（`chmod 600`），
`.env` 本体也是 `600`。**这三把都不要进 git、不要贴进聊天。**

## Gate A — Identity and Access

- `[机器]` `APP_ENV=production` — ✅ 2026-10-01
- `[机器]` `APP_SECRET_KEY` is rotated and non-default — ✅ 2026-10-01（非默认，长度 64）
- `[人工]` `APP_SECRET_KEY` is rotated and non-default —— **轮换日期是谁、什么时候做的**，待签
- `[机器]` `AUTH_ENFORCE_PROTECTED_ROUTES=true` — ✅ 2026-10-01
- `[机器]` `AUTH_API_KEYS` configured — ✅ 2026-10-01（3 条）
- `[机器]` `AUTH_API_KEYS` gives every service agent its own key — ✅ 2026-10-01
  （`ops-admin` / `ops-arbitrator` / `ops-governance` 各一把独立 secret。脚本 `A4c` 判三件事：
  **没有两把共用同一个 secret**（共用 = 审计追不到人）、**每把 secret ≥ 24 字符**、
  **`ADMIN_ACTOR_IDS` / `ARBITRATOR_ACTOR_IDS` / `GOVERNANCE_VERIFIER_IDS` 里点名的每个
  非身份号 actor 都有自己的钥匙**。最后一条是硬的：悬空白名单条目直接 FAIL ——
  一个没人管的 id 留在管理员名单里就是后门）
- `[人工]` 运维白名单里的身份号（`kid_*` / telegram id）确有其人，且与持有人对得上 —— 待签
- `[机器]` No test credentials are present in runtime env — ✅ 2026-10-01
  （`AUTH_ALLOW_DEV_KEY_FALLBACK` / `OPENCLAW_LOCAL_PHASE1_AUTO_RELAX` /
  `OPENCLAW_RELAX_DELIVERY_SIGNATURES` 均为 false，且无 `TEST_*/DEMO_*/SEED_*` 形状的凭证变量）

## Gate B — API Abuse Resistance

- `[机器]` Redis URL configured for the limiter — ✅ 2026-10-01（`redis://`）
- `[人工]` Redis-backed rate limiter is reachable in production —— 脚本在应用进程外
  探不到容器网络，需要有人在服务器上确认 `karma-redis` 连通。待签
- `[机器]` `RATE_LIMIT_REDIS_FAIL_CLOSED=true` — ✅ 2026-10-01
- `[机器]` Sensitive write paths have active limits (`write_sensitive` / `state_transition`)
  — ✅ 2026-10-01（额度已定义且中间件已挂进 `api/app.py`）
- `[人工]` Alerting exists for sustained 429 spikes and auth failures —— 待签
- `[机器]` `/v1/security/ops/alerts` exists and is auth-protected — ✅ 2026-10-01（HTTP 401）
- `[人工]` `/v1/security/ops/alerts` is monitored with tuned thresholds —— 待签
- `[人工]` Alert cooldown / suppression policy is configured and reviewed with on-call —— 待签
- `[人工]` Endpoint / route-group threshold overrides are configured for critical paths —— 待签
- `[人工]` Active security threshold policy version is pinned and documented —— 待签

## Gate C — Security Auditability

- `[机器]` Security audit logs are collected for sensitive write methods — ✅ 2026-10-01
  （`security_audit_middleware` + `SENSITIVE_WRITE_PREFIXES`）
- `[机器]` Logs include actor ID, request path, method, status, request ID — ✅ 2026-10-01
  （代码层面；活体响应实测带 `X-Request-Id`）
- `[人工]` Log retention and query access are configured for incident response —— 待签

## Gate D — Error Surface Control

- `[机器]` Internal exceptions are not returned to public clients — ✅ 2026-10-01
- `[机器]` Private runtime errors are masked behind generic boundary messages — ✅ 2026-10-01
  （对不存在路由 / 未鉴权的写路径做活体探测，响应里没有 `Traceback`、`File "`、
  `site-packages`、`/opt/karma`、`sqlalchemy`、`asyncpg` 任何一项）
- `[机器]` Debug mode is disabled in production — ✅ 2026-10-01
  （`settings.debug` 默认 False，且无 `DEBUG` / `APP_DEBUG` 覆盖；外部 `/docs` 由 nginx 挡成 404）

## Gate E — Verification and Rollback

- `[人工]` Security regression tests pass in CI —— 见该 commit 的 GitHub Actions run，待签
- `[人工]` Public acceptance script passes —— 见该 commit 的 GitHub Actions run，待签
- `[机器]` Rollback/on-call runbook exists — ✅ 2026-10-01（`docs/SECURITY_INCIDENT_PLAYBOOK.md`）
- `[人工]` Rollback plan and on-call runbook are confirmed —— 待签
- `[机器]` `SECURITY_ONCALL_PRIMARY` / `SECURITY_ONCALL_BACKUP` are configured — ✅ 2026-10-01
  （应用代码不读它们，纯「真出事先找谁」的声明。**值只写在服务器 `/opt/karma/.env`，
  不进仓库** —— 这个仓库是公开的，联系方式属于个人信息。
  注意：**目前 `BACKUP` 和 `PRIMARY` 是同一个人，还没有第二联系人**；
  指定第二个人之后把 `SECURITY_ONCALL_BACKUP` 换掉）
- `[机器]` Baseline drift controls exist — ✅ 2026-10-01（`baseline_window_minutes` / `baseline_drift_multiplier`）
- `[人工]` Baseline drift strategy is reviewed —— 待签
- `[人工]` Policy-center rollback drill (`/v1/security/policies/rollback`) has been exercised —— 待签

## Gate F — Backup and Recovery

生产只有一台 VPS：PostgreSQL、Redis 和工作树都在 `/dev/vda3` 上。**只落在这块盘上的快照
不算备份** —— 它和数据库一起死。所以这一组既问「有没有」，也问「能不能恢复」。

- `[机器]` 备份脚本存在且能解析（`scripts/ops/backup.sh`）— ✅ 2026-10-01
- `[机器]` 备份有调度（root crontab / systemd timer 真的引用了备份脚本）— ✅ 2026-10-01
- `[机器]` 最近一份快照在 26h 内，且 `karma-db.sql.gz` 非空 — ✅ 2026-10-01
- `[机器]` 最近一份快照的 dump **真的恢复得回去** — ✅ 2026-10-01
  （`backup.sh --verify`：把 dump 恢复进一次性 `postgres:16-alpine` 容器（`--network none`），
  再逐表比对行数。2026-10-01 实测 **56 张表行数全部一致**，一轮 6.7 秒）
- `[人工]` 离站副本在异地/异账号，并且从它恢复过一次 — 待签

两条要记住的：

- `--verify` 是**恢复演练**，不是「文件在不在」。它比的是行数，不是文件大小。
- `F5` 现在打印 `HUMAN`：`KARMA_BACKUP_OFFSITE` 还没配 —— `.env` 里只有
  `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`，**没有端点**，所以离站推不出去。配上端点
  （或 rsync 目标）之后，每天 03:17 那轮会自动推离站，F5 才会变成机器可判的 PASS。

---

## Gate G — Alerting Delivery

Gate B 问的是「阈值和政策定没定」，Gate G 问的是**告警能不能到达人**。报表接口的鉴权
在 B 里已经验过了；这里验的是「有没有人去拉、拉到之后往哪送、送没送成」。

- `[机器]` 告警轮询脚本存在且能解析（`scripts/ops/security_alert_poller.py`）— ✅ 2026-10-01
- `[机器]` 轮询有调度（root crontab / systemd timer 引用了它）— ✅ 2026-10-01
- `[机器]` 最近一轮轮询成功（15 分钟内）— ✅ 2026-10-01
- `[机器]` 配了真实的告警出口（webhook / Telegram / SMTP）— ⏳ **现在还没配，记 HUMAN**
- `[人工]` 发了一条自检告警并确认真收到（`--test`）— 待签

为什么单独开一组：之前是 —— `/v1/security/ops/alerts` 写得很好，但**服务器上没有
prometheus、没有 grafana、没有 node_exporter，容器 env 里也没有任何 SMTP / webhook /
Sentry 配置**，没有任何东西去拉它。告警生成了，然后烂在内存里。这一组就是补这个洞。

「没配出口」不等于「已经做完了」：轮询脚本会把告警写进 `/var/log/karma-alerts.log`，
而那个日志没人会去看。配了 `KARMA_ALERT_WEBHOOK_URL`、`KARMA_ALERT_TELEGRAM_*` 或
`KARMA_ALERT_SMTP_*`（见 `scripts/ops/env.ops.example`）之后，G4 才会变成机器可判的 PASS。

轮询脚本顺带做几条**不需要外部凭证就有用**的本机体检（和应用的告警共用同一套差分逻辑）：
最新快照超过 26h、恢复演练失败、离站拷贝失败、磁盘超 90%。

---

---

## 签核记录

发布前把这一块填完并留档。`[机器]` 项由脚本给出结论，`[人工]` 项由签字人负责。

| 字段 | 值 |
|---|---|
| 发布版本（git sha） | |
| 环境 | |
| Gate 脚本输出 | `PASS __ / FAIL __ / WARN __ / HUMAN __`（附原始输出） |
| 阻塞项 | |
| 签核人 | |
| 签核日期 | |
