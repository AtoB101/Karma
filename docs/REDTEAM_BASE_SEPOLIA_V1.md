# Base Sepolia 红队实测 V1（多签仲裁 + 真质押栈）

Generated: `2026-10-21T21:53:09Z`
Chain: `84532`（Base Sepolia） · RPC: `https://sepolia.base.org`

## Verdict

**HARD PASS** —— 争议、退款、真质押罚没、attestation 结算、手续费分账五条链上红队路径全部通过。
单 EOA 仲裁已移除（`gateway.arbitrator` 为多签 Timelock），争议裁决受 `SplitOutsideRange` 约束
（无法单边 0~100%），`slash()` 真实划转质押代币。

## 被测栈（pinned，commit 7260531）

| 合约 | 地址 |
|------|------|
| admin_timelock | `0x57bB003B06812F0C65390f0326EAF7260E20F4CC` |
| bilateral (Karma) | `0x3fC260D90D62fCd16F748732dD08Ab4bF98F152D` |
| attestation_gateway | `0x82772891aFF05c157bE6f1b2ad82567af0D1286f` |
| verifier_registry | `0xC68Fd35A2217559B73d84E550f5c5b84009A2e4F` |
| evidence_chain | `0x51d7E773DFcce4f3B2b2d923fbc29CcDF6a9bE54` |
| scoring_engine | `0x505145B39b809732906C2663A64168D946C353Af` |
| emergency_freeze | `0xae1FcD08b888d1301b1C71183E2726bb2B5D88B8` |
| circuit_breaker | `0x0F39c6c3a81e72F10bE21c0Fff7E698a9B813Eb6` |
| reputation_anchor | `0x1B7365a4A2CbC785F8b9d493b4F3AB87f7B4dF27` |
| identity_registry | `0x3DFF3008Ea3c7cc42Ba7989411b00BC7E5Ef760e` |
| fee_bridge | `0x9961a8D301A0b9c31D2Cf112620CACFF61eE9570` |
| erc20_token (USDC) | `0x036CbD53842c5426634e7929541eC2318f3dCF7e` |

链上校验：`karma.admin` = `gateway.arbitrator` = `registry.admin` = admin_timelock；
timelock 为 testnet bootstrap 态（`minDelay=0`、`threshold=1`、owner=部署者）。

## 覆盖矩阵

| # | 流程 | 脚本 | 结果 | 会话 |
|---|------|------|------|------|
| 1 | 争议（dispute → resolve） | `scripts/e2e_dispute_refund_base_sepolia.py` Flow A | PASS | 本会话 2026-10-21 |
| 2 | 退款（refundOnTimeout） | `scripts/e2e_dispute_refund_base_sepolia.py` Flow B | PASS | 本会话 2026-10-21 |
| 3 | 真质押罚没（slash） | `scripts/e2e_slash_base_sepolia.py` | PASS | 本会话 2026-10-21 |
| 4 | attestation 结算 | `scripts/e2e_attestation_base_sepolia.py` | PASS | 部署会话 2026-10-21 |
| 5 | 手续费分账 | `scripts/e2e_feebridge_base_sepolia.py` | PASS | 2026-10-21（隔离部署） |

## 流程明细

### 1) 争议（Flow A）
- lock 10 mUSDC ×2 → bill #5 / #6 → bind #2 → ACTIVE。
- 等 60s settle delay → settle → FINALIZING → buyer dispute → DISPUTED。
- `finalizeSettle` 在 DISPUTED 下被正确拒绝（`TransactionError`），资金冻结。
- agent 提交反证 → 状态保持 DISPUTED。
- 等 60s evidence window 后：`resolveDispute(100%)` 被拒（`SplitOutsideRange`）；
  `resolveDispute(50%)` → SETTLED。
- 终态：buyer 10.0 / agent 10.0 mUSDC，两 bill BURNED，`checkInvariant`=True。
- mock `0xc55c60eD5a0A329e5E1245a1C8bf5dB3910d5dBc`，binding #2（SETTLED）。

### 2) 退款（Flow B）
- lock → bind #3 → ACTIVE → 等 60s settleTimeout → `refundOnTimeout` → REFUNDED。
- 终态：buyer 10.0 / agent 10.0 mUSDC，两 bill BURNED，`checkInvariant`=True。

### 3) 真质押罚没（slash）
- 隔离部署新 registry + mock + treasury。
- 验证者质押 1,000,000（1 mUSDC）→ active。
- `slash()` 后：stake 归零、slashed=1,000,000、active=False；
  treasury +1.0 mUSDC，registry −1.0 mUSDC（真实划转）。
- registry `0x07f081113320817d83990464C0CC38cF370A1C4a`，
  mock `0xF1BEB70C75d64CA58C81B904BC1Db6530dea0DF3`，
  treasury `0xb689894bc7E8B3b14008AeF9c9A13Aa0B95dD8be`。

### 4) attestation 结算
- 3 验证者真实质押 USDC → quorum=True → `bindWithAttestation` → 发布证据 →
  3-of-3 EIP-712 签名 → 60s 挑战窗口 → `settleWithAttestation` → binding #1 SETTLED。
- 结算：buyer 0.0 / agent 19.9 mUSDC（0.5% 手续费 0.1），`checkInvariant` 通过。
- taskId `64c61b9296…5cc74`，gateway `0x46cb1d89…`（脚本自部署）。

### 5) 手续费分账（0.5%，3/3/2/2）
- fee 0.1 mUSDC（GMV 20）；split treasury 0.03 / verifier 0.03 / buyback 0.02 / developer 0.02。
- 隔离部署，不触碰 pinned 栈。

## 复现命令

```powershell
$env:ADMIN_PRIVATE_KEY="0x<部署者私钥>"
cd <repo-root>
python scripts\e2e_dispute_refund_base_sepolia.py
python scripts\e2e_slash_base_sepolia.py
python scripts\e2e_attestation_base_sepolia.py
python scripts\e2e_feebridge_base_sepolia.py
```

## 备注 / 残余风险

- attestation 脚本会把 pinned KARMA 的 `attestationGateway` 重指向自部署网关（testnet 副作用；
  主网应由治理时间锁执行，且需正延迟）。
- timelock 当前 `threshold=1`、`delay=0` 仅限 testnet bootstrap；主网必须 `threshold≥2` 且 `delay>0`
  （部署脚本含 MAINNET GUARD）。
- 部署者 ETH 余额已降至约 0.004，继续跑 E2E 需先补水。
- feebridge 为隔离部署，结果反映 FeeBridge 合约逻辑，与 pinned 栈地址无关。
