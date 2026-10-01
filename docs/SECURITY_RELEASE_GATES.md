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
| 时间 | 2026-10-01（`aa35401` 部署后实测，连跑 3 遍结果一致） |
| 版本 | `main` |
| 环境 | `https://karma-network.ai`（Sepolia `TESTNET_CHAIN_ID=11155111`，`CHAIN_ALLOWANCE_ESCROW_ENABLED=true`） |
| 结果 | **PASS 32 · FAIL 0 · WARN 0 · HUMAN 23**（退出码 0） |
| 阻塞项 | 无。`E5b` 已消：第二值班人配好，`BACKUP` 与 `PRIMARY` 是两个不同的人（值只在服务器 `.env`） |
| 已消项 | `A4b` 警告 + `A4c` 待签：`AUTH_API_KEYS` 拆成 3 把，每个 service agent 一把（见 Gate A） |
| 已消项 | `E5` 值班联系人已配（值只在服务器 `.env`，仓库是公开的所以不入库） |
| 已消项 | `F1`–`F4` 备份与恢复：每小时快照 + 每天 03:17 恢复演练（实测 56 张表行数全一致） |
| 已消项 | `G1`–`G3` 告警轮询：`*/5` cron + 差分 + 本机体检 |
| 已消项 | `H1` / `H4` / `H5` / `H8`：链上三件套、Redis 可达、postgres、部署清单与链上三方对齐 |
| 待签 | `F5`–`F6` 离站副本未配；`G4`–`G5` 告警出口未配（缺外部凭证） |
| 待签 | `H2` / `H3` / `H9`–`H12`：测试钱包、按笔锚定、私仓版本锁、OpenClaw/OpenManus/上链 smoke |

**这轮修掉的两个「自己人打自己人」**（都不是业务 bug，但都会让人开始不信闸门）：

- **假红 1**：`set -o pipefail` + `printf '%s' "$blob" | grep -q PAT` —— grep 命中即退出，
  上游 printf 拿到 SIGPIPE(141)，pipefail 把整条管道判成失败，于是「找到了」被判成「没找到」。
  生产首跑时 G2 报「没人调度轮询」，同一秒 G3 报「273 秒前刚跑成功」。主机上实测 10 次错 3 次。
  5 处（`A4c` / `D1` / `F2` / `G2` / `H4`）全改成 herestring 或变量比较。
- **假黄 3**：`F4`/`F5` 判的是「最新那份快照演练过没有」，而演练与离站只在每天 03:17
  跑一次 —— 于是每小时 cron 落一份新快照，闸门就黄一次（19:17 实测命中）。改成判
  「最近一次演练的结果」后不再按时辰摆动。**修的时候又踩了同一个 SIGPIPE 坑**
  （`bk_status_lines | awk '{print; exit}'`）：表现是最新快照演练失败时，Gate F 整段
  静默消失。既然一天两次，已把它变成 CI 闸门（`ops-scripts` 作业扫 `| grep -q`
  与 `| awk ... {exit}` 两种形状）。
- **假红 2**：`ops-scripts`（分支保护里的必需检查）从加进来那天起就不可能变绿 ——
  `tests/conftest.py` 要 `pytest_asyncio`，而这个作业刻意只装 `pytest`，pytest 连收集
  都没开始就 exit 4。已加 `--noconftest`（这几个文件测的是独立运维脚本，不用 conftest 的 fixture）。

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
- `[机器]` x402 出网口只放行公网目标（`A6`）— ✅ 2026-10-01
  （`X402_ALLOW_PRIVATE_HOSTS=false` 已在发布环境生效，闸门 A6 判它；`url_safety` 还会把
  域名解析一遍再判地址，拦住「域名指向 127.0.0.1 / 169.254.169.254」这类绕过。
  见 [`X402_INTEGRATION-zh.md`](X402_INTEGRATION-zh.md)）

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
  不进仓库** —— 这个仓库是公开的，联系方式属于个人信息）
- `[机器]` `SECURITY_ONCALL_BACKUP` 与 `PRIMARY` 是**两个不同的人**（`E5b`）— ✅ 2026-10-01
  （判据就一条：两个值一样 = 没有第二个人。真出事时「值班的人联系不上」和「没人值班」
  是同一件事，所以这不能靠人自觉。值仍然只写在服务器 `/opt/karma/.env`，不进仓库。
  它红了一整天，一直红到真的有人填进第二个人为止 —— 没有降级成一条没人看的 `HUMAN`）
- `[机器]` Baseline drift controls exist — ✅ 2026-10-01（`baseline_window_minutes` / `baseline_drift_multiplier`）
- `[人工]` Baseline drift strategy is reviewed —— 待签
- `[人工]` Policy-center rollback drill (`/v1/security/policies/rollback`) has been exercised —— 待签

## Gate F — Backup and Recovery

生产只有一台 VPS：PostgreSQL、Redis 和工作树都在 `/dev/vda3` 上。**只落在这块盘上的快照
不算备份** —— 它和数据库一起死。所以这一组既问「有没有」，也问「能不能恢复」。

- `[机器]` 备份脚本存在且能解析（`scripts/ops/backup.sh`）— ✅ 2026-10-01
- `[机器]` 备份有调度（root crontab / systemd timer 真的引用了备份脚本）— ✅ 2026-10-01
- `[机器]` 最近一份快照在 26h 内，且 `karma-db.sql.gz` 非空 — ✅ 2026-10-01
- `[机器]` **最近一次演练**真的把 dump 恢复回去了 — ✅ 2026-10-01
  （`backup.sh --verify`：把 dump 恢复进一次性 `postgres:16-alpine` 容器（`--network none`），
  再逐表比对行数。2026-10-01 实测 **56 张表行数全部一致**，一轮 6.7 秒）

  判据是「**最近一次**演练的结果」，不是「**最新那份**快照演练过没有」—— 后者几乎永远
  是「没有」：快照每小时落一份，而演练每天 03:17 才跑一次。照后者判，闸门每小时从绿变黄、
  再在 03:17 变回绿（2026-10-01 实测：19:17 的 cron 快照把 F4 顶成 HUMAN）。一个按时辰
  变色的闸门很快会被当成噪声忽略掉，和假绿灯一样糟。现在的判据：从新到旧找第一份真的
  跑过演练的（`skipped` / `pending` 不算跑过），判它成没成、离现在多久；演练一停，
  26h 后转红。离站（F5）同理。
- `[人工]` 离站副本在异地/异账号，并且从它恢复过一次 — 待签

两条要记住的：

- `--verify` 是**恢复演练**，不是「文件在不在」。它比的是行数，不是文件大小。
- `F5` 现在打印 `HUMAN`：`KARMA_BACKUP_OFFSITE` 还没配 —— `.env` 里只有
  `MINIO_ACCESS_KEY` / `MINIO_SECRET_KEY`，**没有端点**，所以离站推不出去。配上端点
  （或 rsync 目标）之后，每天 03:17 那轮会自动推离站，F5 才会变成机器可判的 PASS。

**这一条要人给的东西只有一样：一个离站的落点。** 现在快照只落在
`/opt/karma/backups`，和 PostgreSQL 同在一块盘（`/dev/vda3`）上 —— 盘坏了或机器丢了，
数据库和备份一起没。落点二选一：

1. **另一台机器** —— 给 `user@host:/srv/karma-backups`，外加一把能登录的 SSH key
   （走 `rsync` / `scp`）；
2. **任意 S3 兼容对象存储** —— 给 endpoint + 桶名，再加一对 access key
   （阿里云 OSS / MinIO / AWS 都可以）。

给到之后：`KARMA_BACKUP_OFFSITE=s3|rsync|scp` 写进 `/opt/karma/.env.ops`，每天 03:17
那轮自动推，第二天闸门 F5 就是机器判的 PASS 了。

---

## Gate G — Alerting Delivery

Gate B 问的是「阈值和政策定没定」，Gate G 问的是**告警能不能到达人**。报表接口的鉴权
在 B 里已经验过了；这里验的是「有没有人去拉、拉到之后往哪送、送没送成」。

- `[机器]` 告警轮询脚本存在且能解析（`scripts/ops/security_alert_poller.py`）— ✅ 2026-10-01
- `[机器]` 轮询有调度（root crontab / systemd timer 引用了它）— ✅ 2026-10-01
- `[机器]` 最近一轮轮询成功（15 分钟内）— ✅ 2026-10-01
- `[机器]` 配了真实的告警出口，且**最近一次发送真的送出去了**（webhook / Telegram / SMTP）
  — ✅ 2026-10-01（出口 `telegram`，运维专用 bot，两轮 `--test` 实测送达）。判的是发送结果，
  不是「填了两行配置」：配了但从没发过 = HUMAN；最近一次发送失败 = FAIL；最近一次成功 =
  PASS（来源记在 `last_egress_src`，自检落 `selftest`）。凭证只在服务器
  `/opt/karma/.env.ops`（600）—— 仓库是公开的，所以不入库
- `[人工]` 发了一条自检告警并确认真收到（`--test`）— ✅ 2026-10-01 已签（运维确认收到）

为什么单独开一组：之前是 —— `/v1/security/ops/alerts` 写得很好，但**服务器上没有
prometheus、没有 grafana、没有 node_exporter，容器 env 里也没有任何 SMTP / webhook /
Sentry 配置**，没有任何东西去拉它。告警生成了，然后烂在内存里。这一组就是补这个洞。

「没配出口」不等于「已经做完了」：轮询脚本会把告警写进 `/var/log/karma-alerts.log`，
而那个日志没人会去看。配了 `KARMA_ALERT_WEBHOOK_URL`、`KARMA_ALERT_TELEGRAM_*` 或
`KARMA_ALERT_SMTP_*`（见 `scripts/ops/env.ops.example`）之后，再跑一次自检：

```bash
python3 /opt/karma/repo/scripts/ops/security_alert_poller.py --test
```

自检的结果会写进状态文件（`last_egress_ok_ts` / `last_egress_src`），G4 才有东西可判 ——
一台健康的服务器上真实告警可能几个月都不出现，光等真实告警是等不到 PASS 的。自检没发出去
时退出码是 5，不假报成功。

2026-10-01 在接 Telegram 之前回头审了一遍「出口发不出去的时候会发生什么」，修掉四件事
（都由 `tests/unit/test_ops_alert_poller.py` 锁住）：

- **出口抛异常会吞掉告警原文**：原来的顺序是「先发、后写本地日志」，任何一个出口抛异常，
  最后那行 print 就永远执行不到 —— 出口坏掉的那一刻，恰好也是日志里什么都没有的那一刻。
  现在本地留痕排在网络调用前面。
- **一个出口挂掉会连累其他出口**：原来是顺序调用且不接异常，webhook 一挂，Telegram 永远
  收不到。现在每个出口独立 try/except —— 多出口的意义就是冗余。
- **失败信息里可能夹带 token 的隐患**：这条要说准确 —— 在服务器上逐条实测过，`urllib`
  的 `HTTPError` / `URLError` / `InvalidURL` 目前**不会**把请求 URL 带进 `str(exc)`，所以
  眼下并没有在漏。但 `HTTPError.url` 属性里躺着完整的
  `https://api.telegram.org/bot<token>/sendMessage`，而「为了排查方便把异常打全一点」
  （`%r`、或者顺手打印 `exc.url`）是最自然的下一次改动，那一刻 token 就会进 cron 日志，
  而那份日志跟着备份和采集一起走。所以现在往 stderr 和状态文件写东西之前统一过一遍
  `redact()`：按形状认 token，也按值抹掉配置里任何名字像密钥的字段。这是防下一步，不是
  修一个已发生的泄露。
- **`--test` 假绿**：原来无条件 `return 0`，没配出口也报成功。现在发不出去就是退出码 5。

轮询脚本顺带做几条**不需要外部凭证就有用**的本机体检（和应用的告警共用同一套差分逻辑）：
最新快照超过 26h、恢复演练失败、离站拷贝失败、磁盘超 90%。

---

## Gate H — Testnet Go-Live Prerequisites

`docs/public-testing/PUBLIC_TESTNET_GO_LIVE-zh.md` §4 有 12 条「Go 之前全部 ☐→☑」的前置条件。
以前它们只是文档里一排空方框：没人知道到底缺哪几条、谁去补、补成什么样算完 —— 一处漏了，
上线当天才发现。这一组把那 12 条搬进闸门，能机器判的机器判，判不了的明确记 `HUMAN`
并写清楚**去哪判**，不假装判过。

- `[机器]` H1 链上三件套已配（`TESTNET_RPC_URL` / `ERC20_TOKEN_ADDRESS` / `KARMA_BILATERAL_ADDRESS`）
- `[人工]` H2 买方/卖方测试钱包真的有钱（钱的事，shell 判不了）
- `[人工]` H3 `CHAIN_ANCHOR_HASH` —— 它**本该按笔交易写入**，不是全局 env。
  env 里有只算参考，所以机器判到 `HUMAN` 为止，让人确认「确实是按笔写」
- `[机器]` H4 Redis 从主机可达（限流要 fail-closed，连不上就必须拒）
- `[机器]` H5 `DATABASE_URL` 是 postgres 而不是 SQLite
- 见 `A2` / `A4`：H6 `APP_SECRET_KEY` 强随机、`AUTH_API_KEYS` 已配（闸门里打印 `SKIP` 并指向那边）
- 见 `E5` / `E5b`：H7 值班主/备联系人（同上，`SKIP` 指向那边）
- `[机器]` H8 部署清单**三方对齐** —— `deployment-manifest.json` 的结构、发布环境里的绑定变量、
  链上事实（`chain_id`、合约地址上有没有代码、结算钱包有没有钱）三者一致
  （`scripts/acceptance/verify-manifest.sh`，实测 8 项核对全过。探不到链记 `HUMAN` 并退 3，
  不一致记 `FAIL` 并把每条不一致打出来）。
  这一条以前只问「文件在不在」—— 文件在不在不是重点：清单是人写的声明，**写错了比没有更糟**
  （没有的话人会去链上查，写错了人会信它）
- `[人工]` H9 Karma2 `CORE_VERSION.lock` 与公开 commit 对齐（私有仓库的核对）
- `[人工]` H10 OpenClaw MCP 注册 + 一条签名通路的 A/B 实测
- `[人工]` H11 OpenManus / `phase1_claw_manus_smoke.py` 对着活的测试网跑通
- `[人工]` H12 `RUN_TESTNET_ONCHAIN` 混合上链 smoke

H6/H7 故意只打印 `SKIP` 而**不重复报数**：同一件事报两遍，改一处忘另一处时会出现
「一条绿一条红」这种没法解释的输出。

H8 的清单里只有**公开的链上地址**（链上可查），私钥永远不进仓库 —— 服务器 `.env` 里的
`SETTLEMENT_OPERATOR_PRIVATE_KEY` 之类，任何时候都不许出现在这个 public 仓库里。

结算运营钱包（`SETTLEMENT_OPERATOR_ADDRESS`）在清单里标的是 `eoa` 而不是 `contract`：
它是钱包，链上本来就没有代码，写成 `contract` 会让链上核对永远红。对 EOA 查的是**余额** ——
余额为 0 就等于结算永远发不出去，这正是一条上线前置条件。

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
