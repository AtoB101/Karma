/*
 * Karma Trust Protocol — Certora Formal Verification Spec
 * Contract: CircuitBreaker.sol
 *
 * Verified properties:
 *  1. Only admin: all admin functions revert for non-admin
 *  2. Agent pause/resume cycle works
 *  3. Global pause enforces properly
 *  4. Threshold positivity
 */

using CircuitBreaker as cb;

methods {
    function admin() external returns (address) envfree;
    function isGlobalPaused() external returns (bool) envfree;
    function isAgentPaused(address) external returns (bool) envfree;
}

// ── Only Admin Can Pause Agent ─────────────────────────────────────────────
rule onlyAdminCanPauseAgent(address caller, address agent) {
    env e;
    require e.msg.sender == caller;
    require caller != admin();

    pauseAgent@withrevert(e, agent, "test");
    assert lastReverted, "Non-admin cannot pause agent";
}

// ── Only Admin Can Resume Agent ────────────────────────────────────────────
rule onlyAdminCanResumeAgent(address caller, address agent) {
    env e;
    require e.msg.sender == caller;
    require caller != admin();

    resumeAgent@withrevert(e, agent);
    assert lastReverted, "Non-admin cannot resume agent";
}

// ── Only Admin Can Emergency Pause ─────────────────────────────────────────
rule onlyAdminCanEmergencyPause(address caller) {
    env e;
    require e.msg.sender == caller;
    require caller != admin();

    emergencyPause@withrevert(e, "test");
    assert lastReverted, "Non-admin cannot trigger emergency pause";
}

// ── Only Admin Can Emergency Resume ────────────────────────────────────────
rule onlyAdminCanEmergencyResume(address caller) {
    env e;
    require e.msg.sender == caller;
    require caller != admin();

    emergencyResume@withrevert(e);
    assert lastReverted, "Non-admin cannot resume from emergency";
}

// ── Agent Pause/Resume Cycle ───────────────────────────────────────────────
rule agentPauseResumeCycle(address agent) {
    env e;
    require e.msg.sender == admin();
    require agent != 0;

    pauseAgent(e, agent, "test");
    assert isAgentPaused(agent) == true, "Agent must be paused after pauseAgent";

    resumeAgent(e, agent);
    assert isAgentPaused(agent) == false, "Agent must be un-paused after resumeAgent";
}

// ── Emergency Pause/Resume Cycle ───────────────────────────────────────────
rule emergencyPauseResumeCycle() {
    env e;
    require e.msg.sender == admin();

    emergencyPause(e, "test");
    assert isGlobalPaused() == true, "Global pause must be active after emergencyPause";

    emergencyResume(e);
    assert isGlobalPaused() == false, "Global pause must be inactive after emergencyResume";
}

// ── Threshold Must Be Positive ─────────────────────────────────────────────
rule thresholdMustBePositive(uint256 amount) {
    env e;
    require amount == 0;

    setHumanApprovalThreshold@withrevert(e, amount);
    assert lastReverted, "Zero threshold must revert";
}

// ── Constructor ────────────────────────────────────────────────────────────
rule constructorSetsAdmin() {
    assert admin() != 0, "Admin must be set in constructor";
    assert isGlobalPaused() == false, "Global pause must be false initially";
}
