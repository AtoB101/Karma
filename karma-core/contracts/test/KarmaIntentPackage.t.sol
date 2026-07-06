// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {KarmaBilateral} from "../core/KarmaBilateral.sol";
import {ScoringEngine} from "../core/ScoringEngine.sol";
import {EvidenceChain} from "../core/EvidenceChain.sol";
import {VerifierRegistry} from "../core/VerifierRegistry.sol";
import {Types} from "../libraries/Types.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

/// @title KarmaIntentPackageTest
/// @notice Integration + attack tests for IntentPackage, ScoringEngine,
///         EvidenceChain, and VerifierRegistry.
contract KarmaIntentPackageTest is Test {
    KarmaBilateral   internal karma;
    ScoringEngine    internal scores;
    EvidenceChain    internal evidence;
    VerifierRegistry internal verifierReg;
    MockERC20        internal usdc;
    MockERC20        internal karmaToken;

    address internal admin     = makeAddr("admin");
    address internal buyer     = makeAddr("buyer");
    address internal seller    = makeAddr("seller");
    address internal verifier  = makeAddr("verifier");
    address internal verifier2 = makeAddr("verifier2");
    address internal badActor  = makeAddr("badActor");
    address internal stranger  = makeAddr("stranger");

    uint256 internal constant PRICE = 100_000_000; // 100 USDC

    // ── Helpers ─────────────────────────────────────────────────────────

    function _buildIntent(
        address _buyer,
        address _seller,
        address _verifier,
        uint256 _amount
    ) internal view returns (Types.IntentPackage memory) {
        bytes32[] memory reqFields = new bytes32[](2);
        reqFields[0] = keccak256("confirmation");
        reqFields[1] = keccak256("completion_time");
        address[] memory noArb = new address[](0);

        return Types.IntentPackage({
            buyer:               _buyer,
            seller:              _seller,
            serviceType:         keccak256("food_delivery"),
            serviceCategory:     Types.ServiceCategory.LogisticsDelivery,
            requirements:        abi.encode("deliver within 30min"),
            amount:              _amount,
            penaltyRate:         1000,
            deadline:            block.timestamp + 1 hours,
            expiresAt:           block.timestamp + 2 hours,
            proofSchema:         keccak256("delivery_proof_v1"),
            requiredProofFields: reqFields,
            verifier:            _verifier,
            disputeWindow:       1 days,
            paymentSpecHash:     bytes32(0),
            deliverySpecHash:    bytes32(0),
            breachSpecHash:      bytes32(0),
            qualitySpecHash:     bytes32(0),
            disputeSpecHash:     bytes32(0),
            fullDocumentHash:    bytes32(0),
            schemaVersion:       bytes32(0),
            gracePeriod:         0,
            curePeriod:          0,
            acceptanceWindow:    0,
            milestoneAmounts:    new uint256[](0),
            milestoneIds:        new bytes32[](0),
            milestoneDeadlines:  new uint256[](0),
            maxPenalty:          0,
            deliverables:        new bytes32[](0),
            qualityStandard:     bytes32(0),
            breachDefinitions:   bytes32(0),
            maxCureAttempts:     0,
            allowPartialSettlement: false,
            bindingArbitration:  false,
            sellerMustStake:     false,
            buyerMustStake:      false,
            arbitrators:         noArb
        });
    }

    function _lockAndBind(
        address _buyer,
        address _seller,
        uint256 amount,
        address _verifier
    ) internal returns (uint256 bindingId) {
        // Lock buyer
        vm.prank(_buyer);
        uint256 buyerBill = karma.lock(address(usdc), amount);
        // Lock seller
        vm.prank(_seller);
        uint256 agentBill = karma.lock(address(usdc), amount);

        // Bind with intent
        Types.IntentPackage memory intent = _buildIntent(_buyer, _seller, _verifier, amount);
        vm.prank(_buyer);
        bindingId = karma.bindWithIntent(intent, buyerBill, agentBill);
    }

    // ── Setup ───────────────────────────────────────────────────────────

    function setUp() public {
        vm.startPrank(admin);
        karma       = new KarmaBilateral(admin);
        scores      = new ScoringEngine(admin);
        evidence    = new EvidenceChain(admin);
        verifierReg = new VerifierRegistry(admin);
        usdc        = new MockERC20();
        karmaToken  = new MockERC20();
        karma.setTokenAllowed(address(usdc), true);
        vm.stopPrank();

        // Fund participants
        usdc.mint(buyer,    1_000_000_000);
        usdc.mint(seller,   1_000_000_000);
        usdc.mint(badActor, 1_000_000_000);
        usdc.mint(stranger,  500_000_000);

        vm.prank(buyer);    usdc.approve(address(karma), type(uint256).max);
        vm.prank(seller);   usdc.approve(address(karma), type(uint256).max);
        vm.prank(badActor); usdc.approve(address(karma), type(uint256).max);
        vm.prank(stranger);  usdc.approve(address(karma), type(uint256).max);

        // Register verifier
        vm.prank(admin);
        verifierReg.registerVerifier(verifier, "https://verifier.example.com", 0);
        vm.prank(admin);
        verifierReg.registerVerifier(verifier2, "https://verifier2.example.com", 0);

        // Register parties in ScoringEngine
        vm.startPrank(admin);
        scores.registerParty(seller,   ScoringEngine.PartyType.SUPPLIER);
        scores.registerParty(buyer,    ScoringEngine.PartyType.BUYER);
        scores.registerParty(verifier, ScoringEngine.PartyType.VERIFIER);
        scores.registerParty(verifier2,ScoringEngine.PartyType.VERIFIER);
        vm.stopPrank();
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  INTENT PACKAGE — Happy Path
    // ═══════════════════════════════════════════════════════════════════════════

    function test_bindWithIntent_createsBinding() public {
        uint256 id = _lockAndBind(buyer, seller, PRICE, address(0));
        KarmaBilateral.Binding memory b = karma.getBinding(id);
        assertEq(b.buyerBillId, 1);
        assertEq(b.agentBillId, 2);
        assertEq(uint8(b.state), uint8(KarmaBilateral.BindingState.ACTIVE));
    }

    function test_intentPackage_storedOnChain() public {
        uint256 id = _lockAndBind(buyer, seller, PRICE, address(0));
        Types.IntentPackage memory ip = karma.getIntentPackage(id);
        assertEq(ip.buyer, buyer);
        assertEq(ip.seller, seller);
        assertEq(ip.amount, PRICE);
        assertEq(ip.serviceType, keccak256("food_delivery"));
    }

    function test_fullFlow_lockBindSettle() public {
        uint256 id = _lockAndBind(buyer, seller, PRICE, address(0));
        bytes32 proof = keccak256("proof:delivered");

        // Fast-forward past settle delay
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(seller);
        karma.settle(id, proof);

        KarmaBilateral.Binding memory b = karma.getBinding(id);
        assertTrue(b.proofHash != bytes32(0));
    }

    function test_bindWithIntent_withVerifier() public {
        uint256 id = _lockAndBind(buyer, seller, PRICE, verifier);
        // Verifier requirement should be registered
        assertTrue(karma.requiresAttestation(id));
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  INTENT PACKAGE — Reverts (Validation)
    // ═══════════════════════════════════════════════════════════════════════════

    function test_revert_buyerMismatch() public {
        vm.prank(buyer);
        uint256 bBill = karma.lock(address(usdc), PRICE);
        vm.prank(seller);
        uint256 aBill = karma.lock(address(usdc), PRICE);

        // Intent says buyer is stranger, but bill belongs to buyer
        Types.IntentPackage memory intent = _buildIntent(stranger, seller, address(0), PRICE);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.IntentPartyMismatch.selector, "buyer"));
        karma.bindWithIntent(intent, bBill, aBill);
    }

    function test_revert_sellerMismatch() public {
        vm.prank(buyer);
        uint256 bBill = karma.lock(address(usdc), PRICE);
        vm.prank(seller);
        uint256 aBill = karma.lock(address(usdc), PRICE);

        // Intent says seller is stranger, but bill belongs to seller
        Types.IntentPackage memory intent = _buildIntent(buyer, stranger, address(0), PRICE);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.IntentPartyMismatch.selector, "seller"));
        karma.bindWithIntent(intent, bBill, aBill);
    }

    function test_revert_amountMismatch() public {
        vm.prank(buyer);
        uint256 bBill = karma.lock(address(usdc), PRICE);
        vm.prank(seller);
        uint256 aBill = karma.lock(address(usdc), PRICE);

        // Intent says 50, bills have 100
        Types.IntentPackage memory intent = _buildIntent(buyer, seller, address(0), 50_000_000);
        vm.prank(buyer);
        vm.expectRevert(
            abi.encodeWithSelector(KarmaBilateral.IntentAmountMismatch.selector, 50_000_000, PRICE, PRICE)
        );
        karma.bindWithIntent(intent, bBill, aBill);
    }

    function test_revert_expiredIntent() public {
        vm.prank(buyer);
        uint256 bBill = karma.lock(address(usdc), PRICE);
        vm.prank(seller);
        uint256 aBill = karma.lock(address(usdc), PRICE);

        Types.IntentPackage memory intent = _buildIntent(buyer, seller, address(0), PRICE);
        intent.expiresAt = block.timestamp - 1; // already expired

        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.IntentExpired.selector, intent.expiresAt));
        karma.bindWithIntent(intent, bBill, aBill);
    }

    function test_revert_billNotMinted() public {
        uint256 nonexistentBill = 999;
        vm.prank(buyer);
        uint256 bBill = karma.lock(address(usdc), PRICE);

        Types.IntentPackage memory intent = _buildIntent(buyer, seller, address(0), PRICE);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.BillNotMinted.selector, nonexistentBill));
        karma.bindWithIntent(intent, bBill, nonexistentBill);
    }

    function test_revert_notBillOwner() public {
        vm.prank(buyer);
        uint256 bBill = karma.lock(address(usdc), PRICE);
        vm.prank(seller);
        uint256 aBill = karma.lock(address(usdc), PRICE);

        Types.IntentPackage memory intent = _buildIntent(buyer, seller, address(0), PRICE);
        // stranger tries to bind buyer's bill
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.NotBillOwner.selector, bBill));
        karma.bindWithIntent(intent, bBill, aBill);
    }

    function test_revert_zeroServiceType() public {
        vm.prank(buyer);
        uint256 bBill = karma.lock(address(usdc), PRICE);
        vm.prank(seller);
        uint256 aBill = karma.lock(address(usdc), PRICE);

        Types.IntentPackage memory intent = _buildIntent(buyer, seller, address(0), PRICE);
        intent.serviceType = bytes32(0);

        vm.prank(buyer);
        vm.expectRevert(KarmaBilateral.ZeroAmount.selector);
        karma.bindWithIntent(intent, bBill, aBill);
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  ATTACK SCENARIOS — Agent (Seller) Lying
    // ═══════════════════════════════════════════════════════════════════════════

    /// @notice Agent tries to claim a different service type to trick binding.
    function test_attack_agentLiesAboutServiceType() public {
        vm.prank(buyer);
        uint256 bBill = karma.lock(address(usdc), PRICE);
        vm.prank(seller);
        uint256 aBill = karma.lock(address(usdc), PRICE);

        // Agent creates intent pretending to do "flight_booking" but buyer locked for "food_delivery"
        // The buyer is the one calling bindWithIntent, so agent can't inject a fake intent.
        // The attack vector: agent tricks buyer into signing a mismatched intent.
        // In our flow, buyer controls the bind call — they verify the intent locally first.
        Types.IntentPackage memory intent = _buildIntent(buyer, seller, address(0), PRICE);
        intent.serviceType = keccak256("flight_booking");

        // Buyer is careful and binds correctly — no exploit possible
        vm.prank(buyer);
        uint256 id = karma.bindWithIntent(intent, bBill, aBill);

        Types.IntentPackage memory stored = karma.getIntentPackage(id);
        assertEq(stored.serviceType, keccak256("flight_booking"));
        // The intent IS the contract — what was bound is what executes.
    }

    function test_attack_agentSettlesBeforeCompletion() public {
        // Manual setup
        vm.prank(buyer);
        uint256 bBill = karma.lock(address(usdc), PRICE);
        vm.prank(seller);
        uint256 aBill = karma.lock(address(usdc), PRICE);

        Types.IntentPackage memory intent = _buildIntent(buyer, seller, address(0), PRICE);
        vm.prank(buyer);
        uint256 id = karma.bindWithIntent(intent, bBill, aBill);

        bytes32 fakeProof = keccak256("fake:not_delivered");

        // Agent tries to settle immediately — seller IS the agent, so access check
        // passes first, then settle delay check fails
        vm.prank(seller);
        vm.expectRevert(); // Either SettleDelayActive or NoDisputeAccess — both block premature settle
        karma.settle(id, fakeProof);
    }

    /// @notice Agent tries to double-settle (settle twice on same binding).
    function test_attack_doubleSettle() public {
        uint256 id = _lockAndBind(buyer, seller, PRICE, address(0));
        bytes32 proof = keccak256("proof:delivered");

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(seller);
        karma.settle(id, proof);

        // After settle, state is FINALIZING (not ACTIVE) — can't settle again
        vm.prank(seller);
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector,
                id,
                KarmaBilateral.BindingState.ACTIVE,
                KarmaBilateral.BindingState.FINALIZING
            )
        );
        karma.settle(id, proof);
    }

    /// @notice Agent tries to dispute their own binding — only buyer can dispute.
    function test_attack_agentCannotDispute() public {
        // Manual setup to avoid batch threshold
        vm.prank(buyer);
        uint256 bBill = karma.lock(address(usdc), PRICE);
        vm.prank(seller);
        uint256 aBill = karma.lock(address(usdc), PRICE);

        Types.IntentPackage memory intent = _buildIntent(buyer, seller, address(0), PRICE);
        vm.prank(buyer);
        uint256 id = karma.bindWithIntent(intent, bBill, aBill);

        // First settle (puts binding into FINALIZING, required for dispute)
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(seller);
        karma.settle(id, keccak256("proof:done"));

        // Agent tries to dispute — rejected: only buyer can dispute
        vm.prank(seller);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.NoDisputeAccess.selector, id));
        karma.dispute(id, bytes32(0));
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  ATTACK SCENARIOS — Buyer Lying
    // ═══════════════════════════════════════════════════════════════════════════

    /// @notice Buyer CAN dispute within the dispute window after settlement.
    ///         This is the legitimate buyer protection flow — if service wasn't
    ///         actually delivered, the buyer challenges during FINALIZING.
    function test_attack_buyerDisputesAfterDelivery() public {
        uint256 id = _lockAndBind(buyer, seller, PRICE, address(0));
        bytes32 proof = keccak256("proof:delivered");

        // Seller settles
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(seller);
        karma.settle(id, proof);

        // Binding is now FINALIZING — buyer CAN dispute within the dispute window
        KarmaBilateral.Binding memory b = karma.getBinding(id);
        assertEq(uint8(b.state), uint8(KarmaBilateral.BindingState.FINALIZING));

        // Buyer disputes (legitimate protection)
        vm.prank(buyer);
        karma.dispute(id, keccak256("challenge:not_as_described"));

        // Now in DISPUTED state
        b = karma.getBinding(id);
        assertEq(uint8(b.state), uint8(KarmaBilateral.BindingState.DISPUTED));
    }

    /// @notice Buyer disputes too late — dispute window closed after finalization.
    function test_attack_buyerDisputesTooLate() public {
        uint256 id = _lockAndBind(buyer, seller, PRICE, address(0));
        bytes32 proof = keccak256("proof:delivered");

        // Seller settles after settle delay (30 min)
        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(seller);
        karma.settle(id, proof);

        // Warp past settleSubmittedAt + disputeWindow (24 hours)
        vm.warp(block.timestamp + karma.disputeWindow() + 1);
        vm.prank(seller);
        karma.finalizeSettle(id);

        // Can't dispute after finalization — state is SETTLED
        vm.prank(buyer);
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaBilateral.WrongBindingState.selector,
                id,
                KarmaBilateral.BindingState.FINALIZING,
                KarmaBilateral.BindingState.SETTLED
            )
        );
        karma.dispute(id, bytes32(0));
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  ATTACK SCENARIOS — Verifier Lying / Collusion
    // ═══════════════════════════════════════════════════════════════════════════

    /// @notice Unregistered verifier can't submit evidence.
    function test_attack_unregisteredVerifier() public {
        // EvidenceChain only allows authorized verifier
        vm.prank(stranger);
        vm.expectRevert(EvidenceChain.Unauthorized.selector);
        evidence.submitEvidence(1, "fake", bytes32(0));
    }

    /// @notice Verifier submits fake evidence — slashable via admin.
    ///         (Admin slashing is tested separately in VerifierRegistry tests.)
    ///         This test shows the evidence is stored but can be invalidated.
    function test_attack_verifierSubmitsFakeEvidence() public {
        vm.prank(admin);
        evidence.setAuthorizedVerifier(verifier);

        vm.prank(verifier);
        uint256 eid = evidence.submitEvidence(1, hex"dead", keccak256("delivery_proof"));
        assertTrue(evidence.getEvidence(eid).valid);

        // Admin invalidates it
        vm.prank(admin);
        evidence.invalidateEvidence(eid, "fake_proof_detected");
        assertFalse(evidence.getEvidence(eid).valid);
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  EVIDENCE CHAIN
    // ═══════════════════════════════════════════════════════════════════════════

    function test_evidenceChain_submitSingle() public {
        vm.prank(admin);
        evidence.setAuthorizedVerifier(verifier);

        vm.prank(verifier);
        uint256 eid = evidence.submitEvidence(42, hex"abcd", keccak256("field_a"));
        assertEq(eid, 1);
        assertEq(evidence.getBindingEvidenceCount(42), 1);
    }

    function test_evidenceChain_submitBatch() public {
        vm.prank(admin);
        evidence.setAuthorizedVerifier(verifier);

        bytes[] memory data = new bytes[](2);
        data[0] = hex"aa";
        data[1] = hex"bb";
        bytes32[] memory fields = new bytes32[](2);
        fields[0] = keccak256("field_x");
        fields[1] = keccak256("field_y");

        vm.prank(verifier);
        uint256[] memory ids = evidence.submitEvidenceBatch(10, data, fields);
        assertEq(ids.length, 2);
        assertEq(ids[0], 1);
        assertEq(ids[1], 2);

        Types.Evidence[] memory all = evidence.getBindingEvidence(10);
        assertEq(all.length, 2);
        assertEq(all[0].fieldHash, fields[0]);
        assertEq(all[1].fieldHash, fields[1]);
    }

    function test_evidenceChain_invalidate() public {
        vm.prank(admin);
        evidence.setAuthorizedVerifier(verifier);

        vm.prank(verifier);
        uint256 eid = evidence.submitEvidence(1, hex"beef", keccak256("key"));

        vm.prank(admin);
        evidence.invalidateEvidence(eid, "invalid:timestamp_mismatch");

        assertFalse(evidence.getEvidence(eid).valid);
    }

    function test_evidenceChain_batchMismatchReverts() public {
        vm.prank(admin);
        evidence.setAuthorizedVerifier(verifier);

        bytes[] memory data = new bytes[](2);
        bytes32[] memory fields = new bytes32[](1);
        fields[0] = keccak256("only_one");

        vm.prank(verifier);
        vm.expectRevert("Length mismatch");
        evidence.submitEvidenceBatch(1, data, fields);
    }

    function test_evidenceChain_totalCounter() public {
        vm.prank(admin);
        evidence.setAuthorizedVerifier(verifier);

        vm.startPrank(verifier);
        evidence.submitEvidence(1, hex"01", keccak256("a"));
        evidence.submitEvidence(1, hex"02", keccak256("b"));
        evidence.submitEvidence(2, hex"03", keccak256("c"));
        vm.stopPrank();

        assertEq(evidence.totalEvidence(), 3);
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  SCORING ENGINE
    // ═══════════════════════════════════════════════════════════════════════════

    function test_scoring_initialScore() public {
        uint256 score = scores.getReputationScore(seller);
        assertEq(score, 5000); // DEFAULT_SCORE
    }

    function test_scoring_settlementBoostsSeller() public {
        vm.prank(admin);
        scores.setAuthorizedSettler(address(this));

        scores.recordSettlement(seller, buyer, address(0), true, 10000);
        uint256 score = scores.getReputationScore(seller);
        assertGt(score, 5000);
    }

    function test_scoring_lateSettlementDoesNotBoost() public {
        vm.prank(admin);
        scores.setAuthorizedSettler(address(this));

        scores.recordSettlement(seller, buyer, address(0), false, 10000);
        uint256 score = scores.getReputationScore(seller);
        // Late completion doesn't add penalty but doesn't boost
        assertEq(score, 5000); // was 5000 + 0 delta = 5000
    }

    function test_scoring_disputeLost_hurtsSeller() public {
        vm.prank(admin);
        scores.setAuthorizedSettler(address(this));

        // Seller loses dispute with penalty
        scores.recordDisputeResolution(seller, buyer, address(0), false, true);
        uint256 score = scores.getReputationScore(seller);
        assertLt(score, 5000);
    }

    function test_scoring_disputeWon_maintainsSeller() public {
        vm.prank(admin);
        scores.setAuthorizedSettler(address(this));

        // Seller wins dispute
        scores.recordDisputeResolution(seller, buyer, address(0), true, false);
        uint256 score = scores.getReputationScore(seller);
        assertGt(score, 5000); // small boost for winning
    }

    function test_scoring_verifierSlashed() public {
        vm.prank(admin);
        scores.recordVerifierSlashed(verifier);

        Types.ScoringVector memory sv = scores.getScore(verifier);
        assertEq(sv.slashedCount, 1);
        assertLt(sv.reputationScore, 5000);
    }

    function test_scoring_maxScoreCapped() public {
        vm.prank(admin);
        scores.setAuthorizedSettler(address(this));

        // Settle 1000 times — should cap at 10000
        for (uint256 i = 0; i < 1000; i++) {
            scores.recordSettlement(seller, buyer, address(0), true, 10000);
        }
        uint256 score = scores.getReputationScore(seller);
        assertEq(score, 10000);
    }

    function test_scoring_isHighReputation() public {
        vm.prank(admin);
        scores.setAuthorizedSettler(address(this));

        // Boost seller to high reputation
        for (uint256 i = 0; i < 200; i++) {
            scores.recordSettlement(seller, buyer, address(0), true, 10000);
        }
        assertTrue(scores.isHighReputation(seller));
    }

    function test_scoring_unregisteredParty_skipped() public {
        vm.prank(admin);
        scores.setAuthorizedSettler(address(this));

        // stranger is not registered — scoring should skip without revert
        scores.recordSettlement(stranger, buyer, address(0), true, 10000);
        assertEq(scores.getReputationScore(stranger), 0); // never set
    }

    // ═══════════════════════════════════════════════════════════════════════════
    //  VERIFIER REGISTRY — Stake / Slash / Rewards
    // ═══════════════════════════════════════════════════════════════════════════

    function test_verifierRegistry_setStakingConfig() public {
        vm.prank(admin);
        verifierReg.setStakingConfig(address(karmaToken), 100_000_000, 500_000);
        assertEq(verifierReg.minStake(), 100_000_000);
        assertEq(verifierReg.verificationReward(), 500_000);
    }

    function test_verifierRegistry_stake() public {
        vm.prank(admin);
        verifierReg.setStakingConfig(address(karmaToken), 100_000_000, 500_000);

        karmaToken.mint(verifier, 1_000_000_000);
        vm.startPrank(verifier);
        karmaToken.approve(address(verifierReg), type(uint256).max);
        verifierReg.stake(200_000_000);
        vm.stopPrank();

        (, , , uint256 stakeAmt, , , , ) = verifierReg.verifiers(verifier);
        assertEq(stakeAmt, 200_000_000);
    }

    function test_verifierRegistry_unstake_belowMinimumReverts() public {
        vm.prank(admin);
        verifierReg.setStakingConfig(address(karmaToken), 100_000_000, 500_000);

        karmaToken.mint(verifier, 1_000_000_000);
        vm.startPrank(verifier);
        karmaToken.approve(address(verifierReg), type(uint256).max);
        verifierReg.stake(150_000_000);

        // Try to unstake 100m — would leave 50m < 100m minStake
        vm.expectRevert(VerifierRegistry.InsufficientStake.selector);
        verifierReg.unstake(100_000_000);
        vm.stopPrank();
    }

    function test_verifierRegistry_unstake_partial() public {
        vm.prank(admin);
        verifierReg.setStakingConfig(address(karmaToken), 100_000_000, 500_000);

        karmaToken.mint(verifier, 1_000_000_000);
        vm.startPrank(verifier);
        karmaToken.approve(address(verifierReg), type(uint256).max);
        verifierReg.stake(300_000_000);

        // Unstake 150m — leaves 150m >= 100m minStake
        verifierReg.unstake(150_000_000);
        vm.stopPrank();

        (, , , uint256 stakeAmt, , , , ) = verifierReg.verifiers(verifier);
        assertEq(stakeAmt, 150_000_000);
    }

    function test_verifierRegistry_slash_belowMinimum_deactivates() public {
        vm.prank(admin);
        verifierReg.setStakingConfig(address(karmaToken), 100_000_000, 500_000);

        karmaToken.mint(verifier, 1_000_000_000);
        vm.startPrank(verifier);
        karmaToken.approve(address(verifierReg), type(uint256).max);
        verifierReg.stake(150_000_000);
        vm.stopPrank();

        // Admin slashes 100m — leaves 50m < 100m minStake → deactivates
        vm.prank(admin);
        verifierReg.slash(verifier, 100_000_000, "false_attestation");

        (, , bool active, uint256 stakeAmt, , , , ) = verifierReg.verifiers(verifier);
        assertEq(stakeAmt, 50_000_000);
        assertFalse(active);
    }

    function test_verifierRegistry_reward() public {
        vm.prank(admin);
        verifierReg.setStakingConfig(address(karmaToken), 100_000_000, 500_000);

        karmaToken.mint(address(verifierReg), 10_000_000);
        vm.prank(admin);
        verifierReg.rewardVerifier(verifier, 500_000);

        assertEq(karmaToken.balanceOf(verifier), 500_000);
    }

    function test_verifierRegistry_stakeWithoutTokenSet_reverts() public {
        vm.prank(verifier);
        vm.expectRevert(VerifierRegistry.StakingTokenNotSet.selector);
        verifierReg.stake(100);
    }
}
