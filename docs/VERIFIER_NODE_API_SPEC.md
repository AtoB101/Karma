# Karma Verifier Node — API Specification v1

> 版本: 1.0.0 | 最后更新: 2026-06-11

## 概述

Karma 验证节点是一个**外部服务**，负责验证物理世界服务的完成状态（航班到达、外卖送达、酒店入住等），并将验证结果以 attestation 形式提交到链上。

Karma 协议**只定义标准**，不提供验证节点实现。验证节点之间**竞争验证质量和速度**。

---

## 1. 角色与职责

| 角色 | 职责 |
|------|------|
| **Karma Protocol** | 托管资金、定义 IntentPackage 数据结构、执行结算 |
| **Verifier Node** | 监听待验证交易、调用外部 API 验证服务状态、提交 attestation |
| **Provider (Seller)** | 提供服务、锁仓 |
| **Buyer** | 付款、锁仓、争议 |

---

## 2. 验证节点生命周期

```
注册 → 质押 → 监听 → 验证 → 提交 attestation → 收奖励
  ↑                  ↓
  └── slashed ←── 错误验证被举报
```

### 2.1 注册

```solidity
// 链上操作
VerifierRegistry.registerVerifier(wallet, endpointUrl)
```

- `wallet`: 验证节点的 Ethereum 地址（用于签名和接收奖励）
- `endpointUrl`: HTTPS 端点（可选，供 SDK 查询节点状态）

### 2.2 质押

```solidity
// 先 approve token
ERC20.approve(registryAddress, stakeAmount)
// 再 stake
VerifierRegistry.stake(stakeAmount)
```

- `minStake` 由 admin 设定（测试网默认 100 token）
- 低于 `minStake` 自动失活
- 随时可 `unstake()` 退出

### 2.3 奖励

```solidity
// Admin 调用（每次成功 attestation 后自动触发）
VerifierRegistry.rewardVerifier(verifierAddress)
```

### 2.4 罚没 (Slash)

```solidity
// Admin 调用（错误验证被仲裁确认后）
VerifierRegistry.slash(verifierAddress, slashAmount)
```

- 罚没金额从质押中扣除
- 扣到低于 minStake → 自动失活
- ScoringEngine 同步降分

---

## 3. IntentPackage — 服务描述标准

```solidity
struct IntentPackage {
    address   buyer;               // 买家地址
    address   seller;              // 供应商地址
    bytes32   serviceType;         // keccak256("flight_booking")
    bytes     requirements;        // calldata: 结构化服务描述
    uint256   amount;              // 交易金额
    uint256   penaltyRate;         // 失败罚金（basis points）
    uint256   deadline;            // 服务必须在此时间前完成
    uint256   expiresAt;           // 意向过期时间
    bytes32   proofSchema;         // 预期证明结构指纹
    bytes32[] requiredProofFields; // 证明必须包含的字段
    address   verifier;            // 指定验证节点（address(0)=链上验证）
    uint256   disputeWindow;       // 争议窗口（秒）
    address[] arbitrators;         // 仲裁人列表
}
```

### 3.1 serviceType 枚举

| 值 | keccak256 |
|----|-----------|
| 航班预订 | `keccak256("flight_booking")` |
| 外卖配送 | `keccak256("food_delivery")` |
| 酒店入住 | `keccak256("hotel_checkin")` |
| 网约车 | `keccak256("ride_hailing")` |
| 自定义 | 任意 bytes32 |

### 3.2 requirements 格式

`requirements` 是 ABI 编码的结构体，取决于 `serviceType`。

**示例：航班预订**

```solidity
// 链下编码
struct FlightRequirements {
    string  flightNumber;    // "CA1234"
    string  departureAirport; // "PEK"
    string  arrivalAirport;   // "PVG"
    uint256 scheduledDeparture; // unix timestamp
    uint256 scheduledArrival;
    string  passengerName;
}
```

编码后作为 `requirements` 传入 IntentPackage。

### 3.3 requiredProofFields

验证节点提交的 proof 必须包含这些字段的哈希。

```
flight_booking 要求:
  - keccak256("flight_number")
  - keccak256("departure_time")
  - keccak256("arrival_time")
```

---

## 4. 验证节点工作流程

### 4.1 监听链上事件

```
监听 IntentBound(bindingId, serviceType, amount)
  → 检查 intent.verifier == myAddress
  → 检查 serviceType 是否是自己支持的类型
```

### 4.2 验证服务状态

根据 `serviceType` 和 `requirements` 调用对应的外部 API：

| serviceType | 验证 API | 验证内容 |
|-------------|----------|----------|
| flight_booking | 航司/第三方航班 API | 航班号、计划/实际起飞到达时间 |
| food_delivery | 外卖平台 API | 订单状态、配送完成时间 |
| hotel_checkin | 酒店 PMS API | 入住记录、离店时间 |

### 4.3 提交 Attestation

```solidity
// 通过 KarmaAttestationGateway 提交
KarmaAttestationGateway.submitAttestation(
    bindingId,
    keccak256(proofData),  // 证明数据哈希
    v, r, s                 // 验证节点签名
)
```

### 4.4 Settle 触发条件

当 N-of-M 个验证节点提交了一致的有效 attestation 后，任何人都可以调用 settle：

```solidity
KarmaBilateral.settle(bindingId, proofHash)
```

---

## 5. 纯数字服务验证（链上路径）

`intent.verifier == address(0)` 表示纯链上验证，无需外部节点：

- 通过 `EvidenceChain` 提交链上证据
- 链上合约验证证据是否满足 `requiredProofFields`
- 直接 settle

---

## 6. SDK 接入示例

### 6.1 注册并质押

```typescript
import { VerifierRegistry } from '@karma/sdk';

const vrf = new VerifierRegistry({
  rpc: 'https://sepolia.base.org',
  privateKey: VERIFIER_KEY,
  contract: REGISTRY_ADDRESS,
});

// 注册
await vrf.registerVerifier(myWallet, 'https://my-verifier.node/api');

// 质押
await vrf.stake(100_000_000n); // 100 tokens
```

### 6.2 监听并验证

```typescript
import { KarmaBilateral } from '@karma/sdk';

const karma = new KarmaBilateral({
  rpc: 'https://sepolia.base.org',
  privateKey: VERIFIER_KEY,
  contract: KARMA_ADDRESS,
});

// 监听 IntentBound 事件
const contract = new ethers.Contract(KARMA_ADDRESS, KARMA_BILATERAL_ABI, provider);
contract.on('IntentBound', async (bindingId, serviceType, amount) => {
  const intent = await karma.getIntentPackage(bindingId);

  // 检查是否分配给我
  if (intent.verifier !== myWallet) return;

  // 调用外部 API 验证
  const proof = await verifyService(intent);

  // 提交 attestation
  await gateway.submitAttestation(bindingId, proof.hash, v, r, s);
});
```

---

## 7. 评分体系

验证节点由 `ScoringEngine` 多维度评分：

| 维度 | 权重 | 说明 |
|------|------|------|
| reputationScore | 综合 | 0-10000，越高越好 |
| successCount | 数量 | 成功验证次数 |
| falseAttestationCount | 质量 | 错误验证次数（越低越好） |
| slashedCount | 安全 | 被罚没次数（0 最好） |

**高评分优势**：更多交易分配给高评分验证节点（SDK 查询评分后路由交易）。

---

## 8. 安全要求

1. **验证节点私钥必须安全存储**（HSM / KMS / 独立安全区）
2. **API 调用必须签名**（防止中间人篡改证明数据）
3. **不要重复提交相同 attestation**（浪费 gas 不影响结算）
4. **错误验证会被 slash**（stake 被扣除）
5. **建议运行至少 3 个验证节点实例**（高可用）

---

## 9. 节点配置参考

```yaml
# verifier-node.yaml
verifier:
  private_key: ${VERIFIER_KEY}
  wallet_address: "0x..."
  endpoint_url: "https://my-verifier.karma.dev"

chain:
  rpc_url: "https://sepolia.base.org"
  chain_id: 84532
  contracts:
    karma: "0x..."
    registry: "0x..."
    gateway: "0x..."
    evidence: "0x..."
    scoring: "0x..."

supported_services:
  - flight_booking
  - food_delivery
  - hotel_checkin

external_apis:
  flight_api_key: ${FLIGHT_API_KEY}
  food_api_key: ${FOOD_API_KEY}

scoring:
  min_profit_margin: 0.01  # 最低利润率才接单
  max_concurrent: 100       # 最大并发验证数
```

---

## 10. 下一步

- [ ] 发布参考实现（Rust / TypeScript）
- [ ] 添加 Grafana 监控面板
- [ ] 建立验证节点发现服务（链上注册表查询）
- [ ] 添加验证市场竞价（gas auction for verification priority）
