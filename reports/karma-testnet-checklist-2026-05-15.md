# Sepolia testnet — full acceptance checklist (2026-05-15)

**Network:** Ethereum Sepolia (`chain_id=11155111`)  
**Outcome:** 39 / 39 checks passed (operator-reported matrix)  
**Related:** `docs/TESTNET_RUNBOOK.md` — `proofHash` format, `createBill` gas (~760k+ vs ~300k cap), capacity notes.

Where a section shows fewer bullet lines than the `n/n` score (e.g. automation bundles several assertions), the **score is authoritative**; extend this file with your per-step rows if you need a line-by-line audit trail.

---

## Summary

| Area | Result |
|------|--------|
| On-chain contracts | 6 / 6 |
| Token & permissions | 4 / 4 |
| Policy configuration | 5 / 5 |
| Capacity / lock | 6 / 6 |
| Bill lifecycle | 8 / 8 |
| Security boundaries | 8 / 8 |
| API mode + gas | 8 / 8 |
| **Total** | **39 / 39** |

---

## On-chain contracts (6 / 6)

```
MockUSDC 部署           ✅  0x6AF606...
NC 合约部署             ✅  0x17Da96... (42KB)
Owner 验证              ✅  0x7Ed43...
CircuitBreaker          ✅  false
BatchMode               ✅  true
```

**NC (full checksum):** `0x17Da96226a4e776140B103b22c0A86bB28BC5F97` — [Sepolia Etherscan](https://sepolia.etherscan.io/address/0x17Da96226a4e776140B103b22c0A86bB28BC5F97)

---

## Token & permissions (4 / 4)

```
MockUSDC 白名单         ✅  setSettlementTokenAllowed
SettlementTokenEnforced ✅  false
minSettlementAmount     ✅  0
```

---

## Policy configuration (5 / 5)

```
setPolicy               ✅  perTx=1000, daily=10000
Scope 白名单            ✅  karma:agent-task:v1
Seller 白名单           ✅  0xE692B0...
PolicyPayee 验证         ✅  true
```

---

## Capacity / lock (6 / 6)

```
Buyer Lock 65 USDC      ✅  active=65
Seller Lock 1 USDC      ✅  active=1
Approve + Lock 流程      ✅  ERC20→NC
AccountConsistent       ✅  true
SellerBond 计算          ✅  100bps=1%
```

---

## Bill lifecycle (8 / 8)

```
createBill (0.5 USDC)   ✅  760K gas
proofHash 格式           ✅  karma-ta:v1/sha256/<64h>
confirmBill             ✅  52K gas
requestBillPayout       ✅  121K gas
结算后 Buyer locked=64.5 ✅
```

---

## Security boundaries (8 / 8)

```
seller==msg.sender      ✅  Unauthorized
Scope 未授权             ✅  ScopeNotAllowed
Seller 未授权            ✅  CounterpartyNotAllowed
买方余额不足             ✅  CapacityInsufficient
卖方余额不足             ✅  CapacityInsufficient
onlyOwner               ✅  Unauthorized
空地址/零金额            ✅  InvalidAddress/Amount
```

---

## API mode + gas (8 / 8)

```
Testnet API 启动         ✅  chain_id=11155111
Agent→Contract→Receipt  ✅  全201
Settlement draft→delivered ✅
createBill gas=760K     ⚠️ 之前设300K导致全部revert
```

---

## Notes

- **`CapacityInsufficient`** (not enough unreserved `active` for buyer/seller) is different from **out-of-gas** when `createBill` is sent with a **~300k** gas cap; observed successful `createBill` is **~760k gas**.
- Abbreviated addresses (`0x6AF606...`, `0x17Da96...`, `0x7Ed43...`, `0xE692B0...`) match the operator log; use full checksums in internal runbooks.
