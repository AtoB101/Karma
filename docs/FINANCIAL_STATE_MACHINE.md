# Financial State Machine (on-chain)

Source of truth: `KarmaBilateral.sol` enums. This is the formal map for the funds-security plan.

## BillToken (`BillState`)

```
MINTED  (lock)  →  BOUND (bind*)  →  BURNED (settle / refund / unlock)
     ↘ unlock → BURNED
```

Illegal: `BOUND → SETTLED` does not exist on the bill; settlement is a **Binding** transition. Unlock of `BOUND` reverts.

## Binding (`BindingState`)

```
ACTIVE ──settle delay──► settle() ──► FINALIZING ──window──► finalizeSettle() ──► SETTLED
   │                         │
   │                         └── dispute() ──► DISPUTED ──► resolve / autoResolve ──► SETTLED | REFUNDED
   └── settleTimeout ──► refundOnTimeout() ──► REFUNDED

PENDING = ACTIVE + batch threshold (same payout guards)
```

Plan names vs code:

| Plan | Code |
|------|------|
| CREATED / LOCKED | `BillState.MINTED` |
| BILLED / BOUND | `BillState.BOUND` + `BindingState.ACTIVE` |
| VERIFICATION_PENDING | off-chain verification; chain waits `settleAfter` |
| SETTLEMENT_PENDING | `FINALIZING` |
| SETTLED | `SETTLED` + bills `BURNED` |
| DISPUTED / REFUNDED | same |
| FROZEN | overlay: `globalFreezeUntil` / agent / bill / binding + `CircuitBreaker` |
| EXPIRED | `refundOnTimeout` |

Undefined transitions revert (`WrongBillState` / `WrongBindingState`).

## Freeze overlay (Phase 2)

While freeze is active (`block.timestamp < until`, max 7 days) or CircuitBreaker paused:

- **Block:** bind, settle, finalizeSettle, TEE/ZK stubs, payout splits (`buyerShareBps < 10000`)
- **Allow:** view/audit, unlock `MINTED`, `refundOnTimeout`, dispute + evidence, full refund resolve (`10000` bps)

Actors: `admin` and `freezeOperator`. Control Plane: `POST /v1/admin/controls/emergency-freeze`.
