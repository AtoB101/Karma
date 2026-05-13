# Voucher API 标准（公开部分）

授权 Voucher 描述买方对卖方的任务授权与经济参数。完整请求/响应模型见 `core/schemas.py` 与 `openapi/` 中的公开契约。

## REST 入口

- 既有 API：`POST /v1/vouchers`（可选 EIP-712 校验，由 `Settings.voucher_require_eip712` 控制）。  
- Runtime Gateway：`POST /runtime/request-voucher`  
  - Header：`X-Karma-Runtime-Key`  
  - Body：`{ "client_nonce": "…", "voucher": { …CreateVoucherRequest } }`  
  - 约束：`voucher.buyer_identity_id` 必须与 Runtime Key 绑定的 `karma_identity_id` 一致；受 `single_limit` / `daily_limit` 与重放 `client_nonce` 保护。

## 公开字段（概念）

- 买卖双方身份 ID、任务类型与描述哈希、进度与证据规则哈希、金额与账单信用、过期时间、nonce、签名等。

## 私有部分

风险权重、反作弊与套利图分析等 **不得** 出现在本仓库；公开文档只描述接口与数据形状。
