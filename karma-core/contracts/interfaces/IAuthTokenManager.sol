// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Types} from "../libraries/Types.sol";

interface IAuthTokenManager {
    function issueAuthToken(
        address agent,
        Types.OperationType opType,
        uint256 maxAmount,
        uint256 validitySeconds
    ) external returns (bytes32 tokenId);

    function revokeAuthToken(bytes32 tokenId) external;
    function validateAuth(bytes32 tokenId, address agent, Types.OperationType opType, uint256 amount) external view returns (bool);
    function getAuthDigest(
        bytes32 tokenId,
        address agent,
        Types.OperationType opType,
        uint256 amount,
        uint256 deadline
    ) external view returns (bytes32);
    function consumeAuth(
        bytes32 tokenId,
        address agent,
        Types.OperationType opType,
        uint256 amount,
        uint256 deadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external returns (bool);
}
