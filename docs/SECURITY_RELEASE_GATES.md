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

两条关于「机器判的项到底算不算数」的约定：

- 探针每次用**新建的临时目录**，解释器要**真能跑起来**才算数。踩过一次假绿灯：
  Windows 上的 `python3` 是 Store 占位程序，`command -v` 找得到、一执行就
  `Permission denied`，于是探针根本没联网，却把上一轮留在固定目录里的响应读回来
  当成这次的结论 —— 没验过的条目报了 PASS。现在解释器逐个真跑一次再选，目录用
  `mktemp -d`，文件读不到就是读不到。
- 探不到不等于通过：活体探测拿不到响应的条目记 `HUMAN`（要人签），不记 `WARN`。

配套：`scripts/acceptance/public_testnet_preflight.sh`（`PUBLIC_TESTNET_STRICT=true` 时
还强制 Redis fail-closed、PostgreSQL `DATABASE_URL`、on-call 变量、Bilateral RPC 地址）。

---

## 最近一次发布环境实测

| 项 | 值 |
|---|---|
| 时间 | 2026-10-01 |
| 版本 | `main @ 340641d`（部署后再实测一遍，结论与 ac041c5 一致） |
| 环境 | `https://karma-network.ai`（Sepolia `TESTNET_CHAIN_ID=11155111`，`CHAIN_ALLOWANCE_ESCROW_ENABLED=true`） |
| 结果 | **PASS 17 · FAIL 1 · WARN 1 · HUMAN 13** |
| 阻塞项 | `E5` `SECURITY_ONCALL_PRIMARY` / `SECURITY_ONCALL_BACKUP` 未配置 |
| 警告 | `A4b` 只配了 1 个 `AUTH_API_KEYS` 条目 |

---

## Gate A — Identity and Access

- `[机器]` `APP_ENV=production` — ✅ 2026-10-01
- `[机器]` `APP_SECRET_KEY` is rotated and non-default — ✅ 2026-10-01（非默认，长度 64）
- `[人工]` `APP_SECRET_KEY` is rotated and non-default —— **轮换日期是谁、什么时候做的**，待签
- `[机器]` `AUTH_ENFORCE_PROTECTED_ROUTES=true` — ✅ 2026-10-01
- `[机器]` `AUTH_API_KEYS` configured — ✅ 2026-10-01（1 条）
- `[人工]` `AUTH_API_KEYS` configured for all service agents —— 目前**只有 1 条**，
  确认「每个 service agent 一把独立 key」还是共用一个；共用就是审计追溯不出人。待签
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
- `[机器]` `SECURITY_ONCALL_PRIMARY` / `SECURITY_ONCALL_BACKUP` are configured
  — ❌ **2026-10-01 未配置**（`/opt/karma/.env` 里没有这两项；应用代码不读它们，
  纯声明用。需要真人联系方式，脚本不能编）
- `[机器]` Baseline drift controls exist — ✅ 2026-10-01（`baseline_window_minutes` / `baseline_drift_multiplier`）
- `[人工]` Baseline drift strategy is reviewed —— 待签
- `[人工]` Policy-center rollback drill (`/v1/security/policies/rollback`) has been exercised —— 待签

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
