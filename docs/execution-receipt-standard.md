# Execution Receipt 标准（公开摘要）

Execution Receipt 记录 **单次工具调用** 的可验证摘要，是证据链中的原子单元。完整字段定义见 `core/schemas.py` 中的 `ExecutionReceipt`。

## 公开字段（概念）

| 字段 | 含义 |
|------|------|
| `task_id` | 所属任务 |
| `agent_id` | 执行者身份（Runtime 路径下与 Karma Identity 对齐） |
| `step_index` | 从 1 递增的序号 |
| `tool_name` | 工具名 |
| `input_hash` / `output_hash` | 输入/输出的 SHA-256（十六进制），**不**上传明文 |
| `started_at` / `ended_at` / `duration_ms` | 时间约束 |
| `status` | `success` / `failure` / `timeout` / `skipped` |
| `metadata` | 扩展元数据（可含 `runtime_log_hash` 等） |
| `signature` | Ed25519 签名（由可信边缘或服务根据部署配置签署） |

## Runtime Gateway

`POST /runtime/submit-receipt` 在校验 Runtime Key 权限 `submit_receipt` 后，对回执进行静态校验并由服务端使用配置的 Ed25519 材料签名，再写入与 `POST /v1/receipts` 相同的存储路径。

## SDK `wrap_tool_call`

Python / Node SDK 的 `wrap_tool_call` 会：

1. 计算输入/输出摘要（哈希）。  
2. 记录耗时与状态码。  
3. 生成 `runtime_log_hash`（对结构化日志信封做哈希，不上传原始日志正文）。  
4. 调用 `submit_receipt` 并尝试 `get_task_status` 做状态同步（失败不阻断主流程）。

## 与私有运行时的边界

验证引擎如何权衡多步回执、如何与 Voucher / Settlement 状态机关联，属于 **私有运行时** 行为；公开仓库只定义数据形状与接入点。
