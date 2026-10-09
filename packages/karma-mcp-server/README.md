# karma-mcp-server

Karma 通用 Agent MCP Server —— **薄接入层**。把已有后端能力接到 MCP，不重写任何业务。

- 设计：[`docs/mcp/karma-mcp-architecture.md`](../../docs/mcp/karma-mcp-architecture.md)
- 工具契约：[`docs/mcp/karma-mcp-tools.md`](../../docs/mcp/karma-mcp-tools.md)
- 安全：[`docs/mcp/karma-mcp-security.md`](../../docs/mcp/karma-mcp-security.md)

## 安全红线

- 本进程**只**注入 `KARMA_RUNTIME_KEY`；**禁止**私钥、助记词。启动时会检查并拒绝启动。
- 远程 HTTP 传输默认关闭（需 `KARMA_MCP_ENABLE_HTTP=1` + `KARMA_MCP_HTTP_TOKEN`；缺一拒绝启动）。
- Tier-2/3（动钱）默认不注册（`KARMA_MCP_ENABLE_TIER2/3=1` 才开）。

## 环境变量

| 变量 | 必填 | 说明 |
|---|---|---|
| `KARMA_RUNTIME_KEY` | 是（配对后） | `KRM_RT_…`；只读 |
| `KARMA_RUNTIME_URL` | 否 | 默认 `http://localhost:8000` |
| `KARMA_AGENT_PRIVATE_KEY` | 否 | Agent 签名私钥（base64/hex），留在本机 |
| `KARMA_AGENT_ID` | 否 | 主人授权的 agent id |
| `KARMA_AGENT_ENV_PATH` | 否 | 凭据文件路径覆盖（默认 `~/.karma/agent.env`） |
| `KARMA_MCP_ENABLE_TIER2` | 否 | 开启交易/交付工具（默认关） |
| `KARMA_MCP_ENABLE_TIER3` | 否 | 开启结算/争议工具（默认关） |
| `KARMA_MCP_ENABLE_HTTP` | 否 | 开启 Streamable HTTP（默认关） |
| `KARMA_MCP_HTTP_TOKEN` | 远程必填 | 远程 HTTP 的静态 bearer token；缺了拒绝启动 |
| `KARMA_MCP_STATE_DIR` | 否 | 配对状态目录（含配对码），默认 `~/.karma/pairings` |
| `KARMA_MCP_ISSUER_URL` / `KARMA_MCP_RESOURCE_URL` | 否 | 远程鉴权 issuer / resource，默认取 `host:port` |

## 运行

```bash
pip install -e ".[dev]"
karma-mcp-server                                    # stdio（本地 Agent，默认）

KARMA_MCP_ENABLE_HTTP=1 KARMA_MCP_HTTP_TOKEN=... \
  karma-mcp-server --transport streamable-http --host 0.0.0.0 --port 8765
```

远程启动有三道红线：进程里出现私钥 / 未设 `KARMA_MCP_ENABLE_HTTP=1` / 没配
`KARMA_MCP_HTTP_TOKEN` —— 任一条不满足都**拒绝启动**。

## 测试

```bash
python -m pytest -q -c pyproject.toml
```

## 当前状态（第二阶段 S2–S5 已落地）

已实现并有测试（`packages/karma-mcp-server/tests`，56 例全绿）：

- **S2 薄层**：配置 / 凭据（只读）/ Agent Ed25519 逐请求签名（与服务端逐字对齐）/
  后端客户端（错误分类 + `client_nonce`）/ 凭据 0600 落盘 / stdio 入口。
- **S3 配对与身份**：`karma_connect` → `karma_connect_status` → `karma_connect_claim`
  （配对码只落本机文件，凭据只回指纹）；身份核验、授权状态、策略、交易 / 结算 / 信誉查询。
- **S3 授权读写**：`karma_request_authorization`（预览，不写后端）→
  `karma_submit_authorization`（主人钱包签名后铸造）→ `karma_update_authorization`
  （铸新 + 撤旧）→ `karma_revoke_authorization`（一键停用）。
- **S4 远程入口**：`--transport streamable-http` + 静态 bearer token（常量时间比较）。
- **S5 交易工具**：Tier-2/3 已实现，**默认不注册**，按 Tier 白名单 fail-closed。

| Tier | 默认 | 开启方式 | 内容 |
|---|---|---|---|
| T0 只读 | 开 | — | 连接 / 身份 / 授权状态 / 策略 / 交易 / 结算 / 信誉 / 凭证查询 |
| T1 授权 | 开 | — | 授权预览 / 提交（需主人钱包签名）/ 更新 / 撤销 |
| T2 交易 | 关 | `KARMA_MCP_ENABLE_TIER2=1` | 下单 / 收款码 / 确认裁决 / 证据 / 回执 / 进度 / 结算请求 |
| T3 资金 | 关 | `KARMA_MCP_ENABLE_TIER3=1` | 凭证校验 / 争议 / 退款 |

未做（S6 及以后）：跨平台适配器（Telegram / 微信等）、完整 OAuth 2.1 授权服务器接入。
