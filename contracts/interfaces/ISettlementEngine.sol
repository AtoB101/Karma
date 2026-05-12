// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {QuoteTypes} from "../libraries/QuoteTypes.sol";

interface ISettlementEngine {
    function submitSettlement(QuoteTypes.Quote calldata quote, uint8 v, bytes32 r, bytes32 s) external;
    function settleBatch(QuoteTypes.Quote[] calldata quotes, uint8[] calldata vs, bytes32[] calldata rs, bytes32[] calldata ss)
        external;
    function getQuoteDigest(QuoteTypes.Quote calldata quote) external view returns (bytes32);
    function setTokenAllowed(address token, bool allowed) external;
    function pause() external;
    function unpause() external;
    function nonces(address payer) external view returns (uint256);
    function executedQuotes(bytes32 quoteId) external view returns (bool);
}
