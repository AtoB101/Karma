// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {KarmaBilateral}        from "../core/KarmaBilateral.sol";
import {KarmaAttestationGateway} from "../core/KarmaAttestationGateway.sol";
import {VerifierRegistry}      from "../core/VerifierRegistry.sol";
import {MockERC20}             from "./mocks/MockERC20.sol";

/// @notice Full integration test: KarmaBilateral ↔ KarmaAttestationGateway ↔ VerifierRegistry
contract KarmaBilateralAttestationTest is Test {

    KarmaBilateral          internal karma;
    KarmaAttestationGateway internal gateway;
    VerifierRegistry        internal registry;
    MockERC20               internal usdc;

    address internal admin      = makeAddr("admin");
    address internal arbitrator = makeAddr("arbitrator");
    address internal buyer      = makeAddr("buyer");
    address internal agent      = makeAddr("agent");
    address internal stranger   = makeAddr("stranger");

    uint256 internal verifier1Pk = 0xBEEF01;
    uint256 internal verifier2Pk = 0xBEEF02;
    uint256 internal verifier3Pk = 0xBEEF03;
    address internal verifier1;
    address internal verifier2;
    address internal verifier3;

    uint256 internal constant BUYER_LOCK = 100_000_000;
    uint256 internal constant AGENT_LOCK =  50_000_000;

    bytes32 internal constant SCOPE     = keccak256("task:legal-analysis-v1");
    bytes32 internal constant TASK_ID   = keccak256("task-001");
    bytes32 internal constant EVIDENCE  = keccak256("ipfs://QmProofHash");
    string  internal constant EVIDENCE_CID = "ipfs://QmProofHash";

    uint256 internal constant CHALLENGE_WINDOW = 1 hours;

    // ── Setup ─────────────────────────────────────────────────────────────────

    function setUp() public {
        verifier1 = vm.addr(verifier1Pk);
        verifier2 = vm.addr(verifier2Pk);
        verifier3 = vm.addr(verifier3Pk);

        // 1. Deploy VerifierRegistry (3-of-5 threshold)
        vm.startPrank(admin);
        registry = new VerifierRegistry(admin);
        registry.registerVerifier(verifier1, "https://v1.karma.network", 0);
        registry.registerVerifier(verifier2, "https://v2.karma.network", 0);
        registry.registerVerifier(verifier3, "https://v3.karma.network", 0);
        registry.setThresholds(3, 3); // 3-of-3 for this test suite

        // 2. Deploy KarmaBilateral
        usdc  = new MockERC20();
        karma = new KarmaBilateral(admin);
        karma.setTokenAllowed(address(usdc), true);

        // 3. Deploy KarmaAttestationGateway pointing to KarmaBilateral
        gateway = new KarmaAttestationGateway(
            address(registry),
            address(karma),
            arbitrator,
            CHALLENGE_WINDOW
        );

        // 4. Wire KarmaBilateral to accept gateway as the attestation caller
        karma.setAttestationGateway(address(gateway));
        vm.stopPrank();

        // Fund participants
        usdc.mint(buyer,    1_000_000_000);
        usdc.mint(agent,    1_000_000_000);
        usdc.mint(stranger,   500_000_000);
        vm.prank(buyer);   usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent);   usdc.approve(address(karma), type(uint256).max);
        vm.prank(stranger); usdc.approve(address(karma), type(uint256).max);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Wiring sanity
    // ─────────────────────────────────────────────────────────────────────────

    function test_wiring_gatewayPointsToBilateral() public view {
        assertEq(gateway.bilateralContract(), address(karma));
    }

    function test_wiring_bilateralPointsToGateway() public view {
        assertEq(karma.attestationGateway(), address(gateway));
    }

    function test_wiring_registryThreshold() public view {
        assertEq(registry.getRequiredThreshold(), 3);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  bindWithAttestation
    // ─────────────────────────────────────────────────────────────────────────

    function test_bindWithAttestation_setsFlags() public {
        (uint256 bb, uint256 ab, uint256 bindingId) = _setupAttestationBinding();

        assertTrue(karma.requiresAttestation(bindingId));
        assertEq(karma.bindingTaskId(bindingId), TASK_ID);
        assertEq(uint8(karma.getBill(bb).state), uint8(KarmaBilateral.BillState.BOUND));
        assertEq(uint8(karma.getBill(ab).state), uint8(KarmaBilateral.BillState.BOUND));
    }

    function test_bindWithAttestation_revertsIfNoGateway() public {
        // Remove gateway
        vm.prank(admin); karma.setAttestationGateway(address(0));

        vm.prank(buyer); uint256 bb = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 ab = karma.lock(address(usdc), AGENT_LOCK);

        vm.prank(buyer);
        vm.expectRevert(KarmaBilateral.GatewayNotSet.selector);
        karma.bindWithAttestation(bb, ab, SCOPE, TASK_ID);
    }

    function test_bindWithAttestation_revertsIfZeroTaskId() public {
        vm.prank(buyer); uint256 bb = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 ab = karma.lock(address(usdc), AGENT_LOCK);

        vm.prank(buyer);
        vm.expectRevert(KarmaBilateral.ZeroAmount.selector);
        karma.bindWithAttestation(bb, ab, SCOPE, bytes32(0));
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Attested settle() gate: direct call must be blocked
    // ─────────────────────────────────────────────────────────────────────────

    function test_settle_revertsIfAttestationRequiredAndCallerNotGateway() public {
        (, , uint256 bindingId) = _setupAttestationBinding();
        vm.warp(block.timestamp + CHALLENGE_WINDOW + 1);

        // Buyer tries to settle directly — must revert
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.AttestationRequired.selector, bindingId));
        karma.settle(bindingId, EVIDENCE);
    }

    function test_settle_revertsIfAttestationRequiredAndCallerIsAgent() public {
        (, , uint256 bindingId) = _setupAttestationBinding();
        vm.warp(block.timestamp + CHALLENGE_WINDOW + 1);

        vm.prank(agent);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.AttestationRequired.selector, bindingId));
        karma.settle(bindingId, EVIDENCE);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Full happy path: publish → attest ×3 → wait → settleWithAttestation
    // ─────────────────────────────────────────────────────────────────────────

    function test_fullAttestationFlow_settles() public {
        (, , uint256 bindingId) = _setupAttestationBinding();

        uint256 buyerBefore = usdc.balanceOf(buyer);
        uint256 agentBefore = usdc.balanceOf(agent);

        // Step A: publish evidence
        gateway.publishEvidence(TASK_ID, EVIDENCE, EVIDENCE_CID);
        assertEq(gateway.taskEvidence(TASK_ID), EVIDENCE);

        // Step B: 3 verifiers attest
        _submitAttestation(verifier1Pk, verifier1, TASK_ID, true);
        _submitAttestation(verifier2Pk, verifier2, TASK_ID, true);
        _submitAttestation(verifier3Pk, verifier3, TASK_ID, true);

        assertEq(gateway.validAttestationCount(TASK_ID), 3);
        assertTrue(gateway.isQuorumReached(TASK_ID));

        // Step C: wait for challenge window to close
        vm.warp(block.timestamp + CHALLENGE_WINDOW + 1);
        assertTrue(gateway.isChallengeWindowClosed(TASK_ID));

        // Step D: anyone can call settleWithAttestation
        gateway.settleWithAttestation(TASK_ID, bindingId, EVIDENCE);

        // Verify settlement
        KarmaBilateral.Binding memory b = karma.getBinding(bindingId);
        assertEq(uint8(b.state), uint8(KarmaBilateral.BindingState.SETTLED));
        assertEq(b.proofHash, EVIDENCE);

        // USDC released
        assertEq(usdc.balanceOf(buyer), buyerBefore + BUYER_LOCK);
        assertEq(usdc.balanceOf(agent), agentBefore + AGENT_LOCK);

        // Invariant holds
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Gate failures: quorum, window, challenge, hash mismatch
    // ─────────────────────────────────────────────────────────────────────────

    function test_settleWithAttestation_revertsIfQuorumNotReached() public {
        (, , uint256 bindingId) = _setupAttestationBinding();
        gateway.publishEvidence(TASK_ID, EVIDENCE, EVIDENCE_CID);

        // Only 2 of 3 attestations
        _submitAttestation(verifier1Pk, verifier1, TASK_ID, true);
        _submitAttestation(verifier2Pk, verifier2, TASK_ID, true);

        vm.warp(block.timestamp + CHALLENGE_WINDOW + 1);

        vm.expectRevert(
            abi.encodeWithSelector(KarmaAttestationGateway.InsufficientAttestations.selector, 2, 3)
        );
        gateway.settleWithAttestation(TASK_ID, bindingId, EVIDENCE);
    }

    function test_settleWithAttestation_revertsIfWindowOpen() public {
        (, , uint256 bindingId) = _setupAttestationBinding();
        gateway.publishEvidence(TASK_ID, EVIDENCE, EVIDENCE_CID);
        _submitAllAttestations(TASK_ID);

        // Don't warp — window still open
        vm.expectRevert(KarmaAttestationGateway.ChallengeWindowOpen.selector);
        gateway.settleWithAttestation(TASK_ID, bindingId, EVIDENCE);
    }

    function test_settleWithAttestation_revertsIfProofHashMismatch() public {
        (, , uint256 bindingId) = _setupAttestationBinding();
        gateway.publishEvidence(TASK_ID, EVIDENCE, EVIDENCE_CID);
        _submitAllAttestations(TASK_ID);
        vm.warp(block.timestamp + CHALLENGE_WINDOW + 1);

        bytes32 wrongProof = keccak256("wrong-evidence");
        vm.expectRevert(KarmaAttestationGateway.InvalidSignature.selector);
        gateway.settleWithAttestation(TASK_ID, bindingId, wrongProof);
    }

    function test_settleWithAttestation_revertsIfChallengeNotResolved() public {
        (, , uint256 bindingId) = _setupAttestationBinding();
        gateway.publishEvidence(TASK_ID, EVIDENCE, EVIDENCE_CID);
        _submitAllAttestations(TASK_ID);

        // Raise a challenge before window closes
        gateway.raiseChallenge(TASK_ID, "evidence_hash_mismatch", "ipfs://challenge");
        vm.warp(block.timestamp + CHALLENGE_WINDOW + 1);

        vm.expectRevert(KarmaAttestationGateway.SettlementBlocked.selector);
        gateway.settleWithAttestation(TASK_ID, bindingId, EVIDENCE);
    }

    function test_settleWithAttestation_revertsIfChallengeUpheld() public {
        (, , uint256 bindingId) = _setupAttestationBinding();
        gateway.publishEvidence(TASK_ID, EVIDENCE, EVIDENCE_CID);
        _submitAllAttestations(TASK_ID);
        gateway.raiseChallenge(TASK_ID, "bad_output", "ipfs://challenge");

        // Arbitrator upholds the challenge
        vm.prank(arbitrator);
        gateway.resolveChallenge(TASK_ID, true); // upheld

        vm.warp(block.timestamp + CHALLENGE_WINDOW + 1);

        vm.expectRevert(KarmaAttestationGateway.SettlementBlocked.selector);
        gateway.settleWithAttestation(TASK_ID, bindingId, EVIDENCE);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Challenge overruled → settlement proceeds
    // ─────────────────────────────────────────────────────────────────────────

    function test_settleWithAttestation_succeedsIfChallengeOverruled() public {
        (, , uint256 bindingId) = _setupAttestationBinding();
        gateway.publishEvidence(TASK_ID, EVIDENCE, EVIDENCE_CID);
        _submitAllAttestations(TASK_ID);
        gateway.raiseChallenge(TASK_ID, "dispute", "ipfs://challenge");

        // Arbitrator overrules the challenge
        vm.prank(arbitrator);
        gateway.resolveChallenge(TASK_ID, false); // overruled

        vm.warp(block.timestamp + CHALLENGE_WINDOW + 1);

        gateway.settleWithAttestation(TASK_ID, bindingId, EVIDENCE);

        assertEq(
            uint8(karma.getBinding(bindingId).state),
            uint8(KarmaBilateral.BindingState.SETTLED)
        );
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  canSettle view
    // ─────────────────────────────────────────────────────────────────────────

    function test_canSettle_falseBeforeAllConditions() public {
        _setupAttestationBinding();
        gateway.publishEvidence(TASK_ID, EVIDENCE, EVIDENCE_CID);

        assertFalse(gateway.canSettle(TASK_ID, EVIDENCE)); // quorum not reached
        _submitAllAttestations(TASK_ID);
        assertFalse(gateway.canSettle(TASK_ID, EVIDENCE)); // window still open
        vm.warp(block.timestamp + CHALLENGE_WINDOW + 1);
        assertTrue(gateway.canSettle(TASK_ID, EVIDENCE));  // all gates pass
    }

    function test_canSettle_falseOnWrongProofHash() public {
        _setupAttestationBinding();
        gateway.publishEvidence(TASK_ID, EVIDENCE, EVIDENCE_CID);
        _submitAllAttestations(TASK_ID);
        vm.warp(block.timestamp + CHALLENGE_WINDOW + 1);

        assertFalse(gateway.canSettle(TASK_ID, keccak256("wrong")));
        assertTrue(gateway.canSettle(TASK_ID, EVIDENCE));
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Standard (non-attested) binding unaffected
    // ─────────────────────────────────────────────────────────────────────────

    function test_standardBind_stillSettlesDirectly() public {
        vm.prank(buyer); uint256 bb = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 ab = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer); uint256 bindingId = karma.bind(bb, ab, SCOPE);

        assertFalse(karma.requiresAttestation(bindingId));

        vm.warp(block.timestamp + karma.disputeWindowSeconds() + 1);
        vm.prank(buyer);
        karma.settle(bindingId, EVIDENCE);

        assertEq(
            uint8(karma.getBinding(bindingId).state),
            uint8(KarmaBilateral.BindingState.SETTLED)
        );
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Verifier reputation tracking
    // ─────────────────────────────────────────────────────────────────────────

    function test_attestation_updatesVerifierReputation() public {
        _setupAttestationBinding();
        gateway.publishEvidence(TASK_ID, EVIDENCE, EVIDENCE_CID);
        _submitAttestation(verifier1Pk, verifier1, TASK_ID, true);

        (,,,, uint256 successCount,) = registry.verifiers(verifier1);
        assertEq(successCount, 1);
    }

    function test_attestation_tracksFalseAttestation() public {
        _setupAttestationBinding();
        gateway.publishEvidence(TASK_ID, EVIDENCE, EVIDENCE_CID);
        _submitAttestation(verifier1Pk, verifier1, TASK_ID, false); // votes FAIL

        (,,,,, uint256 falseCount) = registry.verifiers(verifier1);
        assertEq(falseCount, 1);
        assertEq(gateway.failAttestationCount(TASK_ID), 1);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  Helpers
    // ─────────────────────────────────────────────────────────────────────────

    function _setupAttestationBinding()
        internal
        returns (uint256 buyerBill, uint256 agentBill, uint256 bindingId)
    {
        vm.prank(buyer); buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); agentBill = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer); bindingId = karma.bindWithAttestation(buyerBill, agentBill, SCOPE, TASK_ID);
    }

    function _submitAttestation(uint256 pk, address verifier, bytes32 taskId, bool valid) internal {
        bytes32 evidenceHash = gateway.taskEvidence(taskId);
        string memory cid    = gateway.taskEvidenceCid(taskId);

        bytes32 structHash = keccak256(abi.encode(
            gateway.ATTESTATION_TYPEHASH(),
            taskId,
            evidenceHash,
            cid,
            verifier,
            block.chainid,
            address(gateway)
        ));
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", gateway.DOMAIN_SEPARATOR(), structHash));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(pk, digest);

        vm.prank(verifier);
        gateway.submitAttestation(taskId, v, r, s, valid);
    }

    function _submitAllAttestations(bytes32 taskId) internal {
        _submitAttestation(verifier1Pk, verifier1, taskId, true);
        _submitAttestation(verifier2Pk, verifier2, taskId, true);
        _submitAttestation(verifier3Pk, verifier3, taskId, true);
    }
}
