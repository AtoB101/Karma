# 公共 API 认证与门禁说明

## `POST /v1/verify`（证据核验代理）

- 当环境变量 **`AUTH_ENFORCE_PROTECTED_ROUTES=true`** 时：必须携带 **`Authorization: Bearer <JWT>`** 或 **`X-Karma-Api-Key: karma_{agent_id}_{secret}`**，否则返回 **401**。
- 当未开启强制认证（默认本地 / 测试）：允许匿名提交，服务端将调用方记为 **`anonymous-verify`**（仅用于开发联调；**生产环境请开启强制认证**）。

实现见 `api/middleware/auth.py` 中的 `resolve_verify_submitter_id` 与 `api/routes/verify.py`。

## 其他受保护路由

大部分 `/v1/*` 写接口通过 `require_auth_if_enabled` 依赖与 `AUTH_ENFORCE_PROTECTED_ROUTES` 对齐，详见 `api/app.py` 中各 `include_router` 的 `dependencies`。

## Runtime Gateway（`/runtime/*`）

- **签发 / 吊销 / 列表**：使用钱包 EIP-191 签名，**不**使用 Runtime Key。
- **Agent 调用**：`X-Karma-Runtime-Key`；权限模型见 `docs/runtime-key-guide.md`。

## 结算线性门禁（可选）

环境变量 **`SETTLEMENT_LOCK_REQUIRES_PENDING`**（对应 `Settings.settlement_lock_requires_pending`）为 **true** 时：`POST /v1/settlement/{task_id}/lock` 不允许从 **DRAFT** 直接锁定，必须先调用 **`/pending`**。默认 **false** 以保持与现有集成测试兼容；生产可按需开启。

## 敏感写操作频率限制

对 `/v1/*` 与 `/runtime/` 下敏感写路径，中间件会调用 Redis 限速（见 `api/middleware/rate_limit.py`）。若 Redis 不可用且 `RATE_LIMIT_REDIS_FAIL_CLOSED=true`，将返回 503。
