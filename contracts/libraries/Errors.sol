// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

library Errors {
    error Unauthorized();
    error InvalidAddress();
    error InvalidAmount();
    error InvalidState();
    error NotFound();
    error DIDNotActive();
    error DIDExpired();
    error InsufficientMappingBalance();
    error PendingAmountNotZero();
    error InvalidToken();
    error TokenUsed();
    error TokenExpired();
    error CircuitBreakerActive();
    error DeprecatedEntryPoint();
    error TokenTransferFailed();
    error InvalidSignature();
    error DeadlineExpired();
    error DigestAlreadyUsed();
    error InvalidNonce();
    error TokenNotAllowed();
    error QuoteAlreadyExecuted();
    error EnginePaused();
}
