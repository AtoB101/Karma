# 安全边界（公开仓库 vs 私有仓库）

## 公开仓库 **包含**

- 协议与数据形状（Schemas、OpenAPI）。  
- Runtime Gateway 路径：`/runtime/*`。  
- Console 静态页与 **Runtime Key** 管理演示。  
- Python `KarmaRuntime` 与 `@karma/runtime-sdk`。  
- 开源 Adapter 与示例脚本。  

## 公开仓库 **不包含**（必须在私有仓库）

1. 私有风控算法与评分权重  
2. 反作弊与套利检测细节  
3. 仲裁权重与恶意 Agent 识别  
4. 黑名单与争议裁决策略  

## Runtime Key 能力边界

Runtime Key **允许**：`request_voucher`、`submit_receipt`、`update_progress`、`request_settlement`、`sync_task_status`。

Runtime Key **禁止**：提现、转 USDC、修改锁仓、提升额度、改钱包、改安全规则、删除账单、修改已接受任务、绕过争议与结算状态机等。

## 用户资金与规则

所有资金动作仍受 **用户规则、Voucher、Settlement 状态机与账本不变式** 约束；Runtime Key 仅是在已授权额度与权限下的自动化 **操作员令牌**。
