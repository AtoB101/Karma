# Open Wallet 签名集成（Phase 1）

> **最近更新：** 2026-05-18（基线 `main` @ `84b9345`）  
> **路线图：** [`KARMA_ECOSYSTEM_INTEGRATION_ROADMAP-zh.md`](KARMA_ECOSYSTEM_INTEGRATION_ROADMAP-zh.md)

## 目标

贸易启动（`POST /v1/trade/orders/launch`）支持 **EIP-712 TradeLaunchIntent**，使买方可在 **浏览器钱包 / WalletConnect / 本地密钥后端** 签名，Runtime **不保存买方私钥**。

## 配置

| 变量 | 默认 | 说明 |
|------|------|------|
| `TRADE_LAUNCH_REQUIRE_EIP712` | `false` | `true` 时强制校验 `buyer_signature` 与绑定钱包 |
| `TRADE_LAUNCH_EIP712_CHAIN_ID` | 空 → `TESTNET_CHAIN_ID` | EIP-712 domain `chainId` |
| `TRADE_LAUNCH_EIP712_VERIFYING_CONTRACT` | `0x000…000` | domain `verifyingContract` |
| `TRADE_LAUNCH_SIGNATURE_TTL_SECONDS` | `600` | `deadlineUnix` 相对当前时间 |
| `KARMA_SIGNING_BACKEND` | `client_only` | `client_only` / `external` / `local` / `env` |
| `KARMA_SIGNING_DEV_PRIVATE_KEY` | 空 | `env` 后端用（**勿提交主网钥**） |
| `TESTNET_PRIVATE_KEY` | 空 | `local` 后端用 |

生产建议（`APP_ENV=production` 启动校验）：

- `TRADE_LAUNCH_REQUIRE_EIP712=true`
- `KARMA_SIGNING_BACKEND=client_only` 或 `external`（禁止 `local`/`env`）
- `RUNTIME_REQUIRE_WALLET_IDENTITY_BINDING=true`
- `TRADE_LAUNCH_RECORD_RUNTIME_DAILY_SPEND=true`（launch 金额计入 Runtime Key 日限额，与 policy 对齐）

## 与 voucher 的统一承诺（Phase 1.5）

贸易流水线在 `progress_rule_spec.trade_launch_attestation` 写入启动证明；`buyer_signature` 为 **TradeLaunchIntent** 签名。

- `POST /v1/vouchers` / payment-codes：若 spec 含 attestation 且开启 trade EIP-712，走 **同一套** TradeLaunch 校验（`services/voucher_buyer_commitment.py`），无需再签 AuthorizationVoucher。
- 手动 payment-code 路径：仍可使用 `VOUCHER_REQUIRE_EIP712` + AuthorizationVoucher 签名。

## API 流程

### 1. 预览 typed data（钱包签名）

```http
POST /v1/trade/orders/launch/signing-preview
Idempotency-Key: <same-as-launch>
```

请求体与 launch 相同（**无需** `buyer_signature`）。响应含 `typed_data`、`buyer_wallet_address`、`launch_nonce`、`deadline_unix`。

### 2. 客户端签名

使用 MetaMask / viem / ethers 对 `typed_data` 做 `eth_signTypedData_v4`，得到 `0x` ECDSA 签名。

### 3. 启动流水线

```http
POST /v1/trade/orders/launch
Idempotency-Key: <same-as-preview>
```

Body 含 `buyer_signature`（上一步结果）。

### 开发/CI：服务端签名

当 `KARMA_SIGNING_BACKEND=local` 或 `env`：

```http
POST /v1/trade/orders/launch/sign-with-backend
```

返回 `buyer_signature`（**禁止**在生产对公网暴露）。

## 策略前检查

除 EIP-712 外，launch 前仍执行：

- `automation-policy` 的 `single_limit` / `allowed_task_types` / 精度区间（`clamp_spec_to_policies`）
- **当日累计** launch 金额不超过 `daily_limit`（`services/spending_policy.py`）

## SDK / MCP

| 组件 | 入口 |
|------|------|
| Python 后端 | `sdk/signing_backend.py`、`services/trade_launch_eip712.py` |
| OpenClaw MCP | `karma_trade_launch_signing_preview`、`karma_trade_launch_sign_with_backend` |
| OpenManus | `KarmaRuntimeClient.trade_launch_signing_preview()` |

## 威胁模型（简表）

| 模式 | 私钥位置 | 适用 |
|------|----------|------|
| `client_only` + EIP-712 | 用户钱包 | 生产买方 |
| `local` / `env` | 服务器环境变量 | CI / Sepolia 自动化 |
| 无 EIP-712（默认） | 任意占位符 | 现有集成测试兼容 |

## 测试

```bash
bash scripts/acceptance/phase1_open_wallet_gate.sh
```

验收摘要与 Sepolia 人工表：[`public-testing/PHASE1_OPEN_WALLET_ACCEPTANCE.md`](public-testing/PHASE1_OPEN_WALLET_ACCEPTANCE.md)。

## 下一步（Phase 2）

x402 HTTP 402 支付与 `external_payment` 收据字段 — 见生态路线图 Phase 2。
