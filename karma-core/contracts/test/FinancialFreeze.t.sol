// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaBilateral} from "../core/KarmaBilateral.sol";
import {CircuitBreaker} from "../core/CircuitBreaker.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

contract FinancialFreezeTest is Test {
    KarmaBilateral internal karma;
    CircuitBreaker internal breaker;
    MockERC20 internal usdc;

    address internal admin = makeAddr("admin");
    address internal operator = makeAddr("operator");
    address internal buyer = makeAddr("buyer");
    address internal agent = makeAddr("agent");
    address internal stranger = makeAddr("stranger");

    uint256 internal constant BUYER_LOCK = 100_000_000;
    uint256 internal constant AGENT_LOCK = 50_000_000;
    bytes32 internal constant SCOPE = keccak256("scope");
    bytes32 internal constant PROOF = keccak256("proof");

    function setUp() public {
        vm.startPrank(admin);
        karma = new KarmaBilateral(admin);
        breaker = new CircuitBreaker(admin);
        usdc = new MockERC20();
        karma.setTokenAllowed(address(usdc), true);
        karma.setCircuitBreaker(address(breaker));
        karma.setFreezeOperator(operator);
        vm.stopPrank();

        usdc.mint(buyer, 1_000_000_000);
        usdc.mint(agent, 1_000_000_000);
        vm.prank(buyer);
        usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent);
        usdc.approve(address(karma), type(uint256).max);
    }

    function _bind() internal returns (uint256 bindingId) {
        vm.prank(buyer);
        uint256 bb = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent);
        uint256 ab = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer);
        bindingId = karma.bind(bb, ab, SCOPE);
    }

    function test_freezeGlobal_blocksSettleAndAllowsUnlock() public {
        vm.prank(buyer);
        uint256 unbound = karma.lock(address(usdc), BUYER_LOCK);
        uint256 bindingId = _bind();

        vm.prank(operator);
        karma.freezeGlobal(1 hours, "critical");
        assertTrue(karma.isGlobalFrozen());

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.FundsFrozen.selector, uint8(1), karma.globalFreezeUntil()));
        karma.settle(bindingId, PROOF);

        vm.prank(buyer);
        karma.unlock(unbound);
        assertEq(uint8(karma.getBill(unbound).state), uint8(KarmaBilateral.BillState.BURNED));
    }

    function test_freezeExpiresAutomatically() public {
        uint256 bindingId = _bind();
        vm.prank(admin);
        karma.freezeGlobal(1 hours, "temp");
        vm.warp(block.timestamp + 1 hours + 1);
        assertFalse(karma.isGlobalFrozen());

        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
    }

    function test_refundOnTimeoutAllowedWhileFrozen() public {
        vm.prank(admin);
        karma.setSettleTimeout(1 hours);
        uint256 bindingId = _bind();
        vm.prank(admin);
        karma.freezeGlobal(7 days, "incident");
        vm.warp(block.timestamp + 1 hours + 1);
        vm.prank(buyer);
        karma.refundOnTimeout(bindingId);
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.REFUNDED));
    }

    function test_circuitBreakerPauseBlocksPayout() public {
        uint256 bindingId = _bind();
        vm.prank(admin);
        breaker.emergencyPause("scp");
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.FundsFrozen.selector, uint8(5), type(uint256).max));
        karma.settle(bindingId, PROOF);
    }

    function test_nonAdminCannotFreeze() public {
        vm.prank(stranger);
        vm.expectRevert(KarmaBilateral.Unauthorized.selector);
        karma.freezeGlobal(1 hours, "nope");
    }

    function test_freezeDurationCap() public {
        vm.prank(admin);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.FreezeDurationInvalid.selector, uint256(8 days)));
        karma.freezeGlobal(8 days, "too long");
    }

    function test_bindingFreezeBlocksFinalize() public {
        uint256 bindingId = _bind();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);

        vm.prank(admin);
        karma.freezeBinding(bindingId, 7 days, "investigate");

        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        vm.expectRevert();
        karma.finalizeSettle(bindingId);
    }

    function test_unfreezeRestoresPayout() public {
        uint256 bindingId = _bind();
        vm.prank(admin);
        karma.freezeGlobal(1 hours, "pause");
        vm.prank(admin);
        karma.unfreezeGlobal();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
    }
}
