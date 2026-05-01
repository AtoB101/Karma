// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

library EIP712Auth {
    bytes32 internal constant AUTH_TYPEHASH =
        keccak256("Auth(bytes32 tokenId,address agent,uint8 opType,uint256 amount,uint256 nonce,uint256 deadline)");

    function hashAuth(
        bytes32 tokenId,
        address agent,
        uint8 opType,
        uint256 amount,
        uint256 nonce,
        uint256 deadline
    ) internal pure returns (bytes32) {
        return keccak256(abi.encode(AUTH_TYPEHASH, tokenId, agent, opType, amount, nonce, deadline));
    }
}
