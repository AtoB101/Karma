# Agent Runtime 集成

本页描述 **Agent** 与 Karma **Runtime Gateway** 的推荐集成顺序。

## 角色分工

| 角色 | 持有物 | 职责 |
|------|--------|------|
| 用户 | 钱包私钥 | 仅在官方 Console 授权额度、签名创建/吊销 Runtime Key |
| Agent | Runtime Key | 在权限子集内请求 Voucher、提交回执、同步状态、请求结算 |

## 推荐流程

1. **创建 Runtime Key**：Console 调 `POST /runtime/create-key`（钱包签名）。  
2. **启动 SDK**：`KarmaRuntime(runtime_key=..., runtime_url=...)`。  
3. **校验**：`verify_key()` / `get_permissions()`，可选校验 `chain_id`。  
4. **容量**：`get_capacity()`（绑定身份）。  
5. **授权**：`request_voucher()`（带 `client_nonce` 防重放）。  
6. **执行**：业务工具外包在 `wrap_tool_call()`。  
7. **进度**：`update_progress()`（需满足 Settlement 与进度曲线校验）。  
8. **状态**：`get_task_status()`。  
9. **结算**：`request_settlement()`（`submit_delivery` / `buyer_accept` / `partial`）。  

## 高风险任务

当单笔金额或任务类型属于「高风险」类目时，应在 **Console 策略** 中要求人工确认；公开仓库不定义具体风控阈值。

## 与 MCP / 工作流

参见 `docs/mcp-adapter-guide.md`。
