// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

library QuoteTypes {
    struct Quote {
        bytes32 quoteId;
        address payer;
        address payee;
        address token;
        uint256 amount;
        uint256 nonce;
        uint256 deadline;
        bytes32 scopeHash;
    }
}
