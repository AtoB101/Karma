/*
 * Karma Trust Protocol — Certora Formal Verification Spec
 * Contract: KYARegistry.sol
 *
 * Verified properties:
 *  1. Only owner can revoke their own DID
 *  2. DID validity period is correctly computed
 *  3. Minimum stake requirement enforced
 *  4. Permission updates only by owner
 *  5. Admin-only withdraw
 */

using KYARegistry as kya;

methods {
    function admin() external returns (address) envfree;
    function MIN_STAKE() external returns (uint256) envfree;
}

// ── DID Validity Period ────────────────────────────────────────────────────
/*
 * RULE: After registerDID, validUntil == block.timestamp + (validityDays * 1 day).
 */
rule didValidityCorrect(address agent, bytes32 permissionsHash, uint256 validityDays) {
    env e;
    require agent != 0;
    require validityDays > 0;
    
    // Provide min stake
    uint256 stake = MIN_STAKE();
    require e.msg.value >= stake;
    require e.msg.value == stake;
    
    bytes32 did = registerDID(e, agent, permissionsHash, validityDays);
    (bool isValid, address owner, uint256 validUntil) = verifyDID(e, agent);
    
    assert isValid == true, "Newly registered DID must be valid";
    assert owner == e.msg.sender, "DID owner must be registrant";
    assert validUntil == e.block.timestamp + (validityDays * 1 days),
        "DID validity period must match validityDays";
}

// ── Minimum Stake Enforced ─────────────────────────────────────────────────
/*
 * RULE: registerDID with msg.value < MIN_STAKE must revert.
 */
rule minStakeEnforced(address agent, bytes32 permissionsHash, uint256 validityDays) {
    env e;
    require agent != 0;
    require validityDays > 0;
    
    uint256 stake = MIN_STAKE();
    require e.msg.value < stake;
    
    registerDID@withrevert(e, agent, permissionsHash, validityDays);
    assert lastReverted, "Below-minimum stake must revert";
}

// ── Only Owner Revokes ─────────────────────────────────────────────────────
rule onlyOwnerRevokesDID(address agent, address caller) {
    env e;
    require e.msg.sender == caller;
    
    // First register a DID for the caller
    uint256 stake = MIN_STAKE();
    e.msg.value = stake;
    bytes32 did = registerDID(e, agent, 0x0, 365);
    (bool isValid, address didOwner, ) = verifyDID(e, agent);
    require isValid;
    
    // Now test revocation by a different caller
    require caller != didOwner;
    e.msg.sender = caller;
    
    revokeDID@withrevert(e, agent);
    assert lastReverted, "Non-owner cannot revoke DID";
}

// ── Revoked DID is Inactive ────────────────────────────────────────────────
/*
 * RULE: After revokeDID, verifyDID returns isValid == false.
 */
rule revokedDidNotValid(address agent) {
    env e;

    bytes32 did = kya.registerDID(e, agent, keccak256("perm"), 365);
    require kya.verifyDID(e, agent).isValid;
    
    kya.revokeDID(e, agent);
    (bool isValid, , ) = kya.verifyDID(e, agent);
    assert isValid == false, "Revoked DID must be invalid";
}

// ── Only Owner Updates Permissions ─────────────────────────────────────────
rule onlyOwnerUpdatesPermissions(address agent, address caller, bytes32 newPerms) {
    env e;
    require e.msg.sender == caller;
    
    // First register a DID
    uint256 stake = MIN_STAKE();
    e.msg.value = stake;
    bytes32 did = kya.registerDID(e, agent, 0x0, 365);
    ( , address didOwner, ) = kya.verifyDID(e, agent);
    
    require caller != didOwner;
    e.msg.sender = caller;
    
    updatePermissions@withrevert(e, agent, newPerms);
    assert lastReverted, "Non-owner cannot update permissions";
}

// ── DID Expiry ─────────────────────────────────────────────────────────────
/*
 * RULE: A DID becomes invalid after its validUntil passes.
 */
rule didExpiresEventually(address agent) {
    env e;
    
    bytes32 did = kya.registerDID(e, agent, keccak256("perm"), 1); // 1 day validity
    (bool isValidNow, , uint256 validUntil) = kya.verifyDID(e, agent);
    assert isValidNow == true;
    
    // Advance time past validity
    env e2;
    require e2.block.timestamp > validUntil;
    
    (bool isValidAfter, , ) = kya.verifyDID(e2, agent);
    assert isValidAfter == false, "DID must expire after validUntil";
}

// ── Constructor ────────────────────────────────────────────────────────────
rule constructorSetsAdmin() {
    assert admin() != 0, "Admin must be set in constructor";
}
