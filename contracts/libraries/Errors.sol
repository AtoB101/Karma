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
    error InvalidToken();
    error TokenUsed();
    error CircuitBreakerActive();
    error TokenTransferFailed();
    error InvalidSignature();
    error DeadlineExpired();
    error DigestAlreadyUsed();
    error InvalidNonce();
    error TokenNotAllowed();
    error QuoteAlreadyExecuted();
    error EnginePaused();
    error InvalidBatchInput();
}
