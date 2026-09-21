# Settlement flow (public)

Canonical on-chain settlement is **KarmaBilateral** only:

- Contract: `karma-core/contracts/core/KarmaBilateral.sol`
- Off-chain adapter: `services/chain/settlement_adapter.py`
- Plan builder: `evidence_runtime/settlement_adapter.py`

## Happy path

```text
lock(token, amount)     → mint Bill Token 1:1 (MINTED), USDC in escrow
bind(buyerBill, agentBill, scopeHash) → both bills BOUND
… execute task, collect evidence …
settle(bindingId, proofHash) → FINALIZING (dispute window)
finalizeSettle(bindingId)    → burn bills, release USDC (SETTLED)
```

Global invariant: `totalBillSupply[token] == totalLocked[token]`.

## States (informative)

**Bill:** `MINTED → BOUND → BURNED`  
**Binding:** `ACTIVE → FINALIZING → SETTLED | DISPUTED | REFUNDED | …`

## Off-chain mirrors

Capacity / voucher ledgers under `services/` reserve bill credits before or alongside chain locks.  
They must not invent a second escrow model — chain Bilateral is authoritative for on-chain funds.

v2 allowance escrow (``KarmaAllowanceEscrow``) locks nothing: the wallet only grants an
allowance, so the master ``capacity`` ledger is credited from the claimed ``commit()`` receipt
(``services/chain/allowance_escrow.reconcile_capacity_mirror``) — one credit per live
commitment, taken back on ``revoke()`` and reduced as Karma pulls the money.

## Allowance escrow (`KarmaAllowanceEscrow`, v3/v4/v5)

Still non-custodial: the buyer's wallet only grants an allowance, so no USDC sits in the
contract. What v3/v4/v5 tighten is *who may move the money* and *when the lock may be undone*.

```text
bind(...)                        -> ACTIVE      (allowance reserved on both bills)
submitSettlement(bindingId, hash)-> FINALIZING  (resolver-only; opens a *payout* window)
submitBreach(bindingId, hash)    -> FINALIZING  (resolver-only; opens a *slash* window)    [v5]
markDisputed(bindingId)          -> DISPUTED    (resolver-only; freezes it, no money moves) [v5]
buyerConfirm(bindingId)          -> FINALIZING  (buyer's own yes; skips the wait)
finalizeSettlement(bindingId)    -> SETTLED     (pull buyer wallet -> seller wallet)
finalizeBreach(bindingId)        -> SLASHED     (seller stake -> buyer)
cancelBinding(bindingId)         -> CANCELLED   (from ACTIVE by a party, DISPUTED by resolver only)
```

- **A window carries its direction.** `FINALIZING` used to mean only "somebody's money is about
  to move", with the direction left to whichever exit ran first. `finalizeSettlement` is
  permissionless by design — its destination is fixed — so on a binding the resolver had already
  ruled a breach, *any* passer-by could crank the payout window and hand the seller the goods
  money; `finalizeBreach` could then never run again. v5 fixes the direction when the window is
  opened: `submitBreach` arms a slash window (`finalizeSettlement` reverts on it), and
  `submitSettlement` arms a payout window (`finalizeBreach` reverts on it, resolver included).
  Re-ruling stays the resolver's call — it just has to open a new window to do it.
- **`markDisputed` freezes the parties, not the money.** `ACTIVE` cannot tell "just bound, nobody
  moved" from "delivered, under arbitration", so a seller ruled in breach could simply
  `cancelBinding` mid-arbitration, release its own stake reservation, and leave the ruling with
  nothing to enforce. `DISPUTED` closes that: no party may cancel, and the exits are again the two
  that move money. The resolver keeps one extra exit — its own cancellation *is* the ruling that
  nothing has to move — because a freeze needs a way out when a party goes silent.
- **`bindingVersion()`** is how the platform probes a contract for the two v5 entry points.
  Historical bindings still point at older contracts, so the probe is per address and never
  "whatever is configured now".

- **`cancelBinding` is a state gate, never a clock gate.** `ACTIVE` is the one state in
  which the binding's money has no owner-in-waiting, so releasing the reservations there
  is free. From `FINALIZING` on the funds carry responsibility and the only two exits are
  the ones that *also move the money* (`finalizeSettlement` / `finalizeBreach`). A window
  that either party could revoke would be an option to walk away after delivery.
- **`buyerConfirm` only shortens a wait.** It is `FINALIZING`-only, buyer-or-buyer-operator
  only, and can never start a payment, change an amount, or touch another binding. Verified
  delivery *plus* the buyer's own yes is exactly the case the window existed to wait out;
  with no mark, the window still expires on its own and the pull goes through.
- Verification is a *condition*, not advice: only the resolver account may open a window.
- Off-chain mirror: `services/chain/escrow_settlement.py` always re-reads the chain state
  before touching money, and adopts `FINALIZING` from chain when the ledger lags behind.

## Not in this repo

Legacy `NonCustodialAgentPayment` / `SettlementEngine` paths and createBill scripts were removed.

Runtime adapter (`services/chain/settlement_adapter.py`) broadcasts `bind` / `settle` / `finalizeSettle` /
`dispute` / `refundOnTimeout` when `SETTLEMENT_MODE=testnet|hybrid` and `TaskContract.onchain_*` ids are set.
