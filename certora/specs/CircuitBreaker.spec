// SPDX-License-Identifier: MIT
/*
 * Karma Trust Protocol — Certora (CVL2)
 * Contract: CircuitBreaker.sol
 *
 * Properties:
 *  - pauseAgent / resumeAgent / emergencyPause / emergencyResume: admin-only
 *  - setHumanApprovalThreshold: any caller may set own threshold; amount==0 reverts
 *  - Pause / resume cycles restore flags
 */
methods {
    function admin() external returns (address) envfree;
    function isGlobalPaused() external returns (bool) envfree;
    function isAgentPaused(address) external returns (bool) envfree;
    // State-changing methods are only invoked from CVL in this spec; Certora does not apply
    // summaries to CVL→contract calls — omit them here (avoids DISPATCHER / “no effect” issues).
}

// ── Admin-only: agent pause / resume ───────────────────────────────────────
rule onlyAdminCanPauseAgent(address caller, address agent) {
    env e;
    require e.msg.sender == caller;
    require caller != admin();
    pauseAgent@withrevert(e, agent, "test");
    assert lastReverted, "Non-admin cannot pause agent";
}

rule onlyAdminCanResumeAgent(address caller, address agent) {
    env e;
    require e.msg.sender == caller;
    require caller != admin();
    resumeAgent@withrevert(e, agent);
    assert lastReverted, "Non-admin cannot resume agent";
}

// ── Admin-only: global emergency controls ───────────────────────────────────
rule onlyAdminCanEmergencyPause(address caller) {
    env e;
    require e.msg.sender == caller;
    require caller != admin();
    emergencyPause@withrevert(e, "test");
    assert lastReverted, "Non-admin cannot trigger emergency pause";
}

rule onlyAdminCanEmergencyResume(address caller) {
    env e;
    require e.msg.sender == caller;
    require caller != admin();
    emergencyResume@withrevert(e);
    assert lastReverted, "Non-admin cannot resume from emergency";
}

// ── Agent pause / resume cycle (admin) ─────────────────────────────────────
rule agentPauseResumeCycle(address agent) {
    env e;
    require e.msg.sender == admin();
    require agent != 0;
    pauseAgent(e, agent, "test");
    assert isAgentPaused(agent) == true, "Agent must be paused after pauseAgent";
    resumeAgent(e, agent);
    assert isAgentPaused(agent) == false, "Agent must be unpaused after resumeAgent";
}

// ── Global emergency pause / resume (admin) ─────────────────────────────────
rule emergencyPauseResumeCycle() {
    env e;
    require e.msg.sender == admin();
    emergencyPause(e, "test");
    assert isGlobalPaused() == true, "Global pause must be active after emergencyPause";
    emergencyResume(e);
    assert isGlobalPaused() == false, "Global pause must be inactive after emergencyResume";
}

// ── Threshold must be positive (any caller; not admin-gated in contract) ───
rule thresholdMustBePositive(uint256 amount) {
    env e;
    require amount == 0;
    setHumanApprovalThreshold@withrevert(e, amount);
    assert lastReverted, "Zero threshold must revert";
}

// ── Initial admin ──────────────────────────────────────────────────────────
rule constructorSetsAdmin() {
    assert admin() != 0, "Admin must be set in constructor";
    assert isGlobalPaused() == false, "Global pause must be false initially";
}
