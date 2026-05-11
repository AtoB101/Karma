/*
 * Karma Trust Protocol — Certora Formal Verification Spec
 * Contract: SettlementEngine.sol
 */

using SettlementEngine as engine;

methods {
    function admin() external returns (address) envfree;
    function paused() external returns (bool) envfree;
    function DOMAIN_SEPARATOR() external returns (bytes32) envfree;
    function tokenAllowed(address) external returns (bool) envfree;
    function executedQuotes(bytes32) external returns (bool) envfree;
    function nonces(address) external returns (uint256) envfree;
}

// ── No Replay ──────────────────────────────────────────────────────────────
rule noReplay(QuoteTypes.Quote quote, uint8 v, bytes32 r, bytes32 s) {
    env e;
    require executedQuotes(quote.quoteId) == false;
    
    submitSettlement@withrevert(e, quote, v, r, s);
    bool firstOk = !lastReverted;
    
    if (firstOk) {
        assert executedQuotes(quote.quoteId) == true,
            "Quote must be marked executed after successful settlement";
        submitSettlement@withrevert(e, quote, v, r, s);
        assert lastReverted, "Re-submission of executed quote must revert";
    }
}

// ── Nonce Monotonicity ─────────────────────────────────────────────────────
rule nonceMonotonic(QuoteTypes.Quote quote, uint8 v, bytes32 r, bytes32 s) {
    env e;
    require executedQuotes(quote.quoteId) == false;
    
    uint256 nonceBefore = nonces(quote.payer);
    
    submitSettlement@withrevert(e, quote, v, r, s);
    
    if (!lastReverted) {
        uint256 nonceAfter = nonces(quote.payer);
        assert nonceAfter == nonceBefore + 1,
            "Payer nonce must increment after successful settlement";
    }
}

// ── Token Allowlist ────────────────────────────────────────────────────────
rule tokenAllowlistEnforced(QuoteTypes.Quote quote, uint8 v, bytes32 r, bytes32 s) {
    env e;
    require tokenAllowed(quote.token) == false;
    
    submitSettlement@withrevert(e, quote, v, r, s);
    assert lastReverted, "Settlement with non-allowed token must revert";
}

// ── Pause Enforces ─────────────────────────────────────────────────────────
rule pauseBlocksSettlement(QuoteTypes.Quote quote, uint8 v, bytes32 r, bytes32 s) {
    env e;
    require paused() == true;
    
    submitSettlement@withrevert(e, quote, v, r, s);
    assert lastReverted, "Paused engine must revert all settlements";
}

// ── Expired Quote Reverts ──────────────────────────────────────────────────
rule expiredQuoteReverts(QuoteTypes.Quote quote, uint8 v, bytes32 r, bytes32 s) {
    env e;
    require quote.deadline < e.block.timestamp;
    
    submitSettlement@withrevert(e, quote, v, r, s);
    assert lastReverted, "Expired quote must revert";
}

// ── Constructor ────────────────────────────────────────────────────────────
rule constructorSetsAdmin() {
    assert admin() != 0, "Admin must be set in constructor";
    assert DOMAIN_SEPARATOR() != 0, "Domain separator must be computed";
}
