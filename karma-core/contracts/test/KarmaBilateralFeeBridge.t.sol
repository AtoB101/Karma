// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaBilateral} from "../core/KarmaBilateral.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

/// @dev Minimal FeeBridge stub: quoteFee + collectAndRecord with FeeMismatch.
contract MockFeeBridge {
    address public core;
    uint256 public quoteBps; // 0 = cold start
    bool public lastFeeWasZero;
    bytes32 public lastOrderId;
    address public lastDeveloper;
    uint256 public lastAmount;
    uint256 public lastFee;
    uint256 public recordCount;

    error FeeMismatch(uint256 expected, uint256 got);

    constructor(address core_, uint256 quoteBps_) {
        core = core_;
        quoteBps = quoteBps_;
    }

    function setQuoteBps(uint256 bps) external {
        quoteBps = bps;
    }

    function quoteFee(address, uint256 amountUsdc) external view returns (uint256) {
        return (amountUsdc * quoteBps) / 10_000;
    }

    function collectAndRecord(
        bytes32 orderId,
        address,
        address,
        address developer,
        uint256 amountUsdc,
        uint256 feeUsdc
    ) external {
        uint256 expected = (amountUsdc * quoteBps) / 10_000;
        if (feeUsdc != expected) revert FeeMismatch(expected, feeUsdc);
        lastOrderId = orderId;
        lastDeveloper = developer;
        lastAmount = amountUsdc;
        lastFee = feeUsdc;
        lastFeeWasZero = feeUsdc == 0;
        recordCount += 1;
    }
}

contract KarmaBilateralFeeBridgeTest is Test {
    KarmaBilateral internal karma;
    MockERC20 internal usdc;
    MockFeeBridge internal bridge;

    address internal admin = makeAddr("admin");
    address internal buyer = makeAddr("buyer");
    address internal agent = makeAddr("agent");
    address internal builder = makeAddr("builder");

    uint256 internal constant BUYER_LOCK = 100_000_000;
    uint256 internal constant AGENT_LOCK = 100_000_000;
    bytes32 internal constant SCOPE = keccak256("api-data");
    bytes32 internal constant PROOF = keccak256("proof");

    function setUp() public {
        vm.startPrank(admin);
        karma = new KarmaBilateral(admin);
        usdc = new MockERC20();
        karma.setTokenAllowed(address(usdc), true);
        // cold-start: fee=0
        bridge = new MockFeeBridge(address(karma), 0);
        karma.setTreasury(address(0xBEEF));
        karma.setFeeBridge(address(bridge));
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
        uint256 buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent);
        uint256 agentBill = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer);
        bindingId = karma.bind(buyerBill, agentBill, SCOPE);
    }

    function _settle(uint256 bindingId) internal {
        // past settle delay
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        // past optimistic dispute window → finalize (FeeBridge runs here)
        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bindingId);
    }

    function test_setTreasury_and_setFeeBridge() public {
        assertEq(karma.treasury(), address(0xBEEF));
        assertEq(karma.feeBridge(), address(bridge));
        assertEq(bridge.core(), address(karma));
    }

    function test_settle_coldStart_fee0_still_collectAndRecord() public {
        uint256 bindingId = _bind();
        vm.prank(buyer);
        karma.setBindingDeveloper(bindingId, builder);
        _settle(bindingId);

        assertEq(bridge.recordCount(), 1);
        assertTrue(bridge.lastFeeWasZero());
        assertEq(bridge.lastOrderId(), bytes32(bindingId));
        assertEq(bridge.lastDeveloper(), builder);
        assertEq(bridge.lastAmount(), BUYER_LOCK + AGENT_LOCK);
        assertEq(bridge.lastFee(), 0);
    }

    function test_settle_feeMustEqualQuote() public {
        vm.prank(admin);
        bridge.setQuoteBps(20); // 0.2%
        uint256 bindingId = _bind();
        vm.prank(buyer);
        karma.setBindingDeveloper(bindingId, builder);
        _settle(bindingId);

        uint256 total = BUYER_LOCK + AGENT_LOCK;
        uint256 expectedFee = (total * 20) / 10_000;
        assertEq(bridge.recordCount(), 1);
        assertEq(bridge.lastFee(), expectedFee);
        assertEq(bridge.lastOrderId(), bytes32(bindingId));
        assertEq(bridge.lastDeveloper(), builder);
    }

    function test_settle_defaultDeveloperIsSeller() public {
        uint256 bindingId = _bind();
        // no setBindingDeveloper → seller = agent
        _settle(bindingId);
        assertEq(bridge.lastDeveloper(), agent);
        assertEq(bridge.lastOrderId(), bytes32(bindingId));
    }
}
