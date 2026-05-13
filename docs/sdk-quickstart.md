# SDK 快速开始（Runtime Key）

本仓库提供 **Python** 与 **Node / TypeScript** 两种 Runtime SDK，面向 `/runtime` 网关。

## 1. 安装

**Python（本仓库 editable 安装）**

```bash
pip install -e ".[dev]"
```

使用：

```python
from karma import KarmaRuntime
import asyncio

async def main():
    runtime = KarmaRuntime(
        runtime_key="KRM_RT_xxx",
        runtime_url="http://127.0.0.1:8000",
    )
    print(await runtime.get_permissions())

asyncio.run(main())
```

或使用环境变量：

```bash
export KARMA_RUNTIME_URL=http://127.0.0.1:8000
export KARMA_RUNTIME_KEY=KRM_RT_...
```

```python
from karma import KarmaRuntime
runtime = KarmaRuntime.from_env()
```

**Node**

```bash
cd packages/karma-runtime-sdk && npm install && npm run build
```

```javascript
import { KarmaRuntime } from "@karma/runtime-sdk";

const runtime = new KarmaRuntime({
  runtimeKey: process.env.KARMA_RUNTIME_KEY,
  runtimeUrl: process.env.KARMA_RUNTIME_URL,
});
console.log(await runtime.getPermissions());
```

## 2. 必做清单（约 30 分钟）

1. 启动公共 API（`karma-api` / `uvicorn api.app:app`）。
2. 在 Console 生成 Runtime Key，复制到 `.env`。
3. 用 SDK 调用 `get_permissions()` 校验 `chain_id`（Python 可传 `expected_chain_id`）。
4. 实现一次 `request_voucher`（或继续用既有 `/v1/vouchers` EIP-712 流程）。
5. 用 `wrap_tool_call`（或 `submit_receipt`）提交执行回执。
6. 用 `get_task_status` 对齐任务状态；完成后 `request_settlement`。

### 端到端集成验收（仓库内）

``tests/integration/test_runtime_e2e.py`` 使用与 ``tests/integration/test_api.py`` 相同的 ``httpx.AsyncClient`` + 内存 SQLite（不启动外网），覆盖：

- 钱包签名签发 Runtime Key → ``list-keys`` → ``revoke-key`` → 吊销后无法再调 ``permissions``；
- 买方 / 卖方双 Key：``capacity``、``request-voucher``、结算创建与状态推进、``submit-receipt``、``task-status``、``buyer_accept`` 全流程；
- ``permissions`` 返回中的 ``chain_id``。

```bash
python3 -m pytest tests/integration/test_runtime_e2e.py -v
```

## 3. 响应签名（可选）

当服务端与 SDK 配置相同的 `KARMA_APP_SECRET`（对齐 `Settings.app_secret_key`）时，Runtime 网关响应带 `X-Karma-Response-Signature: sha256=...`，SDK 将校验 JSON 正文 HMAC。

## 4. 延伸阅读

- `docs/runtime-key-guide.md`
- `docs/API_AUTH.md` — `/v1/verify` 与强制认证、`/runtime` 头、可选结算门禁说明
- `docs/execution-receipt-standard.md`  
- `docs/voucher-api-standard.md`  
