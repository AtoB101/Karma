// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaBilateral} from "../core/KarmaBilateral.sol";
import {KarmaFeeBridge} from "../core/KarmaFeeBridge.sol";
import {VerifierRegistry} from "../core/VerifierRegistry.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

/// @notice Integration coverage for the production KarmaFeeBridge: 0.5% fee,
///         3/3/2/2 split, and the KarmaBilateral collectAndRecord flow.
contract KarmaFeeBridgeTest is Test {
    KarmaBilateral internal karma;
    KarmaFeeBridge internal bridge;
    VerifierRegistry internal registry;
    MockERC20 internal usdc;

    address internal admin = makeAddr("admin");
    address internal buyer = makeAddr("buyer");
    address internal agent = makeAddr("agent");
    address internal treasury = makeAddr("treasury");
    address internal buyback = makeAddr("buyback");
    address internal developer = makeAddr("developer");

    uint256 internal constant BUYER_LOCK = 100_000_000; // 100 USDC
    uint256 internal constant AGENT_LOCK = 100_000_000; // 100 USDC

    function setUp() public {
        vm.startPrank(admin);
        karma = new KarmaBilateral(admin);
        usdc = new MockERC20();
        registry = new VerifierRegistry(admin);

        karma.setTokenAllowed(address(usdc), true);
        karma.setSettleDelay(0);          // no settle delay
        karma.setOptimisticDisputeWindow(0); // no finalize delay

        bridge = new KarmaFeeBridge(admin);
        bridge.setCore(address(karma));
        bridge.setToken(address(usdc));
        bridge.setFeeBps(50); // 0.5%
        bridge.setSplit(3, 3, 2, 2);
        bridge.setDestinations(treasury, address(registry), buyback, developer);
        karma.setFeeBridge(address(bridge));
        vm.stopPrank();

        usdc.mint(buyer, 1_000_000_000);
        usdc.mint(agent, 1_000_000_000);
        vm.prank(buyer);
        usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent);
        usdc.approve(address(karma), type(uint256).max);
    }

    function _settle() internal returns (uint256 bindingId) {
        vm.prank(buyer);
        uint256 buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent);
        uint256 agentBill = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer);
        bindingId = karma.bind(buyerBill, agentBill, keccak256("scope"));
        vm.prank(buyer);
        karma.settle(bindingId, keccak256("proof"));
        karma.finalizeSettle(bindingId);
    }

    function test_feeCollectedAndSplit() public {
        _settle();

        uint256 total = BUYER_LOCK + AGENT_LOCK; // 200 USDC
        uint256 expectedFee = (total * 50) / 10_000; // 1 USDC

        assertEq(bridge.totalFeesCollected(), expectedFee);
        assertEq(bridge.totalGmvRecorded(), total);

        uint256 treasuryAmt = (expectedFee * 3) / 10;
        uint256 verifierAmt = (expectedFee * 3) / 10;
        uint256 buybackAmt = (expectedFee * 2) / 10;
        uint256 developerAmt = expectedFee - treasuryAmt - verifierAmt - buybackAmt;

        assertEq(usdc.balanceOf(treasury), treasuryAmt);
        assertEq(usdc.balanceOf(address(registry)), verifierAmt);
        assertEq(usdc.balanceOf(buyback), buybackAmt);
        assertEq(usdc.balanceOf(developer), developerAmt);

        // Buyer's lock is the payment (no payout); seller gets its lock back
        // plus the buyer's payment, minus the fee.
        assertEq(usdc.balanceOf(buyer), 1_000_000_000 - BUYER_LOCK);
        assertEq(usdc.balanceOf(agent), 1_000_000_000 - AGENT_LOCK + (total - expectedFee));
    }

    function test_zeroFeeStillRecordsGmv() public {
        vm.prank(admin);
        bridge.setFeeBps(0);

        _settle();

        assertEq(bridge.totalFeesCollected(), 0);
        assertEq(bridge.totalGmvRecorded(), BUYER_LOCK + AGENT_LOCK);
        assertEq(usdc.balanceOf(agent), 1_000_000_000 - AGENT_LOCK + BUYER_LOCK + AGENT_LOCK);
    }

    function test_setSplitRejectsNonTenParts() public {
        vm.prank(admin);
        vm.expectRevert(KarmaFeeBridge.InvalidSplit.selector);
        bridge.setSplit(3, 3, 3, 2); // sums to 11
    }

    function test_collectAndRecord_revertsForStranger() public {
        vm.expectRevert(KarmaFeeBridge.Unauthorized.selector);
        bridge.collectAndRecord(bytes32(0), buyer, agent, developer, 100, 0);
    }

    function test_collectAndRecord_feeMismatchReverts() public {
        vm.prank(address(karma));
        vm.expectRevert(
            abi.encodeWithSelector(KarmaFeeBridge.FeeMismatch.selector, uint256(0), uint256(100))
        );
        bridge.collectAndRecord(bytes32(0), buyer, agent, developer, 0, 100);
    }
}
