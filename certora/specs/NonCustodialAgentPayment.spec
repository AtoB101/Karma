// SPDX-License-Identifier: MIT
/*
 * Karma Trust Protocol — Certora (CVL2)
 * Contract: NonCustodialAgentPayment.sol
 *
 * Use the Solidity contract name for types (e.g. NonCustodialAgentPayment.BillStatus).
 * Do not use a `using ... as payment` alias as a *type* prefix — CVL2 rejects it.
 */
methods {
    function arbitrator() external returns (address) envfree;
    function owner() external returns (address) envfree;
    // Dispute / lockFunds paths are only exercised from CVL here — omit from methods block.
}

// ── Arbitrator-only dispute resolutions ────────────────────────────────────
rule nonArbitratorCannotResolveBuyer(address caller, uint256 billId) {
    env e;
    require e.msg.sender == caller;
    require caller != arbitrator();
    resolveDisputeBuyer@withrevert(e, billId);
    assert lastReverted, "non-arbitrator cannot resolve buyer";
}

rule nonArbitratorCannotResolveSeller(address caller, uint256 billId) {
    env e;
    require e.msg.sender == caller;
    require caller != arbitrator();
    resolveDisputeSeller@withrevert(e, billId);
    assert lastReverted, "non-arbitrator cannot resolve seller";
}

rule nonArbitratorCannotResolveSplit(address caller, uint256 billId, uint16 shareBps) {
    env e;
    require e.msg.sender == caller;
    require caller != arbitrator();
    resolveDisputeSplit@withrevert(e, billId, shareBps);
    assert lastReverted, "non-arbitrator cannot resolve split";
}

// ── lockFunds rejects zero token ───────────────────────────────────────────
rule lockFundsZeroTokenReverts(uint256 amount) {
    env e;
    require amount > 0;
    lockFunds@withrevert(e, 0, amount);
    assert lastReverted, "zero token address must revert";
}
