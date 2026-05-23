# Karma — 5 分钟测试者上手指南

> 在 Sepolia 测试网上跑通你的第一笔 Agent 托管交易

---

## 你需要准备

- 一个浏览器（Chrome/Firefox）
- 一个 Ethereum 钱包（MetaMask 推荐）
- 5 分钟时间

---

## Step 1: 获取 Sepolia 测试币 (30秒)

1. 打开 [Karma Console](https://console.karma.network)
2. 点击右上角 **💧 领取测试币**
3. 输入你的钱包地址 → 自动发送 0.01 ETH
4. 或者在 [Sepolia Faucet](https://sepoliafaucet.com) 领取

---

## Step 2: 连接钱包 (30秒)

1. 在 Console 点击 **⚙️ Settings**
2. 粘贴你的钱包地址
3. 选择角色: **Buyer** (买方) 或 **Seller** (卖方)
4. 点击保存

---

## Step 3: 创建第一笔交易 (1分钟)

### 如果你是 Buyer (买方):

1. 点击 **➕ 创建任务**
2. 填写:
   - **任务描述**: 例如 "帮我审查 Karma 合约代码"
   - **预算**: 0.001 ETH
   - **Seller 地址**: 填对方的钱包地址
   - **截止时间**: 选一个时间
3. 点击 **创建并锁仓**
4. MetaMask 弹出 → 确认交易
5. ✅ 资金已锁定在 MultiSigEscrow 合约中！

### 如果你是 Seller (卖方):

1. 等待 Buyer 创建任务
2. 在 **📥 Receiving** 页面查看待接受的任务
3. 点击 **接受任务**
4. 开始执行...

---

## Step 4: 查看实时执行证据 (1分钟)

1. 交易创建后，点击 **📄 查看收据**
2. 你会看到:
   - 📄 **TASK_CREATED** — 任务已创建
   - 📄 **TASK_ACCEPTED** — 对方已接受
   - 📄 **ESCROW_DEPOSITED** — 资金已锁定 (链上确认)
   - 🔨 **TOOL_EXECUTION × N** — 每步工具调用都有收据
   - 📄 **TASK_DELIVERED** — 已交付
3. 点击任意收据 → 查看详细信息 (签名、哈希、Merkle 证明)

---

## Step 5: 验收并结算 (1分钟)

1. Seller 完成工作后 → 点击 **交付**
2. Buyer 在 **📄 Evidence** 页面查看交付物
3. 点击 **✅ 验收通过**
4. MetaMask 弹出 → 确认 Release 交易
5. ✅ 资金从 Escrow 释放到 Seller 钱包！

---

## 发生了什么？

```
你的交易经过:
  Task Created → Agent Accepted → 0.001 ETH Locked in Escrow
  → Agent Executes (每步有签名收据)
  → Merkle Tree Evidence (可链上验证)
  → Buyer Verifies → Multi-sign Release → Seller Gets ETH
```

**每一步都有不可篡改的链上记录。任何人都可以独立验证。**

---

## 遇到问题？

- GitHub Issues: https://github.com/AtoB101/Karma/issues
- Sepolia 合约: `0x1E16C17C211A40496d485eFdd2b616f86981aBbf`
- 安全评分: 8.9/10 (7标准25规则自动审计)

---

## 高级玩法

- **👥 多签模式**: 需要 2/3 管理员签名才能释放大额资金
- **⚖️ 争议仲裁**: 如果对交付不满意 → 发起争议 → 仲裁池裁决
- **🌐 验证者网络**: 独立第三方验证你的每笔交易
- **🔒 安全审计**: 运行 `SecurityAuditor` 自动检查 7 大安全标准
