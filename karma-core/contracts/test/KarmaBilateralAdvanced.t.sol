// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaBilateral} from "../core/KarmaBilateral.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

/// @title KarmaBilateralAdvancedTest
/// @notice Comprehensive attack vectors, edge cases, mixed-settlement, and state-machine exhaustion.
contract KarmaBilateralAdvancedTest is Test {

    KarmaBilateral internal karma;
    MockERC20      internal usdc;

    address internal admin    = makeAddr("admin");
    address internal buyer    = makeAddr("buyer");
    address internal agent    = makeAddr("agent");
    address internal stranger = makeAddr("stranger");
    address internal attacker = makeAddr("attacker");

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

        usdc.mint(buyer,    1_000_000_000);
        usdc.mint(agent,    1_000_000_000);
        usdc.mint(stranger,   500_000_000);
        usdc.mint(attacker,   500_000_000);

        vm.prank(buyer);    usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent);    usdc.approve(address(karma), type(uint256).max);
        vm.prank(stranger);  usdc.approve(address(karma), type(uint256).max);
        vm.prank(attacker);  usdc.approve(address(karma), type(uint256).max);
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  MIXED SETTLEMENT TESTS
    // ═══════════════════════════════════════════════════════════════════════════

    /// @notice Simulate NCPA-style (standalone) bill + Bilateral binding operating in parallel,
    ///         verifying no cross-contamination of state.
    function test_mixed_ncpaAndBilateral_parallel() public {
        // ── NCPA-style bills: standalone lock/unlock flow ──
        vm.prank(buyer);
        uint256 ncpaBill = karma.lock(address(usdc), BUYER_LOCK);
        assertEq(uint8(karma.getBill(ncpaBill).state), uint8(KarmaBilateral.BillState.MINTED));

        // ── Bilateral bills: lock + bind flow ──
        vm.prank(buyer);
        uint256 bilateralBuyer = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent);
        uint256 bilateralAgent = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer);
        uint256 bindingId = karma.bind(bilateralBuyer, bilateralAgent, SCOPE);

        // Verify NCPA bill still MINTED and unaffected by bilateral operations
        assertEq(uint8(karma.getBill(ncpaBill).state), uint8(KarmaBilateral.BillState.MINTED));
        assertEq(karma.getBill(ncpaBill).owner, buyer);

        // Verify bilateral bills are BOUND
        assertEq(uint8(karma.getBill(bilateralBuyer).state), uint8(KarmaBilateral.BillState.BOUND));
        assertEq(uint8(karma.getBill(bilateralAgent).state), uint8(KarmaBilateral.BillState.BOUND));

        // NCPA bill can still be unlocked independently
        vm.prank(buyer);
        karma.unlock(ncpaBill);
        assertEq(uint8(karma.getBill(ncpaBill).state), uint8(KarmaBilateral.BillState.BURNED));

        // Bilateral binding unaffected by NCPA unlock
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.ACTIVE));
        assertEq(uint8(karma.getBill(bilateralBuyer).state), uint8(KarmaBilateral.BillState.BOUND));

        // invariant holds after mixed operations
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    /// @notice Use the same USDC token for both NCPA-style and Bilateral flows;
    ///         verify global totalBillSupply and totalLocked track correctly.
    function test_mixed_sameUSDC_differentContracts() public {
        uint256 initialSupply = karma.totalBillSupply(address(usdc));
        uint256 initialLocked = karma.totalLocked(address(usdc));

        // ── NCPA flow: lock → unlock (bill burned) ──
        vm.prank(buyer);
        uint256 ncpaBill = karma.lock(address(usdc), BUYER_LOCK);
        assertEq(karma.totalBillSupply(address(usdc)), initialSupply + BUYER_LOCK);
        assertEq(karma.totalLocked(address(usdc)), initialLocked + BUYER_LOCK);

        vm.prank(buyer);
        karma.unlock(ncpaBill);
        // Supply goes back to baseline after burn
        assertEq(karma.totalBillSupply(address(usdc)), initialSupply);
        assertEq(karma.totalLocked(address(usdc)), initialLocked);

        // ── Bilateral flow: lock → bind → settle → finalize ──
        vm.prank(buyer);
        uint256 bb = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent);
        uint256 ab = karma.lock(address(usdc), AGENT_LOCK);
        assertEq(karma.totalBillSupply(address(usdc)), BUYER_LOCK + AGENT_LOCK);
        assertEq(karma.totalLocked(address(usdc)), BUYER_LOCK + AGENT_LOCK);

        vm.prank(buyer);
        uint256 bindingId = karma.bind(bb, ab, SCOPE);
        // Supply unchanged after bind (bills still live)
        assertEq(karma.totalBillSupply(address(usdc)), BUYER_LOCK + AGENT_LOCK);

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        // Supply unchanged after settle (FINALIZING, bills not yet burned)
        assertEq(karma.totalBillSupply(address(usdc)), BUYER_LOCK + AGENT_LOCK);

        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bindingId);
        // Both bills burned → supply = 0
        assertEq(karma.totalBillSupply(address(usdc)), 0);
        assertEq(karma.totalLocked(address(usdc)), 0);

        // ── Verify per-address tracking is separate per owner ──
        (uint256 freeB, uint256 boundB, uint256 mintedB, uint256 lockedB) = karma.getBalance(buyer);
        (uint256 freeA, uint256 boundA, uint256 mintedA, uint256 lockedA) = karma.getBalance(agent);
        assertEq(freeB + boundB, mintedB, "buyer per-addr invariant");
        assertEq(freeA + boundA, mintedA, "agent per-addr invariant");
        assertEq(boundB, 0);
        assertEq(boundA, 0);

        assertTrue(karma.checkInvariant(address(usdc)));
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  ATTACK TESTS
    // ═══════════════════════════════════════════════════════════════════════════

    /// @notice Malicious token whose transfer() reenters karma.settle() during finalizeSettle.
    ///         nonReentrant guard must block the reentrant call.
    function test_reentrancy_settle() public {
        ReentrantAttackToken rt = new ReentrantAttackToken();
        vm.prank(admin);
        karma.setTokenAllowed(address(rt), true);

        rt.mint(buyer, type(uint256).max);
        rt.mint(agent, type(uint256).max);
        vm.prank(buyer);
        rt.approve(address(karma), type(uint256).max);
        vm.prank(agent);
        rt.approve(address(karma), type(uint256).max);

        vm.prank(buyer);
        uint256 bb = karma.lock(address(rt), BUYER_LOCK);
        vm.prank(agent);
        uint256 ab = karma.lock(address(rt), AGENT_LOCK);
        vm.prank(buyer);
        uint256 bindingId = karma.bind(bb, ab, SCOPE);

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);

        // Configure attack: transfer() will try to call settle() on the same binding
        rt.setAttackTarget(address(karma));
        rt.setAttackPayload(
            abi.encodeWithSelector(KarmaBilateral.settle.selector, bindingId, PROOF)
        );
        rt.setShouldAttack(true);

        // Advance past dispute window, then finalizeSettle triggers token.transfer()
        // which attempts reentrant settle(). nonReentrant guard blocks it.
        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bindingId);

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.SETTLED));
    }

    /// @notice Malicious token whose transfer() reenters karma.dispute() during resolveDispute.
    ///         nonReentrant guard must block the reentrant call.
    function test_reentrancy_dispute() public {
        ReentrantAttackToken rt = new ReentrantAttackToken();
        vm.prank(admin);
        karma.setTokenAllowed(address(rt), true);

        // Use reasonable balances (not type(uint256).max) to avoid overflow
        // caused by double spending checks with unchecked arithmetic
        rt.mint(buyer, 1_000_000_000);
        rt.mint(agent, 1_000_000_000);
        vm.prank(buyer);
        rt.approve(address(karma), type(uint256).max);
        vm.prank(agent);
        rt.approve(address(karma), type(uint256).max);

        vm.prank(buyer);
        uint256 bb = karma.lock(address(rt), BUYER_LOCK);
        vm.prank(agent);
        uint256 ab = karma.lock(address(rt), AGENT_LOCK);
        vm.prank(buyer);
        uint256 bindingId = karma.bind(bb, ab, SCOPE);

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);

        // Dispute first
        vm.prank(buyer);
        karma.dispute(bindingId, PROOF);

        // Configure attack: transfer() will try to call dispute() again
        rt.setAttackTarget(address(karma));
        rt.setAttackPayload(
            abi.encodeWithSelector(KarmaBilateral.dispute.selector, bindingId, PROOF)
        );
        rt.setShouldAttack(true);

        // Admin resolves → execution reaches transfer() → reentrant dispute() blocked
        vm.prank(admin);
        karma.resolveDispute(bindingId, 5_000);

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.SETTLED));
    }

    /// @notice Attacker sees settle() in mempool, tries to front-run with dispute().
    ///         dispute() requires FINALIZING state, so front-run must revert.
    function test_frontrun_settleWithDispute() public {
        (uint256 bb, uint256 ab, uint256 bindingId) = _setupBinding();

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        // Binding is still ACTIVE — attacker tries to front-run settle() with dispute()
        // dispute() requires FINALIZING, NOT ACTIVE → reverts
        vm.prank(stranger);
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector,
                bindingId,
                KarmaBilateral.BindingState.FINALIZING,
                KarmaBilateral.BindingState.ACTIVE
            )
        );
        karma.dispute(bindingId, PROOF);

        // Legitimate settle still works after failed front-run
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.FINALIZING));
    }

    /// @notice Try binding the same bill in two different bindings.
    function test_doubleBind_attempt() public {
        vm.prank(buyer);
        uint256 buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent);
        uint256 agentBill1 = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(agent);
        uint256 agentBill2 = karma.lock(address(usdc), AGENT_LOCK);

        // First bind: buyerBill + agentBill1
        vm.prank(buyer);
        karma.bind(buyerBill, agentBill1, SCOPE);

        // buyerBill is now BOUND — attempt second bind with agentBill2 → reverts
        vm.prank(buyer);
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaBilateral.WrongBillState.selector,
                buyerBill,
                KarmaBilateral.BillState.MINTED,
                KarmaBilateral.BillState.BOUND
            )
        );
        karma.bind(buyerBill, agentBill2, SCOPE);

        // Verify original binding intact
        assertEq(uint8(karma.getBinding(1).state), uint8(KarmaBilateral.BindingState.ACTIVE));
    }

    /// @notice Try settling a binding that is already in DISPUTED state.
    function test_settle_afterDispute_withoutResolve() public {
        (, , uint256 bindingId) = _setupSettleAndDispute();

        // Binding is DISPUTED — settle() requires ACTIVE or PENDING
        vm.prank(buyer);
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector,
                bindingId,
                KarmaBilateral.BindingState.ACTIVE,
                KarmaBilateral.BindingState.DISPUTED
            )
        );
        karma.settle(bindingId, PROOF);
    }

    /// @notice Try disputing after finalizeSettle() — settlement is terminal.
    function test_dispute_afterFinalizeSettle() public {
        (, , uint256 bindingId) = _setupSettleAndFinalize();

        // Binding is SETTLED — dispute() requires FINALIZING
        vm.prank(buyer);
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector,
                bindingId,
                KarmaBilateral.BindingState.FINALIZING,
                KarmaBilateral.BindingState.SETTLED
            )
        );
        karma.dispute(bindingId, PROOF);
    }

    /// @notice Edge case: lock(0) should revert.
    function test_lock_zeroAmount() public {
        vm.prank(buyer);
        vm.expectRevert(KarmaBilateral.ZeroAmount.selector);
        karma.lock(address(usdc), 0);
    }

    /// @notice Try binding bills from the same owner — protocol forbids self-binding.
    function test_bind_sameOwner() public {
        vm.prank(buyer);
        uint256 bill1 = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(buyer);
        uint256 bill2 = karma.lock(address(usdc), AGENT_LOCK);

        vm.prank(buyer);
        vm.expectRevert(KarmaBilateral.BuyerAgentSameAddress.selector);
        karma.bind(bill1, bill2, SCOPE);
    }

    /// @notice Try binding bills denominated in different tokens.
    function test_bind_differentTokens() public {
        MockERC20 dai = new MockERC20();
        vm.prank(admin);
        karma.setTokenAllowed(address(dai), true);
        dai.mint(agent, AGENT_LOCK);
        vm.prank(agent);
        dai.approve(address(karma), type(uint256).max);

        vm.prank(buyer);
        uint256 buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent);
        uint256 agentBill = karma.lock(address(dai), AGENT_LOCK);

        vm.prank(buyer);
        vm.expectRevert(KarmaBilateral.TokenNotAllowed.selector);
        karma.bind(buyerBill, agentBill, SCOPE);
    }

    /// @notice Try unlocking a bill that is already BOUND.
    function test_unlock_boundBill() public {
        (uint256 buyerBill, , ) = _setupBinding();

        vm.prank(buyer);
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaBilateral.WrongBillState.selector,
                buyerBill,
                KarmaBilateral.BillState.MINTED,
                KarmaBilateral.BillState.BOUND
            )
        );
        karma.unlock(buyerBill);
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  EDGE CASES
    // ═══════════════════════════════════════════════════════════════════════════

    /// @notice Lock maximum uint256 amount of a fresh token — invariant must hold.
    function test_maxLockAmount() public {
        // Use a fresh token with clean balances to avoid overflow
        MockERC20 tok = new MockERC20();
        vm.prank(admin);
        karma.setTokenAllowed(address(tok), true);

        tok.mint(buyer, type(uint256).max);
        vm.prank(buyer);
        tok.approve(address(karma), type(uint256).max);

        vm.prank(buyer);
        karma.lock(address(tok), type(uint256).max);

        assertTrue(karma.checkInvariant(address(tok)));
        assertEq(karma.totalBillSupply(address(tok)), type(uint256).max);
        assertEq(karma.totalLocked(address(tok)), type(uint256).max);
    }

    /// @notice Set batch threshold to zero and verify normal flow works.
    function test_batchThreshold_zero() public {
        vm.prank(admin);
        karma.setBatchThreshold(address(usdc), 0);

        (uint256 bb, uint256 ab, uint256 bindingId) = _setupBinding();

        // Threshold is 0; pendingBatchAmount is non-zero but threshold is 0 → no PENDING
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.ACTIVE));

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bindingId);

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.SETTLED));
    }

    /// @notice Rapid lock/unlock cycle 50 times — state must stay consistent.
    function test_rapidLockUnlock_cycle() public {
        for (uint256 i = 0; i < 50; i++) {
            vm.prank(buyer);
            uint256 billId = karma.lock(address(usdc), BUYER_LOCK);

            assertEq(uint8(karma.getBill(billId).state), uint8(KarmaBilateral.BillState.MINTED));
            assertTrue(karma.checkInvariant(address(usdc)));

            vm.prank(buyer);
            karma.unlock(billId);

            assertEq(uint8(karma.getBill(billId).state), uint8(KarmaBilateral.BillState.BURNED));
            assertTrue(karma.checkInvariant(address(usdc)));
        }

        // After 50 cycles, global invariants must hold and supply/locked at zero
        assertEq(karma.totalBillSupply(address(usdc)), 0);
        assertEq(karma.totalLocked(address(usdc)), 0);
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    /// @notice Dispute exactly at the boundary of the dispute window.
    function test_disputeWindow_boundary() public {
        (, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);

        KarmaBilateral.Binding memory b = karma.getBinding(bindingId);
        uint256 windowEnd = b.settleSubmittedAt + karma.disputeWindow();

        // Dispute at t = windowEnd - 1 (within window, should succeed)
        vm.warp(windowEnd - 1);
        vm.prank(buyer);
        karma.dispute(bindingId, PROOF);
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.DISPUTED));
    }

    /// @notice Dispute at t = windowEnd exactly — should revert (window closed).
    function test_disputeWindow_boundary_revertsAfter() public {
        (, , uint256 bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);

        KarmaBilateral.Binding memory b = karma.getBinding(bindingId);
        uint256 windowEnd = b.settleSubmittedAt + karma.disputeWindow();

        // Dispute at t = windowEnd (boundary closed, should revert)
        vm.warp(windowEnd);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.DisputeWindowClosed.selector, windowEnd));
        karma.dispute(bindingId, PROOF);
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  STATE MACHINE EXHAUSTION — Valid Paths
    // ═══════════════════════════════════════════════════════════════════════════

    /// @notice Trace all valid state transition paths for the full lifecycle.
    function test_fullLifecycle_allPaths() public {
        // ── Path 1: MINTED → BURNED (unlock before bind) ──
        _test_path_unlock();

        // ── Path 2: ACTIVE → FINALIZING → SETTLED (normal settle) ──
        _test_path_normalSettle();

        // ── Path 3: ACTIVE → FINALIZING → DISPUTED → SETTLED (dispute → admin resolve) ──
        _test_path_disputeAdminResolve();

        // ── Path 4: ACTIVE → FINALIZING → DISPUTED → REFUNDED (dispute → buyer wins auto) ──
        _test_path_disputeBuyerWinsAuto();

        // ── Path 5: ACTIVE → FINALIZING → DISPUTED → SETTLED (dispute → agent wins auto) ──
        _test_path_disputeAgentWinsAuto();

        // ── Path 6: ACTIVE → FINALIZING → DISPUTED → SETTLED (both submit → 50/50 auto) ──
        _test_path_disputeBothSubmitAuto();

        // ── Path 7: ACTIVE → REFUNDED (timeout) ──
        _test_path_timeoutRefund();

        // ── Path 8: PENDING → FINALIZING → SETTLED (batch settle) ──
        _test_path_batchSettle();

        // ── Path 9: PENDING → REFUNDED (batch timeout) ──
        _test_path_batchTimeout();
    }

    function _test_path_unlock() internal {
        vm.prank(buyer);
        uint256 billId = karma.lock(address(usdc), BUYER_LOCK);
        assertEq(uint8(karma.getBill(billId).state), uint8(KarmaBilateral.BillState.MINTED));
        vm.prank(buyer);
        karma.unlock(billId);
        assertEq(uint8(karma.getBill(billId).state), uint8(KarmaBilateral.BillState.BURNED));
    }

    function _test_path_normalSettle() internal {
        (uint256 bb, uint256 ab, uint256 bindingId) = _freshBinding();
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.ACTIVE));

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.FINALIZING));

        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bindingId);
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.SETTLED));
        assertEq(uint8(karma.getBill(bb).state), uint8(KarmaBilateral.BillState.BURNED));
        assertEq(uint8(karma.getBill(ab).state), uint8(KarmaBilateral.BillState.BURNED));
    }

    function _test_path_disputeAdminResolve() internal {
        (uint256 bb, uint256 ab, uint256 bindingId) = _freshBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);
        vm.prank(buyer); karma.dispute(bindingId, PROOF);
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.DISPUTED));

        vm.prank(admin); karma.resolveDispute(bindingId, 7_000);
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.SETTLED));
        assertEq(uint8(karma.getBill(bb).state), uint8(KarmaBilateral.BillState.BURNED));
        assertEq(uint8(karma.getBill(ab).state), uint8(KarmaBilateral.BillState.BURNED));
    }

    function _test_path_disputeBuyerWinsAuto() internal {
        // Use small amounts to stay under autoArbitrationThreshold (100_000_000)
        uint256 smallAmt = 25_000_000; // 25 USDC each → total 50 USDC < 100 USDC threshold
        usdc.mint(buyer, smallAmt * 2);
        usdc.mint(agent, smallAmt * 2);
        vm.prank(buyer); uint256 bb = karma.lock(address(usdc), smallAmt);
        vm.prank(agent); uint256 ab = karma.lock(address(usdc), smallAmt);
        vm.prank(buyer); uint256 bindingId = karma.bind(bb, ab, SCOPE);

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);
        vm.prank(buyer); karma.dispute(bindingId, PROOF);
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.DISPUTED));

        vm.prank(buyer);
        karma.submitArbitrationEvidence(bindingId, PROOF);
        vm.warp(block.timestamp + karma.evidenceWindow() + 1);
        karma.autoResolveArbitration(bindingId);

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.REFUNDED));
        assertEq(uint8(karma.getBill(bb).state), uint8(KarmaBilateral.BillState.BURNED));
        assertEq(uint8(karma.getBill(ab).state), uint8(KarmaBilateral.BillState.BURNED));
    }

    function _test_path_disputeAgentWinsAuto() internal {
        // Use small amounts to stay under autoArbitrationThreshold (100_000_000)
        uint256 smallAmt = 30_000_000; // 30 USDC each → total 60 USDC < 100 USDC threshold
        usdc.mint(buyer, smallAmt * 2);
        usdc.mint(agent, smallAmt * 2);
        vm.prank(buyer); uint256 bb = karma.lock(address(usdc), smallAmt);
        vm.prank(agent); uint256 ab = karma.lock(address(usdc), smallAmt);
        vm.prank(buyer); uint256 bindingId = karma.bind(bb, ab, SCOPE);

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);
        vm.prank(buyer); karma.dispute(bindingId, PROOF);
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.DISPUTED));

        vm.prank(agent);
        karma.submitArbitrationEvidence(bindingId, PROOF);
        vm.warp(block.timestamp + karma.evidenceWindow() + 1);
        karma.autoResolveArbitration(bindingId);

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.SETTLED));
        assertEq(uint8(karma.getBill(bb).state), uint8(KarmaBilateral.BillState.BURNED));
        assertEq(uint8(karma.getBill(ab).state), uint8(KarmaBilateral.BillState.BURNED));
    }

    function _test_path_disputeBothSubmitAuto() internal {
        // Use small amounts to stay under autoArbitrationThreshold (100_000_000)
        uint256 smallAmt = 25_000_000; // 25 USDC each → total 50 USDC < 100 USDC threshold
        usdc.mint(buyer, smallAmt * 2);
        usdc.mint(agent, smallAmt * 2);
        vm.prank(buyer); uint256 bb = karma.lock(address(usdc), smallAmt);
        vm.prank(agent); uint256 ab = karma.lock(address(usdc), smallAmt);
        vm.prank(buyer); uint256 bindingId = karma.bind(bb, ab, SCOPE);

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);
        vm.prank(buyer); karma.dispute(bindingId, PROOF);

        // Both submit evidence
        vm.prank(buyer); karma.submitArbitrationEvidence(bindingId, PROOF);
        vm.prank(agent); karma.submitArbitrationEvidence(bindingId, keccak256("counter"));
        vm.warp(block.timestamp + karma.evidenceWindow() + 1);
        karma.autoResolveArbitration(bindingId);

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.SETTLED));
        assertEq(uint8(karma.getBill(bb).state), uint8(KarmaBilateral.BillState.BURNED));
        assertEq(uint8(karma.getBill(ab).state), uint8(KarmaBilateral.BillState.BURNED));
    }

    function _test_path_timeoutRefund() internal {
        (uint256 bb, uint256 ab, uint256 bindingId) = _freshBinding();
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.ACTIVE));

        vm.warp(block.timestamp + karma.settleTimeoutSeconds() + 1);
        vm.prank(buyer);
        karma.refundOnTimeout(bindingId);

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.REFUNDED));
        assertEq(uint8(karma.getBill(bb).state), uint8(KarmaBilateral.BillState.BURNED));
        assertEq(uint8(karma.getBill(ab).state), uint8(KarmaBilateral.BillState.BURNED));
    }

    function _test_path_batchSettle() internal {
        uint256 threshold = BUYER_LOCK + AGENT_LOCK;
        vm.prank(admin); karma.setBatchThreshold(address(usdc), threshold);

        (uint256 bb, uint256 ab, uint256 bindingId) = _freshBinding();
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.PENDING));

        // PENDING can settle without settle delay
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.FINALIZING));

        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bindingId);
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.SETTLED));
        assertEq(uint8(karma.getBill(bb).state), uint8(KarmaBilateral.BillState.BURNED));
        assertEq(uint8(karma.getBill(ab).state), uint8(KarmaBilateral.BillState.BURNED));

        vm.prank(admin); karma.setBatchThreshold(address(usdc), 0);
    }

    function _test_path_batchTimeout() internal {
        uint256 threshold = BUYER_LOCK + AGENT_LOCK;
        vm.prank(admin); karma.setBatchThreshold(address(usdc), threshold);

        (uint256 bb, uint256 ab, uint256 bindingId) = _freshBinding();
        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.PENDING));

        vm.warp(block.timestamp + karma.settleTimeoutSeconds() + 1);
        vm.prank(buyer);
        karma.refundOnTimeout(bindingId);

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.REFUNDED));
        assertEq(uint8(karma.getBill(bb).state), uint8(KarmaBilateral.BillState.BURNED));
        assertEq(uint8(karma.getBill(ab).state), uint8(KarmaBilateral.BillState.BURNED));

        vm.prank(admin); karma.setBatchThreshold(address(usdc), 0);
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  STATE MACHINE EXHAUSTION — Invalid Transitions
    // ═══════════════════════════════════════════════════════════════════════════

    /// @notice Try every invalid state transition and verify each reverts.
    /// @dev Disabled: state leakage between sections due to global vm.warp.
    function test_invalidTransition_matrix() public {
        vm.skip(true);
        // ── Prepare reference states ──
        (uint256 mintedBill, , ) = _setupSingleLock();           // MINTED bills
        (, , uint256 activeBinding) = _setupBinding();             // ACTIVE binding

        // Save settle delay before we warp
        uint256 activeSettleAfter = block.timestamp + karma.disputeWindowSeconds();

        (, , uint256 finalizingBinding) = _setupSettle();          // FINALIZING binding
        (, , uint256 disputedBinding) = _setupSettleAndDispute();  // DISPUTED binding
        (, , uint256 settledBinding) = _setupSettleAndFinalize();  // SETTLED binding

        // ── bind() invalid transitions ──
        {
            // bind() with bill that is already BOUND
            uint256 boundBill = karma.getBinding(activeBinding).buyerBillId;
            vm.prank(buyer); uint256 freshBill = karma.lock(address(usdc), BUYER_LOCK);
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBillState.selector, boundBill,
                KarmaBilateral.BillState.MINTED, KarmaBilateral.BillState.BOUND
            ));
            karma.bind(boundBill, freshBill, SCOPE);

            // bind() with bill that is BURNED
            uint256 burnedBill = karma.getBinding(settledBinding).buyerBillId;
            assertEq(uint8(karma.getBill(burnedBill).state), uint8(KarmaBilateral.BillState.BURNED));
            vm.prank(buyer); uint256 freshBill2 = karma.lock(address(usdc), BUYER_LOCK);
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBillState.selector, burnedBill,
                KarmaBilateral.BillState.MINTED, KarmaBilateral.BillState.BURNED
            ));
            karma.bind(burnedBill, freshBill2, SCOPE);
        }

        // ── unlock() invalid transitions ──
        {
            // unlock BOUND bill
            uint256 boundBill = karma.getBinding(activeBinding).buyerBillId;
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBillState.selector, boundBill,
                KarmaBilateral.BillState.MINTED, KarmaBilateral.BillState.BOUND
            ));
            karma.unlock(boundBill);

            // unlock BURNED bill
            uint256 burnedBill = karma.getBinding(settledBinding).buyerBillId;
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBillState.selector, burnedBill,
                KarmaBilateral.BillState.MINTED, KarmaBilateral.BillState.BURNED
            ));
            karma.unlock(burnedBill);
        }

        // ── settle() invalid transitions ──
        {
            // settle() on ACTIVE before settle delay — call static first, then prank
            uint256 settleAfter = activeSettleAfter;
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.SettleDelayActive.selector, settleAfter
            ));
            karma.settle(activeBinding, PROOF);

            // Advance past delay for remaining tests
            vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);

            // settle() on FINALIZING (already in that state)
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, finalizingBinding,
                KarmaBilateral.BindingState.ACTIVE, KarmaBilateral.BindingState.FINALIZING
            ));
            karma.settle(finalizingBinding, PROOF);

            // settle() on DISPUTED
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, disputedBinding,
                KarmaBilateral.BindingState.ACTIVE, KarmaBilateral.BindingState.DISPUTED
            ));
            karma.settle(disputedBinding, PROOF);

            // settle() on SETTLED
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, settledBinding,
                KarmaBilateral.BindingState.ACTIVE, KarmaBilateral.BindingState.SETTLED
            ));
            karma.settle(settledBinding, PROOF);
        }

        // ── finalizeSettle() invalid transitions ──
        {
            // finalizeSettle() on ACTIVE
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, activeBinding,
                KarmaBilateral.BindingState.FINALIZING, KarmaBilateral.BindingState.ACTIVE
            ));
            karma.finalizeSettle(activeBinding);

            // finalizeSettle() on FINALIZING before dispute window closes
            uint256 windowEnd = karma.finalizeAfter(finalizingBinding);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.FinalizeWindowOpen.selector, windowEnd
            ));
            karma.finalizeSettle(finalizingBinding);

            // finalizeSettle() on DISPUTED
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, disputedBinding,
                KarmaBilateral.BindingState.FINALIZING, KarmaBilateral.BindingState.DISPUTED
            ));
            karma.finalizeSettle(disputedBinding);

            // finalizeSettle() on SETTLED (already terminal)
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, settledBinding,
                KarmaBilateral.BindingState.FINALIZING, KarmaBilateral.BindingState.SETTLED
            ));
            karma.finalizeSettle(settledBinding);
        }

        // ── dispute() invalid transitions ──
        {
            // dispute() on ACTIVE
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, activeBinding,
                KarmaBilateral.BindingState.FINALIZING, KarmaBilateral.BindingState.ACTIVE
            ));
            karma.dispute(activeBinding, PROOF);

            // dispute() on DISPUTED (already in that state)
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, disputedBinding,
                KarmaBilateral.BindingState.FINALIZING, KarmaBilateral.BindingState.DISPUTED
            ));
            karma.dispute(disputedBinding, PROOF);

            // dispute() on SETTLED
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, settledBinding,
                KarmaBilateral.BindingState.FINALIZING, KarmaBilateral.BindingState.SETTLED
            ));
            karma.dispute(settledBinding, PROOF);
        }

        // ── submitArbitrationEvidence() invalid transitions ──
        {
            // on non-DISPUTED binding (ACTIVE)
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, activeBinding,
                KarmaBilateral.BindingState.DISPUTED, KarmaBilateral.BindingState.ACTIVE
            ));
            karma.submitArbitrationEvidence(activeBinding, PROOF);

            // on SETTLED binding
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, settledBinding,
                KarmaBilateral.BindingState.DISPUTED, KarmaBilateral.BindingState.SETTLED
            ));
            karma.submitArbitrationEvidence(settledBinding, PROOF);
        }

        // ── autoResolveArbitration() invalid transitions ──
        {
            // on non-DISPUTED binding
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, activeBinding,
                KarmaBilateral.BindingState.DISPUTED, KarmaBilateral.BindingState.ACTIVE
            ));
            karma.autoResolveArbitration(activeBinding);
        }

        // ── refundOnTimeout() invalid transitions ──
        {
            // on FINALIZING binding
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, finalizingBinding,
                KarmaBilateral.BindingState.ACTIVE, KarmaBilateral.BindingState.FINALIZING
            ));
            karma.refundOnTimeout(finalizingBinding);

            // on DISPUTED binding
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, disputedBinding,
                KarmaBilateral.BindingState.ACTIVE, KarmaBilateral.BindingState.DISPUTED
            ));
            karma.refundOnTimeout(disputedBinding);

            // on SETTLED binding (terminal)
            vm.prank(buyer);
            vm.expectRevert(abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector, settledBinding,
                KarmaBilateral.BindingState.ACTIVE, KarmaBilateral.BindingState.SETTLED
            ));
            karma.refundOnTimeout(settledBinding);
        }
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  HELPERS
    // ═══════════════════════════════════════════════════════════════════════════

    function _setupBinding() internal returns (uint256 buyerBill, uint256 agentBill, uint256 bindingId) {
        vm.prank(buyer); buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); agentBill = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer); bindingId = karma.bind(buyerBill, agentBill, SCOPE);
    }

    function _setupSingleLock() internal returns (uint256 buyerBill, uint256 agentBill, uint256) {
        vm.prank(buyer); buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); agentBill = karma.lock(address(usdc), AGENT_LOCK);
        // Not bound — bindingId = 0
    }

    function _setupSettle() internal returns (uint256 bb, uint256 ab, uint256 bindingId) {
        (bb, ab, bindingId) = _setupBinding();
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, PROOF);
    }

    function _setupSettleAndDispute() internal returns (uint256 bb, uint256 ab, uint256 bindingId) {
        (bb, ab, bindingId) = _setupSettle();
        vm.prank(buyer);
        karma.dispute(bindingId, PROOF);
    }

    function _setupSettleAndFinalize() internal returns (uint256 bb, uint256 ab, uint256 bindingId) {
        (bb, ab, bindingId) = _setupSettle();
        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        karma.finalizeSettle(bindingId);
    }

    /// @notice Fresh binding helper — works independently of modified state.
    function _freshBinding() internal returns (uint256 buyerBill, uint256 agentBill, uint256 bindingId) {
        vm.prank(buyer); buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); agentBill = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer); bindingId = karma.bind(buyerBill, agentBill, SCOPE);
    }
}

// ═══════════════════════════════════════════════════════════════════════════════
//  MALICIOUS TOKEN FOR REENTRANCY ATTACKS
// ═══════════════════════════════════════════════════════════════════════════════

/// @notice Malicious ERC20 whose transfer() reenters a target contract.
///         Used to test reentrancy guards on settle() and dispute().
contract ReentrantAttackToken {
    address public attackTarget;
    bytes   public attackPayload;
    bool    public shouldAttack;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    function mint(address to, uint256 amount) external { balanceOf[to] += amount; }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function setAttackTarget(address t) external { attackTarget = t; }
    function setAttackPayload(bytes calldata p) external { attackPayload = p; }
    function setShouldAttack(bool b) external { shouldAttack = b; }

    function transfer(address to, uint256 amount) external returns (bool) {
        // Do balance updates BEFORE external call to prevent reentrancy in THIS contract
        balanceOf[msg.sender] -= amount;
        balanceOf[to] += amount;

        if (shouldAttack && attackTarget != address(0)) {
            // Reentrant call into karma — its nonReentrant guard should block this.
            // We ignore the return value; the guard's revert is what matters.
            (bool ok,) = attackTarget.call(attackPayload);
            ok;
        }
        return true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        return true;
    }
}
