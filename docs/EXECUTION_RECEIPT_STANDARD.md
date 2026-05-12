# Execution Receipt 标准格式（Public v1.0）

本标准定义 Karma 公共仓库中的执行回执结构，用于 API / MCP / Agent Runtime 统一接入。

## 1. 核心字段（必须）

- `receipt_id`
- `task_id`
- `agent_id`
- `step_index`
- `tool_name`
- `input_hash`
- `output_hash`
- `started_at`
- `ended_at`
- `duration_ms`
- `status` (`success|failure|timeout|skipped`)
- `metadata.template` (`api|mcp|agent_runtime|ai_workflow`)

Schema 文件：

- `packages/evidence-schema/execution-receipt.schema.json`

## 2. 三类模板

### 2.1 API 模板

`metadata` 推荐字段：

- `template = "api"`
- `status_code`
- `request_hash`
- `response_hash`
- `provider_signature`（可选）

### 2.2 MCP 模板

`metadata` 推荐字段：

- `template = "mcp"`
- `mcp_server_id`
- `tool_name`
- `input_digest`
- `output_digest`
- `result_hash`
- `mcp_runtime_receipt`（可选）
- `verification_template`（可选，推荐）
  - `template_version`（`mcp-v2`）
  - `input_schema_hash`
  - `output_schema_hash`
  - `prompt_hash` / `constraints_hash` / `runtime_receipt_hash`（可选）
- `verification_template_hash`（可选）

### 2.3 Agent Runtime 模板

`metadata` 推荐字段：

- `template = "agent_runtime"`
- `node_name`
- `model_used`
- `runtime_trace_hash`
- `input_digest`
- `output_digest`

### 2.4 AI Workflow 模板（P2）

`metadata` 推荐字段：

- `template = "ai_workflow"`
- `workflow_name`
- `stage_name`
- `model_used`
- `policy_version`
- `trace_id`
- `stage_input_digest`
- `stage_output_digest`

## 3. SDK 适配器

公共 SDK 提供基础适配器：

- `APIExecutionAdapter`
- `MCPExecutionAdapter`
- `AgentRuntimeExecutionAdapter`
- `AIWorkflowExecutionAdapter`

位置：

- `sdk/adapters.py`

用法（示例）：

```python
from datetime import datetime, timedelta
from sdk.adapters import APIExecutionAdapter

started = datetime.utcnow()
ended = started + timedelta(milliseconds=120)

receipt = APIExecutionAdapter.build(
    task_id="task-001",
    agent_id="agent-001",
    step_index=1,
    tool_name="http.fetch",
    request_payload={"url": "https://example.com"},
    response_payload={"status": "ok"},
    status_code=200,
    started_at=started,
    ended_at=ended,
)
```

