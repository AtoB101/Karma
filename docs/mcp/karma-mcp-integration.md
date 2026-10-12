# Karma MCP 集成与发布 —— 装 / 接线 / 自检 / 发包

> 对应总指令第十节交付物里的「MCP Server 实现及配置 / 客户端接入示例 / 环境变量示例 /
> 部署、回滚说明」。口径：**只写跑过的东西**；没跑过的（PyPI 上传）明确写成「未发布」，
> 不放「已完成」的旗子。
>
> 相关：`karma-mcp-architecture.md`（分层）、`karma-mcp-tools.md`（工具契约）、
> `karma-mcp-security.md`（红线）、`karma-mcp-platform-adapters.md`（Telegram / WhatsApp）。

## 1. 三个包，装哪个

| 发行版 | 导入名 | 作用 |
|---|---|---|
| `karma-mcp-server` | `karma_mcp_server` | 通用 Agent MCP server：薄接入层，进程里**只**有 `KARMA_RUNTIME_KEY` |
| `karma-openclaw` | `karma_openclaw` | OpenClaw（或其他 host）的证明工具：执行回执 / 证据包 / handoff 校验 |
| `karma-connect` | `karma_connect` | 一行把 MCP server 写进 Codex CLI / Claude Code / Cursor / Muse / OpenClaw 的配置 |

三个包都**不是**钱包，都不持有私钥。

## 2. 怎么装

### 2.1 一行装（不 clone 仓库；今天就能用）

```bash
pip install "karma-mcp-server @ git+https://github.com/AtoB101/Karma@main#subdirectory=packages/karma-mcp-server"
pip install "karma-connect @ git+https://github.com/AtoB101/Karma@main#subdirectory=packages/karma-connect"
pip install "karma-openclaw @ git+https://github.com/AtoB101/Karma@main#subdirectory=packages/karma-openclaw"
```

这行不是「写出来好看」：CI 的 `MCP packages` 作业里另起一个干净 venv，按上面这行装，
再真跑一次 MCP 握手（`.github/workflows/mcp-packages.yml`）。要钉版本就把 `@main`
换成 `@<tag>` 或 `@<sha>`。

### 2.2 已经 clone 了仓库

```bash
pip install ./packages/karma-mcp-server ./packages/karma-openclaw ./packages/karma-connect
```

### 2.3 PyPI —— **未发布**

`pip install karma-mcp-server` 现在会 404。发布步骤见 §7，前置只有一个：一个 PyPI token。

## 3. 接进 Agent host

用 `karma-connect`（推荐，避免手改配置）：

```bash
karma-connect detect            # 这台机器上有哪些 host，配置在哪
karma-connect install            # 只写一个 karma 条目，其余行原样保留
karma-connect install --dry-run  # 先看要改什么
karma-connect doctor             # server 找得到吗、配置读得到吗、这台机器配过对吗
```

它认的 host 与写入位置：

| host | 配置文件 | 写入的 key |
|---|---|---|
| Codex CLI | `$CODEX_HOME/config.toml`（默认 `~/.codex/config.toml`） | `[mcp_servers.karma]` |
| Claude Code | `~/.claude.json` | `mcpServers.karma` |
| Cursor | `~/.cursor/mcp.json` | `mcpServers.karma` |
| Muse Code | `${XDG_CONFIG_HOME:-~/.config}/muse/settings.json` | `mcpServers.karma` |
| OpenClaw | `$OPENCLAW_STATE_DIR/openclaw.json`（默认 `~/.openclaw/openclaw.json`） | `mcp.servers.karma` |
| VS Code | `<workspace>/.vscode/mcp.json`（要带 `--workspace`） | `servers.karma` |

手写也一样，等价的一段（Codex TOML）：

```toml
[mcp_servers.karma]
command = "karma-mcp-server"
args = []
```

### 3.1 装上之后怎么才算通了

1. 重启 host，让它重新加载 MCP server。
2. 让 agent 调 `karma_connect`（`agent_name` 随便它自己起名）。它回 `user_code` +
   `verification_uri`；主人在 Karma Console 打开、核对卡片上的 `agent_fingerprint`
   与 agent 报的那个一致、设好额度、批准。
3. agent 调 `karma_connect_claim`。**批准就是激活** —— 凭据直接领回来，没有 8 位码要人肉转述。
4. 凭据落在 `~/.karma/agent.env`（0600）。聊天窗口里从头到尾不出现明文凭据。

红线：这个进程**只**能拿到 `KARMA_RUNTIME_KEY`。`KARMA_AGENT_PRIVATE_KEY` 要留在 agent
本机（签名用），把私钥注入 MCP 进程会被启动检查直接拒掉（退出码 2）。

## 4. 装完 30 秒自检

握手（`initialize`）里报的身份，就是客户端看到的东西。复制下面这段跑一遍：

```bash
python - <<'PY'
import anyio
from importlib.metadata import version
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

DIST = "karma-mcp-server"


async def main() -> int:
    async with stdio_client(StdioServerParameters(command="karma-mcp-server", args=[])) as (r, w):
        async with ClientSession(r, w) as session:
            init = await session.initialize()
    name, got = init.serverInfo.name, init.serverInfo.version
    expected = version(DIST)
    print(f"serverInfo.name={name} version={got} dist={expected}")
    return 0 if (name == DIST and got == expected) else 1


raise SystemExit(anyio.run(main))
PY
```

期望输出（版本号随包版本走）：

```text
serverInfo.name=karma-mcp-server version=0.1.0 dist=0.1.0
```

`karma-openclaw` 同理，把 `karma-mcp-server` 换成 `karma-openclaw-mcp`、`DIST =
"karma-openclaw"`。

## 5. 为什么要盯 `serverInfo`

mcp SDK 1.x 的 `FastMCP` 不把版本号转给底层 `MCPServer`，后者回落成
`importlib.metadata.version("mcp")`。结果是：**客户端握手看到的版本号是 SDK 的**，
不是 Karma 包的：

| | `serverInfo.name` | `serverInfo.version` |
|---|---|---|
| 修之前（实测） | `karma-openclaw` | `1.29.1`（= mcp SDK 版本） |
| 现在（实测） | `karma-openclaw` | `0.4.0`（= 本包版本） |

排障时这个数字会直接把人带偏（「线上跑的是 1.29.1？」）。现在两个 server 都显式把
`serverInfo.version` 钉成本包 `__version__`，并且：

- `packages/karma-mcp-server/tests/test_mcp_server_identity.py`、
  `packages/karma-openclaw/tests/test_openclaw_server_identity.py` 用内存流跑真实
  `initialize`，断言握手里的名字与版本；
- 同一个用例还比对 `pyproject.toml` 的 `version` 与包内 `__version__`，防两处漂移；
- 改 SDK 若把内部结构换掉，这些断言会立刻变红（而不是悄悄退回 SDK 版本号）。

## 6. CI 闸门：`.github/workflows/mcp-packages.yml`

| 做 | 不做 |
|---|---|
| 三个包各构建 sdist + wheel，`twine check` 卡元数据 | **不上传** PyPI |
| wheel 装进全新 venv，`[project.scripts]` 的入口必须落到 `bin/` | 不做代码签名 / sigstore |
| 用 stdio 真跑一次 `initialize`，断言 `serverInfo` 报包名 + 包版本 | 不发 release、不打 tag |
| 另起干净 venv，只按 §2.1 那行 git URL 装，再握一次手 | 不碰主网、不碰资金路径 |

本地没有网络 / 没有 `setuptools` 时（例如离线 Windows 开发机）**构建不出 wheel**，
这一步只能在 CI 里做；本地能跑的是 §4 的握手自检与包内 pytest。

## 7. 发布到 PyPI（人工，带 token）

CI 只验证「构建得出来」，发布是人的动作：

```bash
cd packages/karma-mcp-server
python -m pip install --upgrade build twine
python -m build          # 产物在 dist/：.tar.gz + .whl
python -m twine check dist/*

# 先上 TestPyPI 走一遍，再上正式：
python -m twine upload --repository testpypi dist/*
python -m twine upload dist/*        # 需要 PYPI_TOKEN（用户名 __token__）
```

发布前必须确认的单一来源：**版本号只写在 `pyproject.toml` 的 `version`**，包内
`__version__` 由测试守着与它一致。改了版本要重跑一次 §4 的自检。

## 8. 回滚

| 场景 | 动作 |
|---|---|
| 装到一半出问题 | `pip uninstall karma-mcp-server`，删 `~/.karma/agent.env`，重启 host |
| 想退到旧版本（已发 PyPI） | `pip install "karma-mcp-server==<旧版本>"` |
| 想退到旧版本（未发 PyPI） | 把 §2.1 的 `@main` 换成 `@<旧 tag / 旧 sha>` |
| host 配置被写坏 | `karma-connect` 只动 `[mcp_servers.karma]` 一个块；直接删掉该块即可 |

## 9. 还没做（诚实清单）

- **PyPI 发布**：三个包都还没上 PyPI，前置只有一个 PyPI token（§7）。
- **代码签名 / 制品溯源**：没有 sigstore、没有 attestation。
- **`karma-connect` 的 PyPI 发布**：临时只能走 2.1 / 2.2 两条路。
- 远程 Streamable HTTP 的 OAuth 2.1 授权服务器接入：见 `karma-mcp-security.md`。
