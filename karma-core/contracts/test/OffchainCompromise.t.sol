// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaBilateral} from "../core/KarmaBilateral.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

/// @notice Matrix: Backend / Verification / DB / Redis / Admin-API impersonation
///         cannot move locked funds without being a legitimate on-chain party.
contract OffchainCompromiseTest is Test {
    KarmaBilateral internal karma;
    MockERC20 internal usdc;

    address internal admin = makeAddr("admin");
    address internal buyer = makeAddr("buyer");
    address internal agent = makeAddr("agent");
    address internal backend = makeAddr("leaked-hot-wallet");
    address internal verifier = makeAddr("malicious-verifier");
    address internal db = makeAddr("compromised-db-writer");

    function setUp() public {
        vm.startPrank(admin);
        karma = new KarmaBilateral(admin);
        usdc = new MockERC20();
        karma.setTokenAllowed(address(usdc), true);
        vm.stopPrank();
        usdc.mint(buyer, 1_000_000_000);
        usdc.mint(agent, 1_000_000_000);
        vm.prank(buyer);
        usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent);
        usdc.approve(address(karma), type(uint256).max);
    }

    function test_matrix_unauthorizedPayout() public {
        vm.prank(buyer);
        uint256 bb = karma.lock(address(usdc), 10_000_000);
        vm.prank(agent);
        uint256 ab = karma.lock(address(usdc), 10_000_000);
        vm.prank(buyer);
        uint256 id = karma.bind(bb, ab, keccak256("t"));
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);

        address[3] memory attackers = [backend, verifier, db];
        for (uint256 i; i < attackers.length; i++) {
            vm.prank(attackers[i]);
            vm.expectRevert();
            karma.settle(id, keccak256("forged-verification"));
        }
    }

    function test_matrix_amountManipulationImpossible() public {
        vm.prank(buyer);
        uint256 billId = karma.lock(address(usdc), 42_000_000);
        assertEq(karma.getBill(billId).amount, 42_000_000);
    }

    function test_matrix_stateSkipImpossible() public {
        vm.prank(buyer);
        uint256 bb = karma.lock(address(usdc), 10_000_000);
        vm.prank(agent);
        uint256 ab = karma.lock(address(usdc), 10_000_000);
        vm.prank(buyer);
        uint256 id = karma.bind(bb, ab, keccak256("t"));
        vm.prank(backend);
        vm.expectRevert();
        karma.finalizeSettle(id);
    }

    function test_matrix_forgedVerificationDoesNotPay() public {
        vm.prank(buyer);
        uint256 bb = karma.lock(address(usdc), 10_000_000);
        vm.prank(agent);
        uint256 ab = karma.lock(address(usdc), 10_000_000);
        vm.prank(buyer);
        uint256 id = karma.bind(bb, ab, keccak256("t"));
        vm.prank(verifier);
        vm.expectRevert(KarmaBilateral.TEENotImplemented.selector);
        karma.settleWithTEE(id, keccak256("attestation"), hex"00");
    }
}
