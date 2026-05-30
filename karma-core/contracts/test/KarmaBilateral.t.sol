// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {KarmaBilateral} from "../core/KarmaBilateral.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

contract KarmaBilateralTest is Test {

    KarmaBilateral internal karma;
    MockERC20      internal usdc;

    address internal admin   = makeAddr("admin");
    address internal buyer   = makeAddr("buyer");
    address internal agent   = makeAddr("agent");
    address internal stranger = makeAddr("stranger");

    uint256 internal constant BUYER_LOCK  = 100_000_000;  // 100 USDC
    uint256 internal constant AGENT_LOCK  =  50_000_000;  //  50 USDC
    bytes32 internal constant SCOPE       = keccak256("search:latest-pricing");
    bytes32 internal constant PROOF       = keccak256("ipfs://Qm...");

    // ── Setup ─────────────────────────────────────────────────────────────────

    function setUp() public {
        vm.startPrank(admin);
        karma = new KarmaBilateral(admin);
        usdc  = new MockERC20();
        karma.setTokenAllowed(address(usdc), true);
        vm.stopPrank();

        usdc.mint(buyer,   1_000_000_000);
        usdc.mint(agent,   1_000_000_000);
        usdc.mint(stranger, 500_000_000);

        vm.prank(buyer);   usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent);   usdc.approve(address(karma), type(uint256).max);
        vm.prank(stranger); usdc.approve(address(karma), type(uint256).max);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  lock()
    // ─────────────────────────────────────────────────────────────────────────

    function test_lock_mintsBillToken() public {
        vm.prank(buyer);
        uint256 billId = karma.lock(address(usdc), BUYER_LOCK);

        assertEq(billId, 1);
        KarmaBilateral.BillToken memory bill = karma.getBill(billId);
        assertEq(bill.owner,  buyer);
        assertEq(bill.token,  address(usdc));
        assertEq(bill.amount, BUYER_LOCK);
        assertEq(uint8(bill.state), uint8(KarmaBilateral.BillState.MINTED));
    }

    function test_lock_transfersUSDCtoContract() public {
        uint256 before = usdc.balanceOf(address(karma));
        vm.prank(buyer);
        karma.lock(address(usdc), BUYER_LOCK);
        assertEq(usdc.balanceOf(address(karma)), before + BUYER_LOCK);
    }

    function test_lock_invariantHolds() public {
        vm.prank(buyer);
        karma.lock(address(usdc), BUYER_LOCK);
        assertTrue(karma.checkInvariant(address(usdc)));
        assertEq(karma.totalBillSupply(address(usdc)), karma.totalLocked(address(usdc)));
    }

    function test_lock_incrementsBillId() public {
        vm.prank(buyer);  uint256 a = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent);  uint256 b = karma.lock(address(usdc), AGENT_LOCK);
        assertEq(b, a + 1);
    }

    function test_lock_revertsOnZeroAmount() public {
        vm.prank(buyer);
        vm.expectRevert(KarmaBilateral.ZeroAmount.selector);
        karma.lock(address(usdc), 0);
    }

    function test_lock_revertsOnDisallowedToken() public {
        address rando = makeAddr("randoToken");
        vm.prank(buyer);
        vm.expectRevert(KarmaBilateral.TokenNotAllowed.selector);
        karma.lock(rando, BUYER_LOCK);
    }

    function test_lock_fuzz(uint96 amount) public {
        vm.assume(amount > 0);
        usdc.mint(buyer, amount);
        vm.prank(buyer);
        uint256 billId = karma.lock(address(usdc), amount);
        assertTrue(karma.checkInvariant(address(usdc)));
        assertEq(karma.getBill(billId).amount, amount);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  unlock() — pre-bind withdrawal
    // ─────────────────────────────────────────────────────────────────────────

    function test_unlock_returnsFundsAndBurnsBill() public {
        vm.prank(buyer);
        uint256 billId = karma.lock(address(usdc), BUYER_LOCK);

        uint256 before = usdc.balanceOf(buyer);
        vm.prank(buyer);
        karma.unlock(billId);

        assertEq(usdc.balanceOf(buyer), before + BUYER_LOCK);
        assertEq(uint8(karma.getBill(billId).state), uint8(KarmaBilateral.BillState.BURNED));
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    function test_unlock_revertsIfNotOwner() public {
        vm.prank(buyer);
        uint256 billId = karma.lock(address(usdc), BUYER_LOCK);

        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.NotBillOwner.selector, billId));
        karma.unlock(billId);
    }

    function test_unlock_revertsIfBound() public {
        (uint256 buyerBill, uint256 agentBill,) = _setupBinding();

        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(
            KarmaBilateral.WrongBillState.selector,
            buyerBill,
            KarmaBilateral.BillState.MINTED,
            KarmaBilateral.BillState.BOUND
        ));
        karma.unlock(buyerBill);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  bind()
    // ─────────────────────────────────────────────────────────────────────────

    function test_bind_bothBillsBecomeBound() public {
        vm.prank(buyer); uint256 buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 agentBill = karma.lock(address(usdc), AGENT_LOCK);

        vm.prank(buyer);
        karma.bind(buyerBill, agentBill, SCOPE);

        assertEq(uint8(karma.getBill(buyerBill).state), uint8(KarmaBilateral.BillState.BOUND));
        assertEq(uint8(karma.getBill(agentBill).state), uint8(KarmaBilateral.BillState.BOUND));
    }

    function test_bind_createsBinding() public {
        (uint256 buyerBill, uint256 agentBill,) = _setupBinding();
        KarmaBilateral.Binding memory b = karma.getBinding(1);

        assertEq(b.buyerBillId, buyerBill);
        assertEq(b.agentBillId, agentBill);
        assertEq(b.scopeHash,   SCOPE);
        assertEq(uint8(b.state), uint8(KarmaBilateral.BindingState.ACTIVE));
    }

    function test_bind_revertsIfCallerNotBuyerOwner() public {
        vm.prank(buyer); uint256 buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 agentBill = karma.lock(address(usdc), AGENT_LOCK);

        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.NotBillOwner.selector, buyerBill));
        karma.bind(buyerBill, agentBill, SCOPE);
    }

    function test_bind_revertsIfSameOwner() public {
        vm.prank(buyer); uint256 bill1 = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(buyer); uint256 bill2 = karma.lock(address(usdc), AGENT_LOCK);

        vm.prank(buyer);
        vm.expectRevert(KarmaBilateral.BuyerAgentSameAddress.selector);
        karma.bind(bill1, bill2, SCOPE);
    }

    function test_bind_revertsIfBuyerBillAlreadyBound() public {
        vm.prank(buyer); uint256 buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 agentBill1 = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(agent); uint256 agentBill2 = karma.lock(address(usdc), AGENT_LOCK);

        vm.prank(buyer); karma.bind(buyerBill, agentBill1, SCOPE);

        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(
            KarmaBilateral.WrongBillState.selector,
            buyerBill,
            KarmaBilateral.BillState.MINTED,
            KarmaBilateral.BillState.BOUND
        ));
        karma.bind(buyerBill, agentBill2, SCOPE);
    }

    function test_bind_accumulatesPendingBatchAmount() public {
        vm.prank(buyer); uint256 bb = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 ab = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer); karma.bind(bb, ab, SCOPE);

        assertEq(karma.pendingBatchAmount(address(usdc)), BUYER_LOCK + AGENT_LOCK);
    }

    function test_bind_autoPendingWhenThresholdReached() public {
        vm.prank(admin);
        karma.setBatchThreshold(address(usdc), BUYER_LOCK + AGENT_LOCK);

        vm.prank(buyer); uint256 bb = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 ab = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer); uint256 bindingId = karma.bind(bb, ab, SCOPE);

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.PENDING));
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  settle()
    // ─────────────────────────────────────────────────────────────────────────

    function test_settle_burnsBothBillsAndReleasesUSDC() public {
        (, , uint256 bindingId) = _setupBinding();

        uint256 buyerBefore = usdc.balanceOf(buyer);
        uint256 agentBefore = usdc.balanceOf(agent);

        // advance past dispute window
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);

        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        // settle() enters FINALIZING; finalizeSettle() burns bills and releases USDC
        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bindingId);

        KarmaBilateral.Binding memory b = karma.getBinding(bindingId);
        assertEq(uint8(b.state), uint8(KarmaBilateral.BindingState.SETTLED));
        assertEq(b.proofHash, PROOF);

        assertEq(usdc.balanceOf(buyer), buyerBefore + BUYER_LOCK);
        assertEq(usdc.balanceOf(agent), agentBefore + AGENT_LOCK);
    }

    function test_settle_billsAreBurned() public {
        (uint256 bb, uint256 ab, uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        // finalizeSettle burns bills
        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bindingId);

        assertEq(uint8(karma.getBill(bb).state), uint8(KarmaBilateral.BillState.BURNED));
        assertEq(uint8(karma.getBill(ab).state), uint8(KarmaBilateral.BillState.BURNED));
    }

    function test_settle_invariantHoldsAfterSettle() public {
        (, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        // finalizeSettle burns bills, zeroing supply and locked
        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bindingId);

        assertTrue(karma.checkInvariant(address(usdc)));
        assertEq(karma.totalBillSupply(address(usdc)), 0);
        assertEq(karma.totalLocked(address(usdc)), 0);
    }

    function test_settle_revertsBeforeSettleDelay() public {
        (, , uint256 bindingId) = _setupBinding();

        // Must pre-compute settleAfter BEFORE vm.prank — view calls consume the prank
        uint256 settleAfter = block.timestamp + karma.disputeWindowSeconds();

        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.SettleDelayActive.selector, settleAfter));
        karma.settle(bindingId, PROOF);
    }

    function test_settle_revertsIfStranger() public {
        (, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);

        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.NoDisputeAccess.selector, bindingId));
        karma.settle(bindingId, PROOF);
    }

    function test_settle_pendingBindingNoWindowRequired() public {
        vm.prank(admin);
        karma.setBatchThreshold(address(usdc), BUYER_LOCK + AGENT_LOCK);

        vm.prank(buyer); uint256 bb = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 ab = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer); uint256 bindingId = karma.bind(bb, ab, SCOPE);

        // state is PENDING — settle delay waived, but finalizeSettle still needed
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bindingId);

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.SETTLED));
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  dispute() + resolveDispute()
    // ─────────────────────────────────────────────────────────────────────────

    function test_dispute_transitionsToDisputed() public {
        (, , uint256 bindingId) = _setupBinding();
        // dispute requires FINALIZING state (after settle)
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);

        vm.prank(buyer);
        karma.dispute(bindingId, PROOF);

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.DISPUTED));
    }

    function test_dispute_revertsIfStranger() public {
        (, , uint256 bindingId) = _setupBinding();
        // dispute requires FINALIZING state (after settle)
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);

        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.NoDisputeAccess.selector, bindingId));
        karma.dispute(bindingId, PROOF);
    }

    function test_dispute_revertsIfAlreadyDisputed() public {
        (, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);
        vm.prank(buyer); karma.dispute(bindingId, PROOF);

        // Binding is now DISPUTED; second dispute reverts (DISPUTED != FINALIZING)
        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(
            KarmaBilateral.WrongBindingState.selector,
            bindingId,
            KarmaBilateral.BindingState.FINALIZING,
            KarmaBilateral.BindingState.DISPUTED
        ));
        karma.dispute(bindingId, PROOF);
    }

    function test_resolveDispute_fullBuyer() public {
        (, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);
        vm.prank(buyer); karma.dispute(bindingId, PROOF);

        uint256 buyerBefore = usdc.balanceOf(buyer);
        uint256 agentBefore = usdc.balanceOf(agent);

        vm.prank(admin);
        karma.resolveDispute(bindingId, 10_000); // 100% to buyer

        assertEq(usdc.balanceOf(buyer), buyerBefore + BUYER_LOCK + AGENT_LOCK);
        assertEq(usdc.balanceOf(agent), agentBefore);
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    function test_resolveDispute_fullAgent() public {
        (, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);
        vm.prank(buyer); karma.dispute(bindingId, PROOF);

        uint256 agentBefore = usdc.balanceOf(agent);

        vm.prank(admin);
        karma.resolveDispute(bindingId, 0); // 100% to agent

        assertEq(usdc.balanceOf(agent), agentBefore + BUYER_LOCK + AGENT_LOCK);
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    function test_resolveDispute_split() public {
        (, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);
        vm.prank(buyer); karma.dispute(bindingId, PROOF);

        uint256 buyerBefore = usdc.balanceOf(buyer);
        uint256 agentBefore = usdc.balanceOf(agent);
        uint256 pool        = BUYER_LOCK + AGENT_LOCK;

        vm.prank(admin);
        karma.resolveDispute(bindingId, 5_000); // 50/50

        assertEq(usdc.balanceOf(buyer), buyerBefore + pool / 2);
        assertEq(usdc.balanceOf(agent), agentBefore + pool / 2);
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    function test_resolveDispute_fuzz(uint16 bps) public {
        vm.assume(bps <= 10_000);
        (, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);
        vm.prank(buyer); karma.dispute(bindingId, PROOF);

        uint256 buyerBefore = usdc.balanceOf(buyer);
        uint256 agentBefore = usdc.balanceOf(agent);
        uint256 pool        = BUYER_LOCK + AGENT_LOCK;

        vm.prank(admin);
        karma.resolveDispute(bindingId, bps);

        uint256 buyerPayout = (pool * bps) / 10_000;
        uint256 agentPayout = pool - buyerPayout;
        assertEq(usdc.balanceOf(buyer), buyerBefore + buyerPayout);
        assertEq(usdc.balanceOf(agent), agentBefore + agentPayout);
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    function test_resolveDispute_revertsIfNotAdmin() public {
        (, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);
        vm.prank(buyer); karma.dispute(bindingId, PROOF);

        vm.prank(stranger);
        vm.expectRevert(KarmaBilateral.Unauthorized.selector);
        karma.resolveDispute(bindingId, 5_000);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  refundOnTimeout()
    // ─────────────────────────────────────────────────────────────────────────

    function test_refundOnTimeout_returnsCollateralToOwners() public {
        (, , uint256 bindingId) = _setupBinding();

        uint256 buyerBefore = usdc.balanceOf(buyer);
        uint256 agentBefore = usdc.balanceOf(agent);

        vm.warp(block.timestamp + karma.settleTimeoutSeconds() + 1);
        vm.prank(buyer);
        karma.refundOnTimeout(bindingId);

        assertEq(usdc.balanceOf(buyer), buyerBefore + BUYER_LOCK);
        assertEq(usdc.balanceOf(agent), agentBefore + AGENT_LOCK);
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.REFUNDED));
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    function test_refundOnTimeout_revertsBeforeTimeout() public {
        (, , uint256 bindingId) = _setupBinding();

        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.DisputeNotExpired.selector, bindingId));
        karma.refundOnTimeout(bindingId);
    }

    function test_refundOnTimeout_revertsIfNotBuyer() public {
        (uint256 bb, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.settleTimeoutSeconds() + 1);

        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.NotBillOwner.selector, bb));
        karma.refundOnTimeout(bindingId);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Invariant — critical safety property
    // ─────────────────────────────────────────────────────────────────────────

    function test_invariant_holdsAfterMultipleOperations() public {
        // lock, bind, settle cycle × 2 in parallel
        vm.prank(buyer); uint256 bb1 = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 ab1 = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer); uint256 bb2 = karma.lock(address(usdc), BUYER_LOCK * 2);
        vm.prank(agent); uint256 ab2 = karma.lock(address(usdc), AGENT_LOCK * 2);

        vm.prank(buyer); uint256 bind1 = karma.bind(bb1, ab1, SCOPE);
        vm.prank(buyer); uint256 bind2 = karma.bind(bb2, ab2, keccak256("scope2"));

        assertTrue(karma.checkInvariant(address(usdc)));

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);

        vm.prank(buyer); karma.settle(bind1, PROOF);
        assertTrue(karma.checkInvariant(address(usdc)));

        vm.prank(agent); karma.settle(bind2, keccak256("proof2"));
        assertTrue(karma.checkInvariant(address(usdc)));

        // finalizeSettle needed to burn bills and zero supply/locked
        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bind1);
        karma.finalizeSettle(bind2);

        assertEq(karma.totalBillSupply(address(usdc)), 0);
        assertEq(karma.totalLocked(address(usdc)), 0);
    }

    function test_invariant_holdsAfterUnlock() public {
        vm.prank(buyer); uint256 billId = karma.lock(address(usdc), BUYER_LOCK);
        assertTrue(karma.checkInvariant(address(usdc)));
        vm.prank(buyer); karma.unlock(billId);
        assertTrue(karma.checkInvariant(address(usdc)));
        assertEq(karma.totalBillSupply(address(usdc)), 0);
        assertEq(karma.totalLocked(address(usdc)), 0);
    }

    function test_invariant_holdsAfterDispute() public {
        (, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);
        vm.prank(buyer); karma.dispute(bindingId, PROOF);
        vm.prank(admin); karma.resolveDispute(bindingId, 7_000);
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    function test_invariant_holdsAfterTimeout() public {
        (, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.settleTimeoutSeconds() + 1);
        vm.prank(buyer); karma.refundOnTimeout(bindingId);
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Reentrancy guard
    // ─────────────────────────────────────────────────────────────────────────

    function test_reentrancy_lockIsGuarded() public {
        ReentrantToken rt = new ReentrantToken(address(karma));
        vm.prank(admin); karma.setTokenAllowed(address(rt), true);

        rt.mint(buyer, BUYER_LOCK * 2);
        vm.prank(buyer); rt.approve(address(karma), type(uint256).max);

        // The nonReentrant guard blocks the inner reentrant lock() call with Reentrancy().
        // ReentrantToken.transferFrom swallows that inner revert and returns true,
        // so the outer lock() call succeeds — this is the correct guard behavior.
        // We verify: (1) outer call succeeds, (2) only ONE bill was minted (not two),
        // and (3) the invariant holds (no double-credit from the swallowed inner call).
        vm.prank(buyer);
        uint256 billId = karma.lock(address(rt), BUYER_LOCK);

        assertEq(billId, 1);
        // Only one bill exists — inner reentrant lock was blocked
        assertEq(karma.ownerBills(buyer).length, 1);
        // Invariant: supply == locked (inner call produced no phantom bill)
        assertTrue(karma.checkInvariant(address(rt)));
        assertEq(karma.totalBillSupply(address(rt)), BUYER_LOCK);
        assertEq(karma.totalLocked(address(rt)), BUYER_LOCK);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Admin controls
    // ─────────────────────────────────────────────────────────────────────────

    function test_admin_setTokenAllowed() public {
        address newToken = makeAddr("newToken");
        assertFalse(karma.tokenAllowed(newToken));
        vm.prank(admin); karma.setTokenAllowed(newToken, true);
        assertTrue(karma.tokenAllowed(newToken));
        vm.prank(admin); karma.setTokenAllowed(newToken, false);
        assertFalse(karma.tokenAllowed(newToken));
    }

    function test_admin_setBatchThreshold() public {
        vm.prank(admin); karma.setBatchThreshold(address(usdc), 999_000_000);
        assertEq(karma.batchThreshold(address(usdc)), 999_000_000);
    }

    function test_admin_revertsIfNotAdmin() public {
        vm.prank(stranger);
        vm.expectRevert(KarmaBilateral.Unauthorized.selector);
        karma.setTokenAllowed(address(usdc), false);
    }

    function test_constructor_revertsOnZeroAdmin() public {
        vm.expectRevert(KarmaBilateral.ZeroAddress.selector);
        new KarmaBilateral(address(0));
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  ownerBills view
    // ─────────────────────────────────────────────────────────────────────────

    function test_ownerBills_tracked() public {
        vm.prank(buyer); karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(buyer); karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); karma.lock(address(usdc), AGENT_LOCK);

        assertEq(karma.ownerBills(buyer).length, 2);
        assertEq(karma.ownerBills(agent).length, 1);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Helpers
    // ─────────────────────────────────────────────────────────────────────────

    function _setupBinding() internal returns (uint256 buyerBill, uint256 agentBill, uint256 bindingId) {
        vm.prank(buyer); buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); agentBill = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer); bindingId = karma.bind(buyerBill, agentBill, SCOPE);
    }
}

// ── Reentrancy attack token ───────────────────────────────────────────────────

contract ReentrantToken {
    address internal immutable _target;
    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    constructor(address target) { _target = target; }

    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function transfer(address to, uint256 amount) external returns (bool) {
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;
        return true;
    }

    // Re-enters karma.lock during transferFrom
    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        // attempt reentrant call — should be blocked by nonReentrant
        (bool ok,) = _target.call(abi.encodeWithSignature("lock(address,uint256)", address(this), amount));
        return true;
    }
}
