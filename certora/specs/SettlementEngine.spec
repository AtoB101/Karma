// SPDX-License-Identifier: MIT
/*
 * Karma Trust Protocol — Certora (CVL2)
 * Contract: SettlementEngine.sol
 *
 * Lightweight admin / domain checks. Parametric Quote settlement is left for a
 * follow-up spec once QuoteTypes wiring is stable under your Certora CLI version.
 */
methods {
    function DOMAIN_SEPARATOR() external returns (bytes32) envfree;
    function admin() external returns (address) envfree;
    function paused() external returns (bool) envfree;
    function tokenAllowed(address) external returns (bool) envfree;
    function setTokenAllowed(address, bool) external => NONDET;
    function pause() external => NONDET;
    function unpause() external => NONDET;
}

// DOMAIN_SEPARATOR is a non-zero commitment (deployment binding)
rule domainSeparatorNonZero() {
    assert DOMAIN_SEPARATOR() != to_bytes32(0), "DOMAIN_SEPARATOR must be non-zero";
}

rule nonAdminCannotPause(address caller) {
    env e;
    require e.msg.sender == caller;
    require caller != admin();
    pause@withrevert(e);
    assert lastReverted, "non-admin pause must revert";
}

rule nonAdminCannotUnpause(address caller) {
    env e;
    require e.msg.sender == caller;
    require caller != admin();
    unpause@withrevert(e);
    assert lastReverted, "non-admin unpause must revert";
}

rule nonAdminCannotSetToken(address caller, address token, bool allowed) {
    env e;
    require e.msg.sender == caller;
    require caller != admin();
    setTokenAllowed@withrevert(e, token, allowed);
    assert lastReverted, "non-admin setTokenAllowed must revert";
}

rule constructorSetsAdminAndDomain() {
    assert admin() != 0, "Admin must be set in constructor";
    assert DOMAIN_SEPARATOR() != to_bytes32(0), "Domain separator must be non-zero";
}
