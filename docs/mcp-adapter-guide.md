# MCP Adapter 指南（Runtime Key）

将 Karma Runtime 接入 MCP 或工作流平台时，遵循以下约束：

1. **工具密钥**：MCP Server 进程环境变量只注入 `KARMA_RUNTIME_KEY`，不要注入钱包私钥或助记词。  
2. **最小权限**：Runtime Key 权限集合保持最小，仅开启 Agent 真正需要的 `request_voucher` / `submit_receipt` 等。  
3. **证据哈希**：工具输入/输出在写入 Karma 前应先做 SHA-256；避免把用户敏感原文写入链下日志。  
4. **重放防护**：每次 `request-voucher` 与 `request-settlement` 携带新的 `client_nonce`。  
5. **响应校验**：配置 `KARMA_APP_SECRET` 与网关一致时，可校验 `X-Karma-Response-Signature`。

仓库内已有 `packages/karma-openclaw` 等示例，可作为 MCP 侧 HTTP 代理模式的参考实现；Runtime 路径应优先走 `/runtime/*` 以保持与 Console 一致。
