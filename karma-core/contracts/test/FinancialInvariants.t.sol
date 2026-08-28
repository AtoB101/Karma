// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaBilateral} from "../core/KarmaBilateral.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

/// @notice Named INV-1..INV-10 suite matching security/registry/financial_functions.yaml
contract FinancialInvariantsTest is Test {
    KarmaBilateral internal karma;
    MockERC20 internal usdc;

    address internal admin = makeAddr("admin");
    address internal buyer = makeAddr("buyer");
    address internal agent = makeAddr("agent");
    address internal attacker = makeAddr("compromised-backend");

    uint256 internal constant BUYER_LOCK = 100_000_000;
    uint256 internal constant AGENT_LOCK = 50_000_000;
    bytes32 internal constant SCOPE = keccak256("inv-scope");
    bytes32 internal constant PROOF = keccak256("inv-proof");

    function setUp() public {
        vm.startPrank(admin);
        karma = new KarmaBilateral(admin);
        usdc = new MockERC20();
        karma.setTokenAllowed(address(usdc), true);
        vm.stopPrank();
        usdc.mint(buyer, 10_000_000_000);
        usdc.mint(agent, 10_000_000_000);
        usdc.mint(attacker, 10_000_000_000);
        vm.prank(buyer);
        usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent);
        usdc.approve(address(karma), type(uint256).max);
        vm.prank(attacker);
        usdc.approve(address(karma), type(uint256).max);
    }

    function _bind() internal returns (uint256 bb, uint256 ab, uint256 bindingId) {
        vm.prank(buyer);
        bb = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent);
        ab = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer);
        bindingId = karma.bind(bb, ab, SCOPE);
    }

    /// INV-1: no legal settlement conditions → funds stay locked
    function test_INV1_cannotSettleBeforeDelay() public {
        (, , uint256 bindingId) = _bind();
        vm.prank(buyer);
        vm.expectRevert();
        karma.settle(bindingId, PROOF);
        assertEq(usdc.balanceOf(address(karma)), BUYER_LOCK + AGENT_LOCK);
    }

    /// INV-2: verification / TEE / ZK result cannot alone authorize payout
    function test_INV2_teeAndZkNeverRelease() public {
        (, , uint256 bindingId) = _bind();
        vm.prank(buyer);
        vm.expectRevert(KarmaBilateral.TEENotImplemented.selector);
        karma.settleWithTEE(bindingId, PROOF, hex"deadbeef");
        vm.prank(buyer);
        vm.expectRevert(KarmaBilateral.ZKNotImplemented.selector);
        karma.settleWithZKProof(bindingId, PROOF, hex"cafebabe");
        assertEq(usdc.balanceOf(address(karma)), BUYER_LOCK + AGENT_LOCK);
    }

    /// INV-3: illegal state jumps fail
    function test_INV3_cannotFinalizeFromActive() public {
        (, , uint256 bindingId) = _bind();
        vm.expectRevert();
        karma.finalizeSettle(bindingId);
    }

    function test_INV3_cannotUnlockBoundBill() public {
        (uint256 bb, , ) = _bind();
        vm.prank(buyer);
        vm.expectRevert();
        karma.unlock(bb);
    }

    /// INV-4: no double settlement
    function test_INV4_doubleFinalizeReverts() public {
        (, , uint256 bindingId) = _bind();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bindingId);
        vm.expectRevert();
        karma.finalizeSettle(bindingId);
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    /// INV-5: unauthorized actor cannot move funds
    function test_INV5_strangerCannotSettleOrUnlock() public {
        (uint256 bb, , uint256 bindingId) = _bind();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(attacker);
        vm.expectRevert();
        karma.settle(bindingId, PROOF);
        vm.prank(attacker);
        vm.expectRevert();
        karma.unlock(bb);
    }

    /// INV-6: recipient is bound at lock — attacker cannot redirect
    function test_INV6_unlockPaysOriginalOwnerOnly() public {
        vm.prank(buyer);
        uint256 billId = karma.lock(address(usdc), BUYER_LOCK);
        uint256 beforeBuyer = usdc.balanceOf(buyer);
        uint256 beforeAttacker = usdc.balanceOf(attacker);
        vm.prank(buyer);
        karma.unlock(billId);
        assertEq(usdc.balanceOf(buyer), beforeBuyer + BUYER_LOCK);
        assertEq(usdc.balanceOf(attacker), beforeAttacker);
    }

    /// INV-7: amount is fixed at lock
    function test_INV7_billAmountImmutable() public {
        vm.prank(buyer);
        uint256 billId = karma.lock(address(usdc), BUYER_LOCK);
        assertEq(karma.getBill(billId).amount, BUYER_LOCK);
    }

    /// INV-8: replay / TEE stub cannot skip guards
    function test_INV8_replaySettleAfterSettledFails() public {
        (, , uint256 bindingId) = _bind();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        vm.prank(buyer);
        vm.expectRevert();
        karma.settle(bindingId, PROOF);
    }

    /// INV-9: dispute blocks ordinary settlement
    function test_INV9_disputeBlocksFinalize() public {
        (, , uint256 bindingId) = _bind();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        vm.prank(buyer);
        karma.dispute(bindingId, keccak256("ev"));
        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        vm.expectRevert();
        karma.finalizeSettle(bindingId);
    }

    /// INV-10: compromised backend EOA cannot drain escrow
    function test_INV10_backendKeyCannotExtractEscrow() public {
        (, , uint256 bindingId) = _bind();
        uint256 escrow = usdc.balanceOf(address(karma));
        vm.startPrank(attacker);
        vm.expectRevert();
        karma.settle(bindingId, PROOF);
        vm.expectRevert();
        karma.finalizeSettle(bindingId);
        vm.expectRevert();
        karma.refundOnTimeout(bindingId);
        vm.expectRevert();
        karma.resolveDispute(bindingId, 0);
        vm.stopPrank();
        assertEq(usdc.balanceOf(address(karma)), escrow);
        assertTrue(karma.checkInvariant(address(usdc)));
    }
}
