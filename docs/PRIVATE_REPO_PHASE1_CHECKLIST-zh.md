# Karma2 私有仓库 · 阶段一配合清单（公开阶段一落地后）

公开仓完成阶段一后，私有仓（Karma2）需在同一发布窗口完成下列项。公开真源 commit 记入 `CORE_VERSION.lock`。

---

## A. 锁步与部署

- [ ] 将 `CORE_VERSION.lock` 更新为含 `0023_phase1_preauth_payment_code` 的公开 `main` commit / tag  
- [ ] `deployment-manifest.json` 中链 ID、合约地址与公开 ABI 一致  
- [ ] 运行 `./verify-manifest.sh`（或 Karma2 等价 CI）通过  
- [ ] 刷新 `vendor/karma-public-sync/` 只读快照（`prepare-karma2-sync-package.sh`）

---

## B. 链上「生成付款码时触发」（若产品要求真链上锚定）

公开仓阶段一支持 **EIP-712 买方签名** + 可选 `chain_anchor_hash` 字段；**完整链上 createBill** 在私有栈：

- [ ] BillManager / LockPool：买方意图上链 tx 与 `voucher_id` / `payload_hash` 关联  
- [ ] 索引服务：按 `chain_anchor_hash` 或 txHash 查询 Voucher  
- [ ] 测试网 Runbook 增加「付款码 + 链上锚定」冒烟

---

## C. 私有风控与 `/v1/verify`

- [ ] Private Runtime 与公开 API `POST /v1/verify` 联通（`PRIVATE_RUNTIME_API_KEY`）  
- [ ] 预授权自动接单 **不** 绕过风控；高风险 `task_type` 仍可在私有侧拦截（配置）

---

## D. OpenClaw / 卖方感应（可选增强）

- [ ] 订阅公开 webhook：`voucher.created`、`voucher.rejected`、`voucher.accepted`  
- [ ] 卖方进程：收到 `voucher.created` 后若未走公开 auto-accept，可二次调用 `POST .../accept`（需卖方 API Key）  
- [ ] 生产 env：`KARMA_OPENCLAW_REQUIRE_SERVER_ATTESTATION=true`（接单后执行链仍见公开运营清单）

---

## E. 商业与运维

- [ ] Console 生产 URL 指向公开静态 Console + 公开 API  
- [ ] 不在私有仓提交测试网私钥；密钥仅部署环境  
- [ ] 内部 Runbook：传统模式 vs 预授权模式 SOP（可复制公开 `docs/CONSOLE_PHASE1_TRADITIONAL_PREAUTH-zh.md` 链接）

---

## F. 阶段二前置（勿与阶段一混发）

- [ ] 账单币迁移合约与管理员权限模型评审（公开仓 `PHASE2` 规格）  
- [ ] 子身份结算钱包绑定流程与 Gnosis Safe 角色矩阵

---

## 签字

| 角色 | 日期 | 签名 |
|------|------|------|
| 私有仓 Owner | | |
| 链上 | | |
| 运维 | | |
