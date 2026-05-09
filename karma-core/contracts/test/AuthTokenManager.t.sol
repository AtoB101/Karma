// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AuthTokenManager} from "../core/AuthTokenManager.sol";
import {Types} from "../libraries/Types.sol";
import {Errors} from "../libraries/Errors.sol";

contract AuthTokenManagerTest is Test {
    uint256 internal constant SECP256K1N =
        0xFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFFEBAAEDCE6AF48A03BBFD25E8CD0364141;
    AuthTokenManager internal manager;
    uint256 internal ownerPk = 0xA11CE;
    address internal owner;
    address internal agent = address(0xCAFE);

    function setUp() public {
        manager = new AuthTokenManager();
        owner = vm.addr(ownerPk);
    }

    function testIssueAndValidateAuthToken() public {
        vm.prank(owner);
        bytes32 tokenId = manager.issueAuthToken(agent, Types.OperationType.CreateBill, 100, 1 days);
        bool valid = manager.validateAuth(tokenId, address(0xCAFE), Types.OperationType.CreateBill, 50);
        assertTrue(valid, "token should validate");
    }

    function testValidateFailsForWrongAmount() public {
        vm.prank(owner);
        bytes32 tokenId = manager.issueAuthToken(agent, Types.OperationType.CreateBill, 100, 1 days);
        bool valid = manager.validateAuth(tokenId, agent, Types.OperationType.CreateBill, 101);
        assertFalse(valid, "token should fail on high amount");
    }

    function testRevokeAuthTokenPreventsValidation() public {
        vm.prank(owner);
        bytes32 tokenId = manager.issueAuthToken(agent, Types.OperationType.CreateBill, 100, 1 days);
        vm.prank(owner);
        manager.revokeAuthToken(tokenId);
        bool valid = manager.validateAuth(tokenId, agent, Types.OperationType.CreateBill, 10);
        assertFalse(valid, "revoked token should be invalid");
    }

    function testIssueRevertsForZeroAmount() public {
        vm.prank(owner);
        vm.expectRevert(Errors.InvalidAmount.selector);
        manager.issueAuthToken(agent, Types.OperationType.CreateBill, 0, 3600);
    }

    function testConsumeAuthWithValidEIP712Signature() public {
        vm.prank(owner);
        bytes32 tokenId = manager.issueAuthToken(agent, Types.OperationType.CreateBill, 100, 1 days);
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 digest = manager.getAuthDigest(tokenId, agent, Types.OperationType.CreateBill, 80, deadline);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(ownerPk, digest);

        bool ok = manager.consumeAuth(tokenId, agent, Types.OperationType.CreateBill, 80, deadline, v, r, s);
        assertTrue(ok, "consume should succeed");

        bool stillValid = manager.validateAuth(tokenId, agent, Types.OperationType.CreateBill, 10);
        assertFalse(stillValid, "token should be used");
    }

    function testConsumeAuthRejectsReplay() public {
        vm.prank(owner);
        bytes32 tokenId = manager.issueAuthToken(agent, Types.OperationType.CreateBill, 100, 1 days);
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 digest = manager.getAuthDigest(tokenId, agent, Types.OperationType.CreateBill, 50, deadline);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(ownerPk, digest);

        manager.consumeAuth(tokenId, agent, Types.OperationType.CreateBill, 50, deadline, v, r, s);
        vm.expectRevert(Errors.TokenUsed.selector);
        manager.consumeAuth(tokenId, agent, Types.OperationType.CreateBill, 50, deadline, v, r, s);
    }

    function testConsumeAuthRejectsInvalidSigner() public {
        vm.prank(owner);
        bytes32 tokenId = manager.issueAuthToken(agent, Types.OperationType.CreateBill, 100, 1 days);
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 digest = manager.getAuthDigest(tokenId, agent, Types.OperationType.CreateBill, 40, deadline);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(0xBEEF, digest);

        vm.expectRevert(Errors.InvalidSignature.selector);
        manager.consumeAuth(tokenId, agent, Types.OperationType.CreateBill, 40, deadline, v, r, s);
    }

    function testConsumeAuthRejectsExpiredDeadline() public {
        vm.prank(owner);
        bytes32 tokenId = manager.issueAuthToken(agent, Types.OperationType.CreateBill, 100, 1 days);
        uint256 deadline = block.timestamp - 1;
        bytes32 digest = manager.getAuthDigest(tokenId, agent, Types.OperationType.CreateBill, 40, deadline);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(ownerPk, digest);

        vm.expectRevert(Errors.DeadlineExpired.selector);
        manager.consumeAuth(tokenId, agent, Types.OperationType.CreateBill, 40, deadline, v, r, s);
    }

    function testConsumeAuthRejectsHighSValue() public {
        vm.prank(owner);
        bytes32 tokenId = manager.issueAuthToken(agent, Types.OperationType.CreateBill, 100, 1 days);
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 digest = manager.getAuthDigest(tokenId, agent, Types.OperationType.CreateBill, 40, deadline);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(ownerPk, digest);
        bytes32 highS = bytes32(SECP256K1N - uint256(s));
        uint8 flippedV = v == 27 ? 28 : 27;

        vm.expectRevert(Errors.InvalidSignature.selector);
        manager.consumeAuth(tokenId, agent, Types.OperationType.CreateBill, 40, deadline, flippedV, r, highS);
    }
}
