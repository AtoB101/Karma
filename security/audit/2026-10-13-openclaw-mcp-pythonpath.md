# 审计 —— OpenClaw 装上 Karma MCP 却连不上（PYTHONPATH 被宿主丢弃）

Date: 2026-10-13 · 环境：Windows 开发机 + OpenClaw `2026.8.2 (0965053)`（测试网口径，
`KARMA_RUNTIME_URL=https://karma-network.ai`）。主网未动。**无 Mock：下面每条都是真机
跑出来的**。

## 1. 现象（用户/agent 反馈）

agent（Claw）接不进 Karma MCP：既没法通过 MCP 工具用 Karma，只能手写签名直接打接口。

## 2. 复现（真机，逐字）

```text
$ openclaw mcp list
[bundle-mcp] server "karma": env "PYTHONPATH" is blocked for stdio startup safety and was ignored.
- karma

$ openclaw mcp doctor
[bundle-mcp] server "karma": env "PYTHONPATH" is blocked for stdio startup safety and was ignored.
MCP doctor (D:\OpenClaw\state\openclaw.json):
- karma: ok                     <-- 静态检查说「没问题」

$ openclaw mcp probe karma
[bundle-mcp] server "karma": env "PYTHONPATH" is blocked for stdio startup safety and was ignored.
[bundle-mcp] failed to start server "karma" (…python.exe -m karma_openclaw): MCP error -32000: Connection closed
! karma: MCP error -32000: Connection closed
```

现场配置（`D:\OpenClaw\state\openclaw.json`）里那条靠 `PYTHONPATH` 指向仓库包：

```json
{"mcp":{"servers":{"karma":{"transport":"stdio","command":"…\\python.exe",
  "args":["-m","karma_openclaw"],
  "env":{"KARMA_RUNTIME_URL":"https://karma-network.ai",
         "PYTHONPATH":"…\\packages\\karma-openclaw"}}}}}
```

## 3. 根因

OpenClaw 在拉起 stdio server 之前，按 `dist/infra/host-env-security-policy.json` 的
`blockedEverywhereKeys` **把这批键从 env 里丢掉**（2026.8.2 实测）：

`PYTHONPATH`、`PYTHONHOME`、`NODE_PATH`、`NODE_OPTIONS`、`PERL5LIB`、`RUBYLIB`、
`BASH_ENV`、`SHELL`、`GIT_*`、`CC/CXX`、`CARGO_*`、`JAVA_OPTS`、`SSLKEYLOGFILE`、
`LD_*` 类（GLIBC_TUNABLES）等 —— 它们的共同点是「决定子进程去加载哪份代码」，透传等于
把「谁来执行」交给配置，宿主宁可丢掉。

于是：**包没装进那个解释器、只靠 PYTHONPATH 找得到** → 被丢弃 → `python -m
karma_openclaw` ModuleNotFoundError → 进程秒退 → MCP `Connection closed`。而
`openclaw mcp doctor` 只做静态检查（不真起进程），所以它说 ok，**是假绿灯**。

这条对仓库是个**真缺陷**：`packages/karma-connect` 的兜底路径 `_module_command()` 恰恰
把 `PYTHONPATH` 写进宿主 env（用于「包没 pip 进解释器、只在仓库树里」的场景），所以
`karma-connect install --host openclaw` 会写出一个**永远起不来**的条目。

## 4. 修法（本轮）

- `packages/karma-connect/karma_connect/hosts.py`：`Host` 增加 `blocked_env`；把 OpenClaw
  的 `blockedEverywhereKeys` 照实记成 `OPENCLAW_BLOCKED_ENV`；`render()` 渲染时把这些键
  **剔掉，永不落盘**。
- `packages/karma-connect/karma_connect/cli.py`：新增 `_importable_without()` —— 真起一个
  子进程验证「去掉这些键之后还 import 得动吗」（不是 `find_spec` 猜，因为丢键只发生在宿主
  拉起 server 的那一刻）；`install` 遇到「剔完就起不来」的宿主**直接拒写**（退出码 2）并给出
  `pip install` 指引；`doctor` 同样报出来（不再只印 ok）。
- 文档：`packages/karma-connect/README.md` 与 `docs/mcp/karma-mcp-integration.md` 补 OpenClaw
  专节（`openclaw mcp add/probe/doctor/reload` 配方 + 「doctor ok ≠ 起得来」）。
- 真机修复：给 OpenClaw 用的解释器建了专用 venv（`D:\OpenClaw\state\karma-mcp-venv`，
  `--system-site-packages`），把 `karma-openclaw==0.4.0`（PyPI）装进去，再用
  `openclaw mcp add`（**先探测再保存**）重写条目、去掉 PYTHONPATH。

## 5. 验证（真机）

```text
$ openclaw mcp add karma --command "D:\OpenClaw\state\karma-mcp-venv\Scripts\python.exe" \
    --arg -m --arg karma_openclaw --env KARMA_RUNTIME_URL=https://karma-network.ai
Saved MCP server "karma" to D:\OpenClaw\state\openclaw.json.      # 探测通过才会保存

$ openclaw mcp probe karma
- karma: 68 tools, resources, prompts, Codex approval auto           # RC=0

$ openclaw mcp reload
Disposed cached MCP runtimes. Active agents use new MCP config on their next runtime build.
```

MCP → 后端真连通（不是握手而已）：用同一个 server 进程调 `karma_connect`，服务端
`POST /v1/agent-pairing/request` → **201 Created**。

修复后的 `karma-connect` 行为（真机跑）：

```text
$ karma-connect doctor --host openclaw
  warn openclaw drops PYTHONPATH at spawn time and karma_mcp_server is not importable
       without it - pip install ./packages/karma-mcp-server into <interpreter>      # RC=1

$ karma-connect install --host openclaw --dry-run
OpenClaw drops PYTHONPATH when it spawns a stdio server, and 'karma_mcp_server' is not
importable without it - skipping it (a written entry would never boot).             # RC=2
（openclaw.json 哈希不变 —— 没写任何东西）
```

单测：`packages/karma-connect/tests` **30 passed**（新增 5 条：屏蔽键不落盘 / 别的宿主仍保留
PYTHONPATH / 剔完起不来就拒写且不留文件 / 装进解释器后照写 / `_module_of`）。

## 6. 仍未做 / 未验证（如实记）

- **完整交易闭环仍未跑**。本地已验：`local_dual_agent_gate.sh` PASS（真实订单 +
  `execution_started` + 幂等重放）、`real_commerce_scenario_loop.py` PASS（离链全链路
  结算 SETTLED）。但「买家锁 USDC → 凭证 → 回执 → 结算」那一笔需要**有余额的 Sepolia
  买卖双方**（USDC + ETH），当前没有资金账号；2026-10-11 那次 22/22 真机闭环用的
  live harness 不在本仓库里。
- **OpenClaw 网关里 agent 真调一次 MCP 工具**没跑（那要驱动一次 agent turn；本轮验到
  `probe` 列出 68 工具 + 独立进程调 `karma_connect` 拿到 201）。
- 本机 `scripts/e2e_smoke.py` 已过时（发 `worker_agent_id` 被拒、仲裁池口径也变了，
  16 步失败），且**没有任何门禁引用它**。属于遗留脚本，本轮没动。

## 7. 追加（同日第二轮）：默认模型 id 坏了 —— 现象同样是「openclaw 工具报错」

§6 里「OpenClaw 网关里 agent 真调一次 MCP 工具没跑」这一条，本轮补上了，并且顺带挖出
**第二个能把 agent 侧整条锁死的坑**（根因完全不在 MCP）。

### 7.1 现象

agent 侧任何 turn 都过不去。在 agent 门口看，就是「openclaw 工具报错 / MCP 注册、重载不动」——
和 §1 的现象几乎一样，很容易被当成 MCP 的问题。

### 7.2 真机复现（逐字）

```text
$ openclaw models status
Default : deepseek/to

$ openclaw agent exec "…"                      # 走默认模型
[provider-transport-fetch] response provider=deepseek api=openai-completions model=to status=400
LLM request failed: provider rejected the request schema or tool payload.
rawError=400 The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed to.
[model-fallback/decision] decision=candidate_failed requested=deepseek/to … next=none
```

`D:\OpenClaw\state\openclaw.json` 里 `agents.defaults.model.primary = "deepseek/to"` ——
一个 provider 不认的 id（`openclaw.json.bak.2/.3/.4` 里还是好的
`deepseek/deepseek-v4-pro`，从 `bak.1` 起就变成 `deepseek/to`）。

**关键干扰项**：这时 `openclaw mcp probe karma` 照样 `68 tools` 全绿 —— probe 是 CLI
直接起进程，压根不走模型。所以只盯 MCP 侧的话，所有检查都是绿的，只有 agent 侧是红的。

### 7.3 修法

```bash
openclaw models set deepseek/deepseek-v4-pro    # 写回一个真 id（自动生成 openclaw.json.bak）
```

改前副本另存为 `D:\OpenClaw\state\openclaw.json.before-model-fix`。

### 7.4 验证（agent 侧，真机）

```text
$ openclaw mcp reload
Disposed cached MCP runtimes. Active agents use new MCP config on their next runtime build.

$ openclaw agent --agent main --json \
    --message "只列出现在可用的 karma_ 开头的 MCP 工具名，不要调用任何工具"
{ "status": "ok",
  "result": { "meta": { "provider": "deepseek", "model": "deepseek-v4-pro", … },
              "payloads": [ … 68 条 karma_* 工具名 … ] } }

$ openclaw mcp probe karma
- karma: 68 tools, resources, prompts, Codex approval auto
```

即：**连通层 + agent 工具面这一层现在是真的通了** —— 经由网关真实跑的 agent turn，看见
全部 68 个 `karma_*` 工具，不再是「probe 绿、agent 红」。

同一个 server 进程打后端也复验过：`karma_connect` → `POST /v1/agent-pairing/request`
→ **201 Created**（本机沙箱只挡了它写 `~/.karma`，不改结论）。

### 7.5 仍未做（如实记）

- **完整链上交易闭环仍未跑**：需要**有余额的 Sepolia 买卖双方**（USDC + ETH）。当前没有
  资金账号，也没人给过；仓库里的 `scripts/faucet.py`（mUSDC 水龙头）要 `FAUCET_KEY`
  才能出币。本地离链那条已经绿（见 §6）。
- 文档：`docs/mcp/karma-mcp-integration.md` 新增 §3.1 记这条坑，原 §3.1 顺延为 §3.2。
