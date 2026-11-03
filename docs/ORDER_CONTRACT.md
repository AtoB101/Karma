# 订购合同（Order Contract）— 双方签署 + 链上锚定

> 状态：已实现（main）。订购合同把一笔交易的**条款**固化成双方共同签署、链上锚定的
> 不可篡改对象，是争议发生时唯一的裁决依据。

## 1. 为什么需要它

托管（lock）只解决"钱在谁手里"，不解决"这笔生意到底是什么"。双方都锁了钱、都不想
出问题，但一旦交付起争议（货不对板、没按期、质检不过），必须有一份**双方都确认过、
且链上可查**的合同细则，否则仲裁无从下手。

Karma 的订购合同解决三件事：

1. **双方确认**：买家（EIP-712 钱包签名）与 worker/agent（Ed25519 签名）都签同一份条款。
2. **链上锚定**：条款哈希（`termsHash`）作为 `bind` 的 `scopeHash` 上链，改一条细则哈希就对不上。
3. **可裁决**：争议时以链上 `scopeHash` 对应的条款版本为唯一依据。

## 2. 核心概念

- **termsHash**：规范化条款的 SHA-256（64 位 hex）。金额以 6 位定长字符串入哈希
  （USDC 6 位小数），避免浮点漂移。
- **双方签名**：
  - buyer：EIP-712（`KarmaOrderContract` domain，`OrderContract(termsHash, taskId)`）。
  - worker：Ed25519，直接签 `termsHash` 字节。
- **链上锚点**：`KarmaBilateral.bind(buyerBillId, agentBillId, scopeHash)` 的 `scopeHash`
  即 `termsHash`（复用现有合约，不改合约）。
- **worker 不进条款**：worker 是下单后指派，条款哈希只锁定"交易内容"；worker 身份由其
  Ed25519 签名绑定。
- **可协商修订**：`POST /{task_id}/revise` 让任一方（buyer/worker）提出反提案——只改传入字段，
  版本 +1、重算 `termsHash`、清空旧签名、回到 `draft`，双方对新版本重新签。**链上锚定后锁定不可改。**

## 3. 完整流程

```
1. POST /v1/contracts             创建合同（DRAFT），返回 terms_hash
2. POST /v1/contracts/{id}/sign   买家 EIP-712 签名  → buyer_signed
3. (指派 worker)
   ── 可协商：worker 反提案 `revise` → 版本+1 → 双方对新版本重签 ──
4. POST /v1/contracts/{id}/sign   worker Ed25519 签名 → signed
5. POST /v1/bilateral/lock        双方各自 lock USDC，铸 Bill
6. POST /v1/bilateral/bind        传 scope_hash=terms_hash 与 task_id → 链上锚定
7. POST /v1/bilateral/settle      交付 + 证据哈希
8. POST /v1/bilateral/finalize    过争议窗口后放款
   或 POST /v1/bilateral/dispute  争议冻结（校验链上 scopeHash==termsHash）
```

## 4. API 端点

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/v1/contracts` | 创建合同（DRAFT），计算 `terms_hash` |
| POST | `/v1/contracts/{task_id}/sign` | 买家/worker 分签，验签后推进状态 |
| POST | `/v1/contracts/{task_id}/revise` | 反提案：改条款 → 版本+1、重算 terms_hash、双方重签 |
| GET | `/v1/contracts/{task_id}/terms` | 签署版条款 + 双方签名 + `terms_hash`（裁决依据） |
| GET | `/v1/contracts/{task_id}/anchor` | 链上 `scopeHash` 与 `terms_hash` 比对结果 |
| POST | `/v1/bilateral/bind` | 传 `task_id` 时强制「双签 + scopeHash==termsHash」 |
| POST | `/v1/bilateral/dispute` | 传 `task_id` 时强制「链上 scopeHash==termsHash」 |

### 签名请求体

```jsonc
// 买家（EIP-712）
{ "role": "buyer", "signature": "0x…", "address": "0x…" }

// worker（Ed25519，base64）
{ "role": "worker", "signature": "<b64>", "public_key": "<b64>" }
```

## 5. 争议裁决

- 仲裁者读 `GET /v1/contracts/{task_id}/terms` 拿**双方签署的条款 + 两个签名**。
- 用 `GET /v1/contracts/{task_id}/anchor` 确认**链上锚定的就是这份条款**
  （`anchored: true` 表示链上 `scopeHash == terms_hash`）。
- 任何单方改条款 → `terms_hash` 变 → 与链上不符 → 无效。

## 6. 外贸条款模板（可选）

创建合同时可附 6 个条款，设置后进入 `termsHash`（空值不改变哈希）：

`quality_standard`、`inspection_standard`、`shipment_terms`、
`delivery_criteria`、`penalty`、`arbitration_rules`

## 7. 安全模型与边界

- **已做**：服务端 bind/dispute 强校验双签 + 链上 `termsHash` 锚点；`spending_grant`
  控制 lock 额度；建单/结算/放款均有 grant 门。
- **未做（刻意）**：合约级双签校验 —— worker 是 Ed25519，EVM 原生无法低成本验证，
  且合约已接近 EIP-170 上限。当前以"服务端强校验 + 链上锚点"作为等价约束。
- **仍属上游/运行侧**：官网审批页部署、身份核验（KYC）、主网多签治理。
