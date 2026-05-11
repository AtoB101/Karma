// SPDX-License-Identifier: MIT
/*
 * Karma Trust Protocol — Certora (CVL2)
 * Contract: KYARegistry.sol
 *
 * Properties covered:
 *  1. Only DID owner can revoke an active DID (non-owner reverts)
 *  2. After registerDID, validUntil matches validityDays * 1 days
 *  3. Minimum stake enforced (below MIN_STAKE reverts)
 *  4. Non-owner cannot update permissions
 *  5. Only admin can withdraw stuck ETH
 */
methods {
    function admin() external returns (address) envfree;
    function MIN_STAKE() external returns (uint256) envfree;
    // Payable on-chain; CVL methods entry omits `payable` keyword for broader Prover compatibility.
    function registerDID(address, bytes32, uint256) external returns (bytes32) => NONDET;
    function verifyDID(address) external returns (bool, address, uint256) envfree;
    function revokeDID(address) external => NONDET;
    function updatePermissions(address, bytes32) external => NONDET;
    function withdrawStuckETH(address, uint256) external => NONDET;
}

// ── DID validity after registration ───────────────────────────────────────
rule didValidityCorrect(address agent, bytes32 permissionsHash, uint256 validityDays) {
    env e;
    require agent != 0;
    require validityDays > 0;

    uint256 stake = MIN_STAKE();
    require e.msg.value == stake;

    registerDID(e, agent, permissionsHash, validityDays);

    bool isValid;
    address owner;
    uint256 validUntil;
    isValid, owner, validUntil = verifyDID(e, agent);

    assert isValid == true, "Newly registered DID must be valid";
    assert owner == e.msg.sender, "DID owner must be registrant";
    assert validUntil == e.block.timestamp + validityDays * 86400,
        "DID validity period must match validityDays in seconds";
}

// ── Minimum stake enforced ──────────────────────────────────────────────────
rule minStakeEnforced(address agent, bytes32 permissionsHash, uint256 validityDays) {
    env e;
    require agent != 0;
    require validityDays > 0;

    uint256 stake = MIN_STAKE();
    require e.msg.value < stake;

    registerDID@withrevert(e, agent, permissionsHash, validityDays);
    assert lastReverted, "Below-minimum stake must revert";
}

// ── Only owner can revoke ───────────────────────────────────────────────────
rule onlyOwnerRevokesDID(address agent, address caller) {
    env e;
    require e.msg.sender == caller;

    bool isValid;
    address didOwner;
    uint256 vuntil;
    isValid, didOwner, vuntil = verifyDID(e, agent);
    require isValid == true;
    require didOwner != 0;
    require caller != didOwner;

    revokeDID@withrevert(e, agent);
    assert lastReverted, "Non-owner cannot revoke DID";
}

// ── Revoked DID is inactive ─────────────────────────────────────────────────
rule revokedDidNotValid(address agent) {
    env e;
    require agent != 0;

    uint256 stake = MIN_STAKE();
    require e.msg.value == stake;

    registerDID(e, agent, keccak256("perm"), 365);

    bool isValidBefore;
    address ownerBefore;
    uint256 vuntilBefore;
    isValidBefore, ownerBefore, vuntilBefore = verifyDID(e, agent);
    require isValidBefore == true;

    revokeDID(e, agent);

    bool isValidAfter;
    address ownerAfter;
    uint256 vuntilAfter;
    isValidAfter, ownerAfter, vuntilAfter = verifyDID(e, agent);
    assert isValidAfter == false, "Revoked DID must be invalid";
}

// ── Only owner updates permissions ──────────────────────────────────────────
rule onlyOwnerUpdatesPermissions(address agent, address caller, bytes32 newPerms) {
    env e;
    require e.msg.sender == caller;

    bool isValid;
    address didOwner;
    uint256 vuntil;
    isValid, didOwner, vuntil = verifyDID(e, agent);
    require didOwner != 0;
    require caller != didOwner;

    updatePermissions@withrevert(e, agent, newPerms);
    assert lastReverted, "Non-owner cannot update permissions";
}

// ── One-day validity window stored ─────────────────────────────────────────
rule didOneDayWindowStored(address agent) {
    env e;
    require agent != 0;

    uint256 stake = MIN_STAKE();
    require e.msg.value == stake;

    registerDID(e, agent, keccak256("perm"), 1);

    bool isValidNow;
    address ownerNow;
    uint256 validUntil;
    isValidNow, ownerNow, validUntil = verifyDID(e, agent);
    assert isValidNow == true;
    assert validUntil == e.block.timestamp + 86400,
        "1-day registration must set validUntil to now + 86400 seconds";
}

// ── Only admin withdraws ETH ────────────────────────────────────────────────
rule onlyAdminWithdraw(address caller, address to, uint256 amount) {
    env e;
    require e.msg.sender == caller;
    require caller != admin();
    require to != 0;
    require amount > 0;

    withdrawStuckETH@withrevert(e, to, amount);
    assert lastReverted, "Non-admin cannot withdraw stuck ETH";
}

// ── Constructor / initial admin ─────────────────────────────────────────────
rule constructorSetsAdmin() {
    assert admin() != 0, "Admin must be set in constructor";
}
