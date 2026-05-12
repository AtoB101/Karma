// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AuthTokenManager} from "../../core/AuthTokenManager.sol";
import {Types} from "../../libraries/Types.sol";

abstract contract AuthTestHelper is Test {
    function issueAndSignAuth(
        AuthTokenManager auth,
        uint256 signerPk,
        address signer,
        Types.OperationType opType,
        uint256 amount
    ) internal returns (bytes32 tokenId, uint256 deadline, uint8 v, bytes32 r, bytes32 s) {
        vm.prank(signer);
        tokenId = auth.issueAuthToken(signer, opType, amount, 1 days);
        deadline = block.timestamp + 1 hours;
        bytes32 digest = auth.getAuthDigest(tokenId, signer, opType, amount, deadline);
        (v, r, s) = vm.sign(signerPk, digest);
    }
}
