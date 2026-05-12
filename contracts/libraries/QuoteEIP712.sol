// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {QuoteTypes} from "./QuoteTypes.sol";

library QuoteEIP712 {
    bytes32 internal constant QUOTE_TYPEHASH = keccak256(
        "Quote(bytes32 quoteId,address payer,address payee,address token,uint256 amount,uint256 nonce,uint256 deadline,bytes32 scopeHash)"
    );

    function hashQuote(QuoteTypes.Quote memory q) internal pure returns (bytes32) {
        return keccak256(
            abi.encode(QUOTE_TYPEHASH, q.quoteId, q.payer, q.payee, q.token, q.amount, q.nonce, q.deadline, q.scopeHash)
        );
    }
}
