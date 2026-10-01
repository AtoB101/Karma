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
| 时间 | 2026-10-02（本轮部署后实测，`--no-heavy`；重活由 CI 覆盖） |
| 版本 | `main` |
| 环境 | `https://karma-network.ai`（Sepolia `TESTNET_CHAIN_ID=11155111`，`CHAIN_ALLOWANCE_ESCROW_ENABLED=true`） |
| 结果 | **PASS 48 · FAIL 0 · WARN 0 · HUMAN 11**（退出码 0；累计比 2026-10-01 那轮多 14 条机器判定、少 11 条待签） |
| 阻塞项 | 无。`E5b` 已消：第二值班人配好，`BACKUP` 与 `PRIMARY` 是两个不同的人（值只在服务器 `.env`） |
| 已消项 | `G4`：告警出口接上 Telegram（运维专用 bot），最近一次真发送成功；`G5` 改为机器判（`last_selftest_ok_ts` 粘性证据）；`B3` 改为判**真告警真的送达过**（2026-10-02 实做投递演练）。**改完当场又踩到一个「自己人打自己人」**：常规轮询收尾是重拼状态字典，漏搬了两个粘性键，自检刚写下的证据被下一轮 `*/5` 擦掉 —— 见下面第三条 |
| 已消项 | `B5`/`B6`/`B7`：**本轮发现 B6 其实是空的** —— `security_threshold_policies` 表 0 行，全站跑代码默认值。已激活 v2，在 `auth`/`runtime`/`verification`/`settlement` 四个关键路由组上单独收紧，冷却 10 分钟。闸门改为直读库里 active 那一行，并把文档钉版与库中版本**逐字段比对**（对不上就 FAIL） |
| 已消项 | `E7`：策略中心回滚演练实做（建 v3 → 激活 → 回滚 v2，三次变更单各走一遍两人审批），结果留在 `/opt/karma/state/security-policy-drill.json`，闸门读它并要求 180 天内做过 |
| 已消项 | `A2b`：轮换台账改成**机器可读 + 机器判定**（字段齐全 + 口径自洽 + 有人签字 + 未过期；过期直接 FAIL） |
| 已消项 | `B1b`：Redis 可达不再记 `HUMAN` —— 直接在发布机 `docker exec karma-redis redis-cli ping` 取 `PONG`（同一个事实 `H4` 早就在判，一处 PASS 一处 HUMAN 是自相矛盾） |
| 已消项 | `C3a`/`C3b`/`C3c`：容器日志上限（compose 里的 `max-size=20m`×`max-file=5`）、journald 留存**显式写死**（`SystemMaxUse=2G`/`SystemKeepFree=2G`/`MaxRetentionSec=90d`）、留存窗口与查询命令写进 playbook §7 |
| 已消项 | `A6`（上一轮新增）：x402 出网口只放行公网目标。生产 `X402_ALLOW_PRIVATE_HOSTS=false` + `X402_PAYMENT_BACKEND=sepolia`，真链端到端实测见 [`public-testing/PHASE2_X402_ACCEPTANCE.md`](public-testing/PHASE2_X402_ACCEPTANCE.md) |
| 已消项 | `A4b` 警告 + `A4c` 待签：`AUTH_API_KEYS` 拆成 3 把，每个 service agent 一把（见 Gate A） |
| 已消项 | `E5` 值班联系人已配（值只在服务器 `.env`，仓库是公开的所以不入库） |
| 已消项 | `F1`–`F4` 备份与恢复：每小时快照 + 每天 03:17 恢复演练（实测 56 张表行数全一致） |
| 已消项 | `G1`–`G3` 告警轮询：`*/5` cron + 差分 + 本机体检 |
| 已消项 | `H1` / `H4` / `H5` / `H8`：链上三件套、Redis 可达、postgres、部署清单与链上三方对齐 |
| 已消项 | `E1`/`E2`：回归与公开验收以前一律待签（「去看那个 commit 的 Actions run」）。仓库是公开的，Actions 运行列表**不需要 token** 就能读，所以发布机上直判：HEAD 那个 sha 的所有 run 必须 completed + 成功；还在跑记 `HUMAN`（CI 没跑完既不算过也不算挂），concluded 但不成功才记 `FAIL`；探不到（没 git/python、GitHub 不可达、被限流）一律 `HUMAN` |
| 已消项 | `B8`（新增）：安全事件**落盘**了 —— 以前只在进程内存里，每次发布都把 15 分钟检测窗口清零。生产实测：重建容器**前后**报表都是 `failed_auth=8`（修之前重建后必定是 0）。机器判据是 `B8`：造一个会被记录的事件，再从发布环境里那份 journal 的最后一行读回来 |
| 已消项 | `B3`/`G5` 的投递证据能在常规轮询里**存活**（2026-10-02 生产实测：自检写完 `last_selftest_ok_ts` 后紧接跑一次常规轮询，该值仍在（旧版会变 `never`）；随后打尖峰 → 下一轮 `*/5` 投出 3 条 `rate_limit_spike`，`last_alert_ok_ts` 与之同时在场） |
| 待签 | `F5`–`F6` 离站副本未配 —— 只缺一个「离站落点」（另一台机器或对象存储，见 Gate F） |
| 待签 | `A4d`（白名单里的身份号确有其人）、`E4b`（回滚/值班手册人确认）、`E6b`（基线漂移策略评审） |
| 待签 | `H2` / `H3` / `H9`–`H12`：测试钱包、按笔锚定、私仓版本锁、OpenClaw/OpenManus/上链 smoke |

**这轮修掉的「自己人打自己人」**（都不是业务 bug，但都会让人开始不信闸门）：

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
- **部署顺序（本轮踩的）**：`karma deploy` 的顺序是「先 `docker exec karma-api alembic
  upgrade head`、再重建容器」，而 `docker exec` 用的是**容器创建时冻结的 env**。所以
  「改 `.env` + 改代码」同一个 push 进来时，迁移会拿**旧 env** 跑新代码：本轮把
  `X402_PAYMENT_BACKEND` 从 `env` 改成 `sepolia`、而新校验要求这种后端必须有
  `X402_PRIVATE_KEY`，迁移当场 `ValidationError` 退出。校验本身是对的（它拦住了「配置没
  到位就上线」），脚本那句「nothing else was changed; the running container is untouched」
  也是对的 —— 线上没受影响，只是这次发布停了。修法：先按新 `.env`
  `docker compose up -d --force-recreate app` 一次，再走部署。
- **假红 2**：`ops-scripts`（分支保护里的必需检查）从加进来那天起就不可能变绿 ——
  `tests/conftest.py` 要 `pytest_asyncio`，而这个作业刻意只装 `pytest`，pytest 连收集
  都没开始就 exit 4。已加 `--noconftest`（这几个文件测的是独立运维脚本，不用 conftest 的 fixture）。
- **假红 3（2026-10-02）**：`G5` 刚改成「自检真的送达过」的机器判，判的是状态文件里的
  `last_selftest_ok_ts`。但 `security_alert_poller.py` 的常规轮询收尾是**重拼**一份字典再落盘 ——
  新加的两个粘性键没被搬过去，于是**自检刚写完证据，下一个 `*/5` 轮询就把它擦掉**，
  `G5` 反而在系统更健康的时候变红。生产实测看到 `selftest_ok` 从 278s 变成 `never` 才定位到。
  修法：把 `last_selftest_ok_ts` / `last_alert_ok_ts` 补进 `state_out`，并加一条端到端回归用例
  （去掉修复即 `KeyError` 变红，用例确实能抓住这个 bug）。

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
- `[机器]` `APP_SECRET_KEY` rotation date is recorded（`A2b`）— ✅ 2026-10-01 已签，签字人 YMZAI
  （脚本解析 `KEY_ROTATION.md` 里的机器可读台账：字段齐全 + 口径自洽 + 有人签字 + 未过期；
  过期会直接 `FAIL`。**它判的是「记录是否完整自洽」，不是「签字人是不是真人」** —— 后者是 A4d）
  口径与事实要分开写：**2026-10-01 = 首次建立轮换制度的基准日**，周期 **90 天**，**首次真轮换计划 2026-12-30**；
  这条 key **从建网起从未轮换过**（回溯 12 份 `.env` 备份，指纹一致，最早 `2026-09-02 17:09`）——
  所以在 2026-12-30 真正做完之前，台账里它一直是「未轮换」。
  台账 / 代价 / 操作手册见 [KEY_ROTATION.md](./KEY_ROTATION.md)
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
- `[机器]` Redis-backed rate limiter is reachable in production（`B1b`）— ✅ 2026-10-01
  （在发布机上 `docker exec karma-redis redis-cli ping` 取到 `PONG`；够不着才退回 `HUMAN`。
  这一条以前一直记 `HUMAN`，但**同一个事实 `H4` 早就在判** —— 一处 PASS 一处 HUMAN 是
  自相矛盾，同一个事实只该有一个判据）
- `[机器]` `RATE_LIMIT_REDIS_FAIL_CLOSED=true` — ✅ 2026-10-01
- `[机器]` Sensitive write paths have active limits (`write_sensitive` / `state_transition`)
  — ✅ 2026-10-01（额度已定义且中间件已挂进 `api/app.py`）
- `[机器]` Alerting is **delivered** for sustained 429 spikes and auth failures（`B3`）— ✅ 2026-10-02
  （判据是**真的响过一次并送到人**：告警轮询器状态里的 `last_alert_ok_ts`。
  只发自检不算 —— 自检证明管道通，不证明它会响，那是 `G5`。2026-10-02 实做：
  35 次被拒请求 → 报表出现 3 条 `rate_limit_spike`（全局 42 次 / 按端点 `/v1/auth/token` /
  按路由组 `auth`）→ 下一个 5 分钟轮询周期全部投递到运维 Telegram）
- `[机器]` `/v1/security/ops/alerts` exists and is auth-protected — ✅ 2026-10-01（HTTP 401）
- `[人工]` `/v1/security/ops/alerts` is monitored with tuned thresholds —— 待签
- `[机器]` Alert cooldown / suppression policy is configured（`B5`）— ✅ 2026-10-02
  （`alert_cooldown_minutes=10` 钉在 active 策略里。抑制的是**重复投递**，不是检测本身：
  检测照跑、告警记录照写，只是同一签名 10 分钟内不重复推送）
- `[机器]` Endpoint / route-group threshold overrides are configured for critical paths（`B6`）— ✅ 2026-10-02
  （**本轮发现它其实是空的**：`security_threshold_policies` 表 0 行，全站跑的是代码默认值 ——
  这一条以前记「待签」，真相是「没做」。现已激活 v2，在 `auth` / `runtime` / `verification` /
  `settlement` 四个关键路由组上单独收紧，明细见 [`SECURITY_THRESHOLD_POLICY.md`](./SECURITY_THRESHOLD_POLICY.md)）
- `[机器]` Active security threshold policy version is pinned and documented（`B7`）— ✅ 2026-10-02
  （判据不是「文档写没写」，而是**文档里钉的版本号跟库里 active 那一行对不对得上** ——
  对不上就 `FAIL`。文档和现实分叉比没有文档更危险）

### 已修：安全事件曾经只活在进程内存里（2026-10-02）

`services/security_monitoring.py::record_security_event` 以前把事件 append 到一个**进程内的
list**（`_EVENTS`），`build_security_ops_alert_report` 只从那个 list 取数。也就是说：

- 每次部署重建 `karma-api` / 每次重启，**最近 15 分钟的检测窗口直接归零**；
- 告警轮询是 `*/5` 的 cron，**重启恰好落在两次轮询之间，这一波的尖峰就没人看见**。

这不是推演 —— 2026-10-02 实测踩到：18:12:50Z 打了 35 次被拒请求，报表当时确实出现 3 条
尖峰告警；18:15:17Z 部署重建容器；下一次轮询（18:15:00Z 之后的 18:20:00Z）看到的是空的，
`active=0`，什么都没投递。把同样的尖峰在容器稳定时重打一次，下一个轮询周期就正常送达
（`src=alerts`）。所以链路本身是通的，**卡在「状态不落盘」**：

- 攻击者只要等到/促成一次发布，就能把跨窗口的持续性攻击切碎甚至抹掉；
- 对「持续 429 尖峰」这种**本来就靠时间累积才能判**的告警，等于随时可能漏。

**修法（2026-10-02 已做）**：事件同时追加到一份本地 journal，读的时候把内存环与 journal
按 `event_id` 合并去重。

- journal 落在 `persist_json.py` 已经在用的持久化目录（`KARMA_MVP_DATA_DIR`，容器里就是
  `/opt/karma/mvp_data:/app/mvp_data` 这个 rw bind mount），**不引入新依赖、不碰 Redis**；
- 严格 best-effort：路径不可写 / 磁盘满 → 静默退回纯内存行为，连错 5 次后本进程放弃
  重试，绝不把异常带进请求路径（`test_unwritable_event_journal_degrades_to_memory_only`）；
- 保 60 分钟、上限 4 MB，超了就近截断重写；`KARMA_SECURITY_EVENT_JOURNAL` 可以覆盖路径（测试用）；
- `clear_security_events()` 连 journal 一起清（生产没人调它，测试要干净）。

**生产实测（2026-10-02，本机跑完 6 步）**：

| 步骤 | 结果 |
|---|---|
| 造噪声前 | `failed_auth=0` |
| 打 8 次未鉴权 GET | 8 × `401` |
| 容器内 journal | `/app/mvp_data/security_events.jsonl` 1696B，最后一行是 `failed_auth` |
| 重建**之前**的报表 | `failed_auth=8` |
| `docker compose up -d --force-recreate app`（每次发布都做的那一步） | `/health` 200 |
| 重建**之后**的报表 | **`failed_auth=8`** —— 窗口活过了重建（修之前这里必定是 0） |

机器判据是 `B8`：先造一个会被记录的事件（未鉴权 401），再从发布环境里那份 journal 的
最后一行读回来 —— 读得到且够新才算 PASS。这与本轮已修的另一处是同一类问题：**只活在进程里的
状态，重启就等于没发生**（刹车模式落库那次，也是同一类）。

---

## Gate C — Security Auditability

- `[机器]` Security audit logs are collected for sensitive write methods — ✅ 2026-10-01
  （`security_audit_middleware` + `SENSITIVE_WRITE_PREFIXES`）
- `[机器]` Logs include actor ID, request path, method, status, request ID — ✅ 2026-10-01
  （代码层面；活体响应实测带 `X-Request-Id`）
- `[机器]` Log retention and query access are configured for incident response
  （`C3a` / `C3b` / `C3c`）— ✅ 2026-10-01
  （`C3a` 容器日志有轮转上限 `max-size=20m` × `max-file=5`；`C3b` journald 的
  `SystemMaxUse` / `SystemKeepFree` / `MaxRetentionSec` **显式写死**，不跟发行版默认走；
  `C3c` 留存窗口与查询命令写进 [`SECURITY_INCIDENT_PLAYBOOK.md`](./SECURITY_INCIDENT_PLAYBOOK.md) §7。
  窗口取 90 天，与密钥轮换周期同口径）

## Gate D — Error Surface Control

- `[机器]` Internal exceptions are not returned to public clients — ✅ 2026-10-01
- `[机器]` Private runtime errors are masked behind generic boundary messages — ✅ 2026-10-01
  （对不存在路由 / 未鉴权的写路径做活体探测，响应里没有 `Traceback`、`File "`、
  `site-packages`、`/opt/karma`、`sqlalchemy`、`asyncpg` 任何一项）
- `[机器]` Debug mode is disabled in production — ✅ 2026-10-01
  （`settings.debug` 默认 False，且无 `DEBUG` / `APP_DEBUG` 覆盖；外部 `/docs` 由 nginx 挡成 404）

## Gate E — Verification and Rollback

- `[机器]` Security regression tests pass in CI（`E1`）— ✅ 2026-10-02
  （以前一律待签。仓库公开，发布机 HEAD 那个 sha 的 Actions 运行列表
  **不需要 token** 就能读，直判即可；还在跑记 `HUMAN`，探不到也记 `HUMAN`
  —— 「探不到不算通过」这条规矩这里同样适用）
- `[机器]` Public acceptance script passes（`E2`）— ✅ 2026-10-02
  （公开验收由 CI 跑，与 `E1` 同一份 run 列表）
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
- `[机器]` Policy-center rollback drill has been exercised（`E7`）— ✅ 2026-10-02
  （2026-10-02 实做：建 v3 临时策略 → 激活 → 回滚到 v2，三次变更单各走一遍**两人审批**，
  回滚后 active 只剩 v2 一行。结果留在 `/opt/karma/state/security-policy-drill.json`，
  闸门读它并要求 180 天内做过。⚠️ 已知薄弱点：审批里 `approver_id` 是调用方自报的，
  所以「两人审批」目前是流程约束、不是密码学约束）

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
- `[机器]` 自检告警真的投递出去了（`G5`）— ✅ 2026-10-02
  （状态文件里的 `last_selftest_ok_ts` —— 粘性字段：真告警后来居上也不会把自检记录顶掉，
  否则「系统更健康」反而会让这一条变红。2026-10-01 运维已确认收到，
  2026-10-02 复测再次送达）

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

### 单 worker 是硬要求（不是省内存）

`services/runtime_safety.py` 的刹车状态已经**落库**（migration `0060_runtime_safety_mode`）：
写完当场提交、进程启动时灌回缓存、后台每 5 秒重灌一次。所以多 worker 不再是
「刹车只拦住 1/N」，最坏也只是晚几秒全量生效。

即便如此，**API 仍然必须单 worker** —— `deploy/docker-compose.yml` 里显式钉死
`--workers 1`，`deploy/Dockerfile.api` 同步改成 1：

- 还有若干进程内状态没落库：`runtime_key_service._replay` 的同进程 nonce 去重、
  `escrow_settlement._recover_failed_at` 的回查冷却表；
- 单机 1.6 GB 内存，多 worker 只是把 OOM 的概率乘上去。

回归用例：`tests/unit/test_single_worker_pinning.py` —— 把 `--workers 4` 写回去就红。
刹车落库本身的回归用例：`tests/unit/test_runtime_safety_persistence.py`
（「重启之后刹车还在」「关掉也活过重启」「写库失败时刹车仍生效」）。

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
