# Karma MCP —— Tier 2/3 真机验收记录

本文件记录 **2026-10-11** 在测试网对 `packages/karma-mcp-server` 的 Tier 2 / Tier 3
工具做的**真机闭环实测**。全程**无 Mock、无硬编码结果**：每一笔都打到真实后端、
真实状态机、真实链上托管。

## 1. 被测环境

| 项 | 值 |
| --- | --- |
| API | `https://karma-network.ai`（测试网，`KARMA_ENV=production` 语义的生产开关全开） |
| 链 | Sepolia `chain_id=11155111` |
| 托管合约 | `0x65eb82058F4ea707B1a0aFb2A5872eb95076b6F2`（`KarmaAllowanceEscrow` v5） |
| 结算币 | `0x6AF606f5B071BF649DC136fCd308ed0c9ADf38FF`（mUSDC，6 位小数） |
| 链上 operator | `0x1D147c9eefd9D1d4C4725700a05EDc6ca13975Cc`（bind/submit 由 Karma 代跑） |
| MCP | `McpConfig(enable_tier2=True, enable_tier3=True)`，默认仍为 fail-closed |

被测身份是一套**全新生成、自持私钥**的测试夹具（主人钱包 + agent Ed25519 + Runtime Key +
买卖双方 API Key 全部本机生成）。买方的链上锁仓是本人钱包真实签名广播的
`approve()` + `commit()`，后端只按交易回执记账，**没有任何私钥离开钱包**。

## 2. 结果

`python <live-harness> all` 输出：

```
SUMMARY|total=22 fail=0
```

| 组 | 用例 | 结果 |
| --- | --- | --- |
| T1 自助授权 | 预览 → 主人钱包签名 → 铸 key → agent 公钥指纹绑定 → 主人确认上线 | 6/6 PASS |
| Important Fields | protocol capture → 买卖双方 `submit-encrypted`（karma2 密文）→ `match-secure` 封存 | 3/3 PASS |
| T2 下单 | `karma_create_transaction` → 真出凭证 / 结算单（`in_progress`） | 1/1 PASS |
| T0 只读 | `karma_get_voucher` / `karma_get_settlement_status` / `karma_get_transaction_status` | 3/3 PASS |
| T2 证据 | `karma_verify_evidence` 对上真实 404 裁决（**不谎报成功**） | 1/1 PASS |
| T2 卖方接单 | `karma_accept_payment_code` 打到真实接单口；凭证在链上状态为 `accepted` | 3/3 PASS |
| T3 争议/退款 | `karma_open_dispute` → 结算转 `disputed`；`karma_request_refund` 共用同一冻结入口 | 3/3 PASS |
| 失败语义 | 缺 `seller_identity_id` / 重复退款全部 fail-closed | 2/2 PASS |

## 3. 链上痕迹（可自行到 Sepolia 浏览器核对）

- 买方锁仓 `commit()`：`0x375db2243e7f132d97f039af2b32f768258fad1240fa4a3a1362acb83adc5871`
  → 本地账单 `allowance_commits.bill_id = 0x65eb…b6F2:10`，25 USDC，`state=open`、`backed=true`
- 接单绑定（任务 `a6a5111d-…`）：`escrow_bindings.binding_id=308`，`state=active`，
  `bind_tx=0x2a1cff63b8ef73c126d7e4701931f537730528182f3822b638b6334ebc789e24`
- 争议绑定（任务 `e8f697a2-…`）：`escrow_bindings.binding_id=309`，`state=disputed`，
  `bind_tx=0x04178ba9676aec7ec17d26d11350ef2699ba75d8295d45ba80d48a51b90af87d`
- 结算：`settlements.status = disputed`；`capacity` 镜像 `reserved=2, disputed=1`
- 已接受的凭证：`voucher_id = 77b9156f-7952-4635-ac54-eb54f6324d4f`

## 4. 一并跑过的自动化闸

| 命令 | 结果 |
| --- | --- |
| `ruff check packages/karma-mcp-server` | All checks passed |
| `pytest packages/karma-mcp-server/tests -q` | 73 passed |
| `pytest tests/unit/test_agent_message_parity.py tests/unit/test_identity_verification.py -q` | 24 passed |
| 工具数（默认 / +T2 / +T2+T3） | 17 / 25 / 28（与 `karma-mcp-tools.md` §4 表一致） |

## 5. 本次**没有**声称的东西

- 未在主网做任何资金操作；全部在测试网。
- `karma_verify_evidence` 只做摘要比对，**不代表**后端已作出验证裁决。
- `karma_request_refund` 与 `karma_open_dispute` 共用同一后端入口：agent 只能**发起**，
  退款/放款只能由仲裁结果驱动，MCP 层没有任何自行放款能力。
- 买方锁仓额度由**用户自己钱包**持有；Karma 只能在这条 ERC-20 授权额内划动。

## 6. Agent 自动接入：邮箱回执（第三把锁）真机验收

本步（commit `b458e08`）在同一台测试网 VPS 上实测「配对 + 邮箱回执」
（`/opt/karma/repo` HEAD=`b458e08`，`karma-api` healthy）。全程**无 Mock**：真实 HTTP、
真实配对状态机、真实 `smtplib` 出站。

### 6.1 出口未配置时（fail-closed）

| 用例 | 期望 | 实测 |
| --- | --- | --- |
| `approve` 带 `notify_email` | 503 | 503 |
| 被拒后该配对仍是 `pending`（不许「批准了但锁没加上」） | `pending` | `pending` |
| `GET /v1/agent-pairing/email-confirm` 假 token | 409 + HTML | 409 |
| owner 路由匿名调用（approve / lookup） | 401 | 401 |
| `approve` 不带 `notify_email` | 200，`email_confirm={"required": false, "state": "off"}`，claim 正常交付 | 一致 |

### 6.2 出口配好之后（受控 SMTP 出口，全链路）

在 VPS 上临时起一个**受控 SMTP sink**（宿主进程监听 `0.0.0.0:2525`），把
`KARMA_MAIL_HOST/PORT/FROM/SSL` 经 `/opt/karma/.env` 注入后 `docker compose up -d` 重建容器；
测完**已还原 `.env` 并重建**，`mailer.configured()` 回到 `False`。

| 用例 | 期望 | 实测 |
| --- | --- | --- |
| `approve` 带 `notify_email` | 200，`delivered=true`，`email_masked=ow***@example.com` | 一致 |
| sink 收到的信 | 正文含 3 个候选码 + 3 条链接，**不含任何凭据** | 一致（3 码 / 3 链接，无 `karma_`） |
| 邮箱未点之前 `claim` | `awaiting_email_confirm`，**无凭据** | 一致 |
| 拿 `match_code` 当 token（配对码泄漏者） | 409 —— 单知道这个码换不到东西 | 409 |
| `resend` 之后，旧邮件里的 token | 409（旧码当场作废） | 409 |
| 点一个干扰码 | 409 | 409 |
| 点对的那个码 | 200（再点一次仍 200，不重复扣） | 200 / 200 |
| 确认后 `claim` | `approved` + `api_key` | 一致 |
| 凭据是否出现在邮件正文 | 否 | 否 |
| 用交付的 `api_key` 调 owner 端点 | 200（key 真实可用） | 200 |
| `resend` | 200，重出码 | 200 |

### 6.3 夹具清理（已执行）

- 临时 owner bootstrap key + 本次 4 把 agent key 从 store 删除：**175 → 170**（回到基线）；
- 4 个 custody 托管私钥文件删除；测试配对记录 **203 → 199**；
- 删除后旧 owner key 实测 **401**；`.env` 已还原（`KARMA_MAIL_*` 计数 = 0），
  `mailer.configured()=False`。

### 6.4 本次**没有**声称的东西

- **真实外部邮箱投递未验证**：环境没有可用的 SMTP 凭据，6.2 用的是受控 sink。它证明了
  「配置齐了之后整条链路真的能跑通」（真实 `smtplib` 会话 + 真实 HTTP + 真实状态机），
  但**不等于** QQ / Gmail 收件箱收得到信；凭据到位后需补一次真实投递。
- 未在主网做任何操作；本步全部只碰测试网。
