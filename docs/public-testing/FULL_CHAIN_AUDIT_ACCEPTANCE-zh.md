# 全链路审计与验收（OpenClaw / OpenManus / 测试网）

> **最近更新：** 2026-05-18  
> **公开基线：** `main`（Phase 1–3 + x402 + Karma2 同步清单模板）

---

## 1. 两层验收

| 层级 | 脚本 | 需要 RPC / 实机 |
|------|------|-----------------|
| **离链全链路** | `bash scripts/acceptance/full_chain_audit_gate.sh` | 否 |
| **测试网 + Claw/Manus 实测** | `bash scripts/acceptance/testnet_claw_manus_gate.sh` | 是（API + 可选 Sepolia） |

---

## 2. 离链全链路门（7 步）

```bash
bash scripts/acceptance/full_chain_audit_gate.sh
```

| 步骤 | 内容 |
|------|------|
| 1 | **反向规则审计** — `reverse_rule_audit.py`（KSA/KSA2/Phase 路由/迁移静态存在性） |
| 2 | Phase 1 Open Wallet（EIP-712 + OpenClaw relax + 生产 Settings） |
| 3 | Phase 2 x402 |
| 4 | Phase 3 AP2 / PaymentIntent |
| 5 | 安全攻击回归（KSA + KSA2 + KSA-TL + **KSA-AP2**） |
| 6 | `run_public_acceptance_tests.sh`（~380 pytest） |
| 7 | `production-prelaunch-gate.sh` |

单独跑静态审计：

```bash
python3 scripts/acceptance/reverse_rule_audit.py
```

---

## 3. 测试网 + OpenClaw / OpenManus

### 3.1 准备

```bash
cp deploy/.env.testnet-claw-manus.example .env.testnet.local
# 填写 KARMA_*_IDENTITY_ID、API Key、CHAIN_ANCHOR_HASH、可选 Sepolia 变量
set -a && source .env.testnet.local && set +a
uvicorn api.app:app --host 0.0.0.0 --port 8000
```

### 3.2 执行

```bash
bash scripts/acceptance/testnet_claw_manus_gate.sh
```

| 步骤 | 说明 |
|------|------|
| 1 | 先跑离链 `full_chain_audit_gate.sh` |
| 2 | `curl /health` |
| 3 | `phase1_claw_manus_smoke.py`（OpenManus `KarmaRuntimeClient`） |
| 4 | 可选 `RUN_EIP712_SMOKE=true` |
| 5 | 可选 `RUN_TESTNET_ONCHAIN=true` → `testnet_full_flow.py --send` |

### 3.3 OpenClaw MCP（人工签字）

见 [`PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md`](../PHASE1_CLAW_MANUS_LIVE_ACCEPTANCE-zh.md)：

- 路径 A：本地无 EIP-712 + `deploy/.env.local-openclaw.example`
- 路径 B：EIP-712 + `deploy/.env.local-eip712.example`
- 路径 C：测试网 + `CHAIN_ANCHOR_HASH`

### 3.4 OpenManus

- BFF：`packages/karma-openmanus` + `docs/KARMA_BFF_OPENMANUS_INTEGRATION.md`
- Runtime：`KarmaRuntimeClient.launch_trade_order`（与 smoke 脚本相同）

---

## 4. 反向规则审计（KSA 对照）

静态：`scripts/acceptance/reverse_rule_audit.py`  
动态：`tests/unit/test_security_attack_mitigations.py`、`test_level2_attack_mitigations.py`、`test_ap2_security.py`

| 族 | 公开 ID | 动态测试 |
|----|---------|----------|
| 认证/任务存在 | KSA-011, KSA-028, KSA-030 | security_attack_mitigations |
| 结算/环 | KSA2-006, KSA2-034 | level2 + triangle |
| Trade Launch | KSA-TL-* | trade_launch_security |
| x402 | KSA-X402-* | test_x402_security |
| AP2 | KSA-AP2-* | test_ap2_security |

完整表：[`attack-testing-roadmap.md`](attack-testing-roadmap.md)

---

## 5. 通过标准（Go/No-Go）

- [ ] `full_chain_audit_gate.sh` 退出码 0  
- [ ] `reverse_rule_audit.py` 退出码 0  
- [ ] 测试网 smoke：`phase1_claw_manus_smoke.py` 返回 0（买卖双方 policy/capacity 已种子）  
- [ ] OpenClaw MCP 路径 A 或 B 至少一条人工签字（见 CLAW_MANUS 清单）  
- [ ] （可选）Sepolia `testnet_full_flow.py --send` 或预授权 runbook 7/7  
- [ ] 生产部署前：`APP_ENV=production` + `production-prelaunch-gate.sh` + 真实密钥不进 git  

---

## 6. 相关文档

- [`PHASE1_OPEN_WALLET_ACCEPTANCE.md`](PHASE1_OPEN_WALLET_ACCEPTANCE.md)  
- [`PHASE2_X402_ACCEPTANCE.md`](PHASE2_X402_ACCEPTANCE.md)  
- [`PHASE3_AP2_ACCEPTANCE.md`](PHASE3_AP2_ACCEPTANCE.md)  
- [`TESTNET_RUNBOOK.md`](../TESTNET_RUNBOOK.md)  
- Karma2 私仓：`prepare-karma2-sync-package.sh` → `docs/PHASE1-3_PRIVATE_GAP_CHECKLIST-zh.md`
