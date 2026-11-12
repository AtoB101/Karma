// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaBilateral} from "../core/KarmaBilateral.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

/// @dev Fee bridge that actually pulls the fee (mirrors KarmaFeeBridge.collectAndRecord),
///      so the test proves balance == totalLocked survives a real partial payout.
contract WithdrawingFeeBridge {
    MockERC20 public token;
    uint256 public feeBps = 50; // 0.5%

    constructor(MockERC20 token_) { token = token_; }

    function quoteFee(address, uint256 amountUsdc) external view returns (uint256) {
        return (amountUsdc * feeBps) / 10_000;
    }

    function collectAndRecord(bytes32, address, address, address, uint256 amountUsdc, uint256 feeUsdc) external {
        uint256 expected = (amountUsdc * feeBps) / 10_000;
        require(feeUsdc == expected, "fee mismatch");
        require(token.transferFrom(msg.sender, address(this), feeUsdc), "pull failed");
    }
}

/// @notice Escrow conservation invariant: the contract's real ERC20 balance must
///         equal totalLocked[token] after every lifecycle transition.
contract InvariantConservationTest is Test {
    KarmaBilateral internal karma;
    MockERC20 internal usdc;
    WithdrawingFeeBridge internal bridge;

    address internal admin = makeAddr("admin");
    address internal buyer = makeAddr("buyer");
    address internal agent = makeAddr("agent");

    uint256 internal constant BUYER_LOCK = 100_000_000;
    uint256 internal constant AGENT_LOCK = 50_000_000;
    bytes32 internal constant SCOPE = keccak256("conservation-scope");
    bytes32 internal constant PROOF = keccak256("conservation-proof");

    function setUp() public {
        vm.startPrank(admin);
        karma = new KarmaBilateral(admin);
        usdc = new MockERC20();
        karma.setTokenAllowed(address(usdc), true);
        bridge = new WithdrawingFeeBridge(usdc);
        karma.setFeeBridge(address(bridge));
        vm.stopPrank();

        usdc.mint(buyer, 1_000_000_000);
        usdc.mint(agent, 1_000_000_000);
        vm.prank(buyer);
        usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent);
        usdc.approve(address(karma), type(uint256).max);
        vm.prank(admin);
        usdc.approve(address(karma), type(uint256).max);
    }

    function _assertConserves() internal {
        assertTrue(karma.checkInvariant(address(usdc)));
        assertEq(usdc.balanceOf(address(karma)), karma.totalLocked(address(usdc)));
    }

    function _lockBoth() internal returns (uint256 bb, uint256 ab, uint256 bindingId) {
        vm.prank(buyer);
        bb = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent);
        ab = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer);
        bindingId = karma.bind(bb, ab, SCOPE);
    }

    function _settle(uint256 bindingId) internal {
        vm.warp(block.timestamp + karma.settleDelaySeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        vm.warp(block.timestamp + karma.optimisticDisputeWindow() + 1);
        karma.finalizeSettle(bindingId);
    }

    function test_lockConserves() public {
        vm.prank(buyer);
        karma.lock(address(usdc), BUYER_LOCK);
        _assertConserves();
    }

    function test_settleWithFeeConserves() public {
        (,, uint256 bindingId) = _lockBoth();
        _settle(bindingId);
        _assertConserves();
        // pool = 150, fee = 0.5% = 0.75; agent receives pool - fee
        assertEq(usdc.balanceOf(address(bridge)), 750_000);
        assertEq(usdc.balanceOf(agent), 1_000_000_000 - AGENT_LOCK + 150_000_000 - 750_000);
    }

    function test_refundConserves() public {
        (,, uint256 bindingId) = _lockBoth();
        vm.warp(block.timestamp + karma.settleTimeoutSeconds() + 1);
        vm.prank(buyer);
        karma.refundOnTimeout(bindingId);
        _assertConserves();
    }

    function test_unlockConserves() public {
        vm.prank(buyer);
        uint256 bill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(buyer);
        karma.unlock(bill);
        _assertConserves();
    }

    /// A direct transfer to the contract (donation / accidental send) breaks the
    /// ledger, because balance rises without a matching totalLocked entry.
    function test_donationBreaksInvariant() public {
        vm.prank(buyer);
        usdc.transfer(address(karma), 1_000);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.InvariantBroken.selector, address(usdc), 1_000, 0));
        karma.checkInvariant(address(usdc));
    }

    /// A forced payout without a burn (only possible via a malicious token that
    /// self-transfers) also breaks conservation.
    function test_missingBurnBreaksInvariant() public {
        vm.prank(buyer);
        karma.lock(address(usdc), BUYER_LOCK);
        // Simulate leakage: mint directly into the contract (no totalLocked entry).
        usdc.mint(address(karma), 5_000);
        vm.expectRevert();
        karma.checkInvariant(address(usdc));
    }
}
