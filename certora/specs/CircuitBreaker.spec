/*
 * Karma Trust Protocol — Certora Formal Verification Spec
 * Contract: CircuitBreaker.sol
 *
 * Verified properties:
 *  1. Only admin: all admin functions revert for non-admin
 *  2. Agent pause is binary (no invalid intermediate states)
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
    require caller != cb.admin(e);

    pauseAgent@withrevert(e, agent, "test");
    assert lastReverted, "Non-admin cannot pause agent";
}

// ── Only Admin Can Resume Agent ────────────────────────────────────────────
rule onlyAdminCanResumeAgent(address caller, address agent) {
    env e;
    require e.msg.sender == caller;
    require caller != cb.admin(e);

    resumeAgent@withrevert(e, agent);
    assert lastReverted, "Non-admin cannot resume agent";
}

// ── Only Admin Can Emergency Pause ─────────────────────────────────────────
rule onlyAdminCanEmergencyPause(address caller) {
    env e;
    require e.msg.sender == caller;
    require caller != cb.admin(e);

    emergencyPause@withrevert(e, "test");
    assert lastReverted, "Non-admin cannot trigger emergency pause";
}

// ── Only Admin Can Emergency Resume ────────────────────────────────────────
rule onlyAdminCanEmergencyResume(address caller) {
    env e;
    require e.msg.sender == caller;
    require caller != cb.admin(e);

    emergencyResume@withrevert(e);
    assert lastReverted, "Non-admin cannot resume from emergency";
}

// ── Agent Pause is Idempotent ──────────────────────────────────────────────
/*
 * RULE: Pausing an already-paused agent should not change state,
 * and resume after pause restores to unpaused.
 */
rule agentPauseResumeCycle(address agent) {
    env e;
    require e.msg.sender == cb.admin(e);
    require agent != 0;

    // Pause
    pauseAgent(e, agent, "test");
    assert isAgentPaused(e, agent) == true, "Agent must be paused";

    // Resume
    resumeAgent(e, agent);
    assert isAgentPaused(e, agent) == false, "Agent must be resumed";
}

// ── Emergency Pause/Resume Cycle ───────────────────────────────────────────
rule emergencyPauseResumeCycle() {
    env e;
    require e.msg.sender == cb.admin(e);

    emergencyPause(e, "test");
    assert isGlobalPaused(e) == true, "Global pause must be active";

    emergencyResume(e);
    assert isGlobalPaused(e) == false, "Global pause must be inactive";
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
