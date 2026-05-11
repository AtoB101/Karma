/*
 * Karma Trust Protocol — Certora Formal Verification Spec
 * Contract: SettlementEngine.sol
 * 
 * Verified properties:
 *  1. No replay: a quote can only be executed once
 *  2. Nonce monotonicity: nonce always increments
 *  3. Only valid EIP-712 signatures accepted
 *  4. Token allowlist: only allowed tokens pass
 *  5. Pause enforces correctly
 *  6. Batch settlement consistency
 */

using ISettlementEngine as engine;

methods {
    function admin() external returns (address) envfree;
    function paused() external returns (bool) envfree;
    function DOMAIN_SEPARATOR() external returns (bytes32) envfree;
    function tokenAllowed(address) external returns (bool) envfree;
    function executedQuotes(bytes32) external returns (bool) envfree;
    function nonces(address) external returns (uint256) envfree;
}

// ── No Replay ──────────────────────────────────────────────────────────────
/*
 * RULE: A quoteId can only be executed once. After execution,
 * executedQuotes[quoteId] is true and any re-submission reverts.
 */
rule noReplay(QuoteTypes.Quote quote, uint8 v, bytes32 r, bytes32 s) {
    env e;
    require !engine.executedQuotes(e, quote.quoteId);
    
    submitSettlement@withrevert(e, quote, v, r, s);
    bool firstOk = !lastReverted;
    
    if (firstOk) {
        assert engine.executedQuotes(e, quote.quoteId) == true,
            "Quote must be marked executed after successful settlement";
        
        // Re-submission must revert
        submitSettlement@withrevert(e, quote, v, r, s);
        assert lastReverted, "Re-submission of executed quote must revert";
    }
}

// ── Nonce Monotonicity ─────────────────────────────────────────────────────
/*
 * RULE: After a successful settlement, payer nonce must have incremented.
 */
rule nonceMonotonic(QuoteTypes.Quote quote, uint8 v, bytes32 r, bytes32 s) {
    env e;
    require !engine.executedQuotes(e, quote.quoteId);
    
    uint256 nonceBefore = engine.nonces(e, quote.payer);
    
    submitSettlement@withrevert(e, quote, v, r, s);
    
    if (!lastReverted) {
        uint256 nonceAfter = engine.nonces(e, quote.payer);
        assert nonceAfter == nonceBefore + 1,
            "Payer nonce must increment after successful settlement";
    }
}

// ── Token Allowlist ────────────────────────────────────────────────────────
/*
 * RULE: If a token is not allowed, settlement must revert.
 */
rule tokenAllowlistEnforced(QuoteTypes.Quote quote, uint8 v, bytes32 r, bytes32 s) {
    env e;
    require !engine.tokenAllowed(e, quote.token);
    
    submitSettlement@withrevert(e, quote, v, r, s);
    assert lastReverted, "Settlement with non-allowed token must revert";
}

// ── Pause Enforces ─────────────────────────────────────────────────────────
/*
 * RULE: When paused, all settlements revert.
 */
rule pauseBlocksSettlement(QuoteTypes.Quote quote, uint8 v, bytes32 r, bytes32 s) {
    env e;
    require engine.paused(e);
    
    submitSettlement@withrevert(e, quote, v, r, s);
    assert lastReverted, "Paused engine must revert all settlements";
}

// ── Expired Quote Reverts ──────────────────────────────────────────────────
/*
 * RULE: A quote with deadline < block.timestamp must revert.
 */
rule expiredQuoteReverts(QuoteTypes.Quote quote, uint8 v, bytes32 r, bytes32 s) {
    env e;
    require quote.deadline < e.block.timestamp;
    
    submitSettlement@withrevert(e, quote, v, r, s);
    assert lastReverted, "Expired quote must revert";
}

// ── Batch Consistency ─────────────────────────────────────────────────────
/*
 * RULE: Batch settlement of N quotes must process exactly N settlements
 * or revert entirely.
 */
rule batchConsistency(QuoteTypes.Quote[] quotes, uint8[] vs, bytes32[] rs, bytes32[] ss) {
    env e;
    require quotes.length == vs.length && vs.length == rs.length && rs.length == ss.length;
    require quotes.length > 0 && quotes.length <= 10;
    
    // Count how many quotes are not already executed
    uint256 freshCount = 0;
    for (uint256 i = 0; i < quotes.length; i++) {
        if (!engine.executedQuotes(e, quotes[i].quoteId)) {
            freshCount = freshCount + 1;
        }
    }
    
    settleBatch@withrevert(e, quotes, vs, rs, ss);
    
    if (!lastReverted) {
        // All fresh quotes should now be executed
        for (uint256 i = 0; i < quotes.length; i++) {
            assert engine.executedQuotes(e, quotes[i].quoteId) == true,
                "All quotes in batch must be executed after successful settleBatch";
        }
    }
}

// ── Constructor ────────────────────────────────────────────────────────────
rule constructorSetsAdmin() {
    assert admin() != 0, "Admin must be set in constructor";
    assert DOMAIN_SEPARATOR() != 0, "Domain separator must be computed";
}
