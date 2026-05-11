/*
 * Karma Trust Protocol — Certora Formal Verification Spec
 * Contract: AuthTokenManager.sol
 */

using AuthTokenManager as auth;

methods {
    function DOMAIN_SEPARATOR() external returns (bytes32) envfree;
    // authTokens is a public mapping; its auto-generated getter returns
    // decomposed struct fields: (bytes32,address,address,OperationType,uint256,uint256,bool,uint256)
    function authTokens(bytes32) external returns (bytes32, address, address, uint8, uint256, uint256, bool, uint256) envfree;
}

// ── Token Single Use ───────────────────────────────────────────────────────
rule tokenSingleUse(bytes32 tokenId, address agent, uint8 opTypeRaw, uint256 amount, uint256 deadline, uint8 v, bytes32 r, bytes32 s) {
    env e;
    
    bytes32 tid; address own; address ag; uint8 opRaw; uint256 maxAmt; uint256 vUntil; bool used; uint256 nonce;
    tid, own, ag, opRaw, maxAmt, vUntil, used, nonce = authTokens(tokenId);
    
    require own != 0;
    require used == false;
    require ag == agent;
    require opRaw == opTypeRaw;
    require amount > 0 && amount <= maxAmt;
    require deadline >= e.block.timestamp && deadline <= vUntil;

    consumeAuth@withrevert(e, tokenId, agent, opTypeRaw, amount, deadline, v, r, s);
    bool firstOk = !lastReverted;

    if (firstOk) {
        // re-read to verify used
        bytes32 tid2; address own2; address ag2; uint8 op2; uint256 ma2; uint256 vu2; bool used2; uint256 no2;
        tid2, own2, ag2, op2, ma2, vu2, used2, no2 = authTokens(tokenId);
        assert used2 == true, "Token must be marked used after consumption";

        // Second consumption must revert
        consumeAuth@withrevert(e, tokenId, agent, opTypeRaw, amount, deadline, v, r, s);
        assert lastReverted, "Consuming used token must revert";
    }
}

// ── Expiry Enforcement ─────────────────────────────────────────────────────
rule expiredTokenReverts(bytes32 tokenId, address agent, uint8 opTypeRaw, uint256 amount, uint256 deadline, uint8 v, bytes32 r, bytes32 s) {
    env e;
    
    bytes32 tid; address own; address ag; uint8 opRaw; uint256 maxAmt; uint256 vUntil; bool used; uint256 nonce;
    tid, own, ag, opRaw, maxAmt, vUntil, used, nonce = authTokens(tokenId);
    
    require own != 0;
    require used == false;
    require e.block.timestamp > vUntil;

    consumeAuth@withrevert(e, tokenId, agent, opTypeRaw, amount, deadline, v, r, s);
    assert lastReverted, "Expired token must revert on consumption";
}

// ── Only Owner Revokes ─────────────────────────────────────────────────────
rule onlyOwnerRevokes(bytes32 tokenId, address caller) {
    env e;
    require e.msg.sender == caller;
    
    bytes32 tid; address own; address ag; uint8 opRaw; uint256 maxAmt; uint256 vUntil; bool used; uint256 nonce;
    tid, own, ag, opRaw, maxAmt, vUntil, used, nonce = authTokens(tokenId);
    
    require own != 0;
    require caller != own;

    revokeAuthToken@withrevert(e, tokenId);
    assert lastReverted, "Non-owner cannot revoke token";
}

// ── Issue Creates Valid Token ──────────────────────────────────────────────
rule issueCreatesValidToken(address agent, uint8 opTypeRaw, uint256 maxAmount, uint256 validitySeconds) {
    env e;
    require agent != 0;
    require maxAmount > 0;
    require validitySeconds > 0;

    bytes32 tokenId = issueAuthToken(e, agent, opTypeRaw, maxAmount, validitySeconds);
    
    bytes32 tid; address own; address ag; uint8 opRaw; uint256 maxAmt; uint256 vUntil; bool used; uint256 nonce;
    tid, own, ag, opRaw, maxAmt, vUntil, used, nonce = authTokens(tokenId);

    assert own == e.msg.sender, "Token owner must be issuer";
    assert ag == agent, "Token agent must match";
    assert opRaw == opTypeRaw, "Token opType must match";
    assert maxAmt == maxAmount, "Token maxAmount must match";
    assert used == false, "New token must be unused";
    assert vUntil == e.block.timestamp + validitySeconds, "Token validity must match";
}

// ── Validation Rejects Wrong Agent ─────────────────────────────────────────
rule validateRejectsWrongAgent(bytes32 tokenId, address wrongAgent, uint8 opTypeRaw, uint256 amount) {
    env e;

    bytes32 tid; address own; address ag; uint8 opRaw; uint256 maxAmt; uint256 vUntil; bool used; uint256 nonce;
    tid, own, ag, opRaw, maxAmt, vUntil, used, nonce = authTokens(tokenId);
    
    require own != 0;
    require ag != wrongAgent;

    bool result = validateAuth(e, tokenId, wrongAgent, opTypeRaw, amount);
    assert result == false, "Validate must reject wrong agent";
}

// ── Validation Rejects Used Token ──────────────────────────────────────────
rule validateRejectsUsedToken(bytes32 tokenId, address agent, uint8 opTypeRaw, uint256 amount) {
    env e;

    bytes32 tid; address own; address ag; uint8 opRaw; uint256 maxAmt; uint256 vUntil; bool used; uint256 nonce;
    tid, own, ag, opRaw, maxAmt, vUntil, used, nonce = authTokens(tokenId);
    
    require own != 0;
    require used == true;

    bool result = validateAuth(e, tokenId, agent, opTypeRaw, amount);
    assert result == false, "Validate must reject used token";
}

// ── Constructor ────────────────────────────────────────────────────────────
rule constructorSetsDomainSeparator() {
    assert DOMAIN_SEPARATOR() != 0, "Domain separator must be set";
}
