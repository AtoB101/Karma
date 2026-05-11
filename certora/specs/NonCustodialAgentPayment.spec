/*
 * Karma Trust Protocol — Certora Formal Verification Spec
 * Contract: NonCustodialAgentPayment.sol
 */

using NonCustodialAgentPayment as payment;

// ── Account Consistency Invariant ──────────────────────────────────────────
invariant accountConsistency(address user, address token)
    getAccountState(user, token).locked
        == getAccountState(user, token).active + getAccountState(user, token).reserved;

// ── Lock Positivity ───────────────────────────────────────────────────────
invariant lockNonNegative(address user, address token)
    getAccountState(user, token).locked >= getAccountState(user, token).active
    && getAccountState(user, token).active >= 0
    && getAccountState(user, token).reserved >= 0;

// ── No Double Settlement ──────────────────────────────────────────────────
rule noDoubleSettlement(method f, mathint billId) {
    env e;
    payment.Bill billBefore = getBill(billId);
    
    require billBefore.billId != 0;
    require billBefore.status == payment.BillStatus.Settled
        || billBefore.status == payment.BillStatus.ResolvedBuyer
        || billBefore.status == payment.BillStatus.ResolvedSeller
        || billBefore.status == payment.BillStatus.SplitResolved;
    
    calldataarg args;
    f(e, args);
    
    payment.Bill billAfter = getBill(billId);
    
    assert billAfter.status == billBefore.status,
        "Settled bill status must not change";
}

// ── Only Buyer Can Confirm ────────────────────────────────────────────────
rule onlyBuyerConfirms(mathint billId) {
    env e;
    
    payment.Bill bill = getBill(billId);
    require bill.billId != 0;
    require bill.status == payment.BillStatus.Pending;
    require e.msg.sender != bill.buyer;
    
    confirmBill@withrevert(e, billId);
    assert lastReverted, "confirmBill must revert for non-buyer";
}

// ── Amount Conservation ────────────────────────────────────────────────────
rule amountConservation(method f, mathint billId) {
    env e;
    payment.Bill billBefore = getBill(billId);
    require billBefore.billId != 0;
    
    uint256 billAmount = billBefore.amount;
    
    calldataarg args;
    f(e, args);
    
    payment.Bill billAfter = getBill(billId);
    
    assert billAfter.amount == billAmount,
        "Bill amount must not change during lifecycle";
}

// ── Seller Bond Calculation ───────────────────────────────────────────────
rule sellerBondBounded(mathint amount) {
    require amount > 0;
    require amount <= to_mathint(max_uint256) / 10000;
    
    mathint expectedBond = amount * to_mathint(sellerBondBps()) / to_mathint(BPS_DENOMINATOR());
    assert expectedBond <= amount, "Seller bond must not exceed amount";
}

// ── Constructor Validation ────────────────────────────────────────────────
rule constructorValidatesInputs() {
    assert owner() != 0, "Owner must be set";
    assert arbitrator() != 0, "Arbitrator must be set";
    assert sellerBondBps() <= BPS_DENOMINATOR(), "Bond ratio must be <= 100%";
}

// ── Lock/Unlock Symmetry ──────────────────────────────────────────────────
rule lockUnlockSymmetry(address token, uint256 amount) {
    env e;
    require amount > 0;
    require token != 0;
    
    payment.AccountState stateBefore = getAccountState(e.msg.sender, token);
    require stateBefore.active >= amount;
    
    lockFunds(e, token, amount);
    unlockFunds(e, token, amount);
    
    payment.AccountState stateAfter = getAccountState(e.msg.sender, token);
    assert stateAfter.locked == stateBefore.locked, "Lock/unlock should restore locked";
    assert stateAfter.active == stateBefore.active, "Lock/unlock should restore active";
}
