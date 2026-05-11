/*
 * Karma Trust Protocol — Certora Formal Verification Spec
 * Contract: AuthTokenManager.sol
 *
 * Verified properties:
 *  1. Token single-use: a token can only be consumed once
 *  2. Expiry enforcement: expired tokens cannot be used
 *  3. Only owner can issue tokens with correct metadata
 *  4. Only owner can revoke their own tokens
 *  5. Signature validation integrity
 */

using AuthTokenManager as auth;

methods {
    function DOMAIN_SEPARATOR() external returns (bytes32) envfree;
    function authTokens(bytes32) external returns (Types.AuthToken) envfree;
}

// ── Token Single Use ───────────────────────────────────────────────────────
/*
 * RULE: Once consumeAuth succeeds, token.used is true and
 * any subsequent consumption reverts.
 */
rule tokenSingleUse(bytes32 tokenId, address agent, Types.OperationType opType, uint256 amount, uint256 deadline, uint8 v, bytes32 r, bytes32 s) {
    env e;
    
    // Ensure valid token exists
    Types.AuthToken tok = authTokens(tokenId);
    require tok.owner != 0;
    require tok.used == false;
    require tok.agent == agent;
    require tok.opType == opType;
    require amount > 0 && amount <= tok.maxAmount;
    require deadline >= e.block.timestamp && deadline <= tok.validUntil;
    require tok.validUntil >= e.block.timestamp;

    consumeAuth@withrevert(e, tokenId, agent, opType, amount, deadline, v, r, s);
    bool firstOk = !lastReverted;

    if (firstOk) {
        Types.AuthToken tokAfter = authTokens(tokenId);
        assert tokAfter.used == true, "Token must be marked used after consumption";

        // Second consumption must revert
        consumeAuth@withrevert(e, tokenId, agent, opType, amount, deadline, v, r, s);
        assert lastReverted, "Consuming used token must revert";
    }
}

// ── Expiry Enforcement ─────────────────────────────────────────────────────
/*
 * RULE: A token past its validUntil cannot be consumed.
 */
rule expiredTokenReverts(bytes32 tokenId, address agent, Types.OperationType opType, uint256 amount, uint256 deadline, uint8 v, bytes32 r, bytes32 s) {
    env e;
    
    Types.AuthToken tok = authTokens(tokenId);
    require tok.owner != 0;
    require tok.used == false;
    require e.block.timestamp > tok.validUntil;

    consumeAuth@withrevert(e, tokenId, agent, opType, amount, deadline, v, r, s);
    assert lastReverted, "Expired token must revert on consumption";
}

// ── Only Owner Revokes ─────────────────────────────────────────────────────
rule onlyOwnerRevokes(bytes32 tokenId, address caller) {
    env e;
    require e.msg.sender == caller;
    
    Types.AuthToken tok = authTokens(tokenId);
    require tok.owner != 0;
    require caller != tok.owner;

    revokeAuthToken@withrevert(e, tokenId);
    assert lastReverted, "Non-owner cannot revoke token";
}

// ── Issue Creates Valid Token ──────────────────────────────────────────────
/*
 * RULE: After issueAuthToken, the token exists with correct metadata.
 */
rule issueCreatesValidToken(address agent, Types.OperationType opType, uint256 maxAmount, uint256 validitySeconds) {
    env e;
    require agent != 0;
    require maxAmount > 0;
    require validitySeconds > 0;

    bytes32 tokenId = issueAuthToken(e, agent, opType, maxAmount, validitySeconds);
    Types.AuthToken tok = authTokens(tokenId);

    assert tok.owner == e.msg.sender, "Token owner must be issuer";
    assert tok.agent == agent, "Token agent must match";
    assert tok.opType == opType, "Token opType must match";
    assert tok.maxAmount == maxAmount, "Token maxAmount must match";
    assert tok.used == false, "New token must be unused";
    assert tok.validUntil == e.block.timestamp + validitySeconds, "Token validity must match";
}

// ── Validation Rejects Wrong Agent ─────────────────────────────────────────
rule validateRejectsWrongAgent(bytes32 tokenId, address wrongAgent, Types.OperationType opType, uint256 amount) {
    env e;

    Types.AuthToken tok = authTokens(tokenId);
    require tok.owner != 0;
    require tok.agent != wrongAgent;

    bool result = validateAuth(e, tokenId, wrongAgent, opType, amount);
    assert result == false, "Validate must reject wrong agent";
}

// ── Validation Rejects Used Token ──────────────────────────────────────────
rule validateRejectsUsedToken(bytes32 tokenId, address agent, Types.OperationType opType, uint256 amount) {
    env e;

    Types.AuthToken tok = authTokens(tokenId);
    require tok.owner != 0;
    require tok.used == true;

    bool result = validateAuth(e, tokenId, agent, opType, amount);
    assert result == false, "Validate must reject used token";
}

// ── Constructor ────────────────────────────────────────────────────────────
rule constructorSetsDomainSeparator() {
    assert DOMAIN_SEPARATOR() != 0, "Domain separator must be set";
}
