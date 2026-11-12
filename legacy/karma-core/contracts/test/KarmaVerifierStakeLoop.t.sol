// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaBilateral}           from "../core/KarmaBilateral.sol";
import {KarmaAttestationGateway}  from "../core/KarmaAttestationGateway.sol";
import {VerifierRegistry}         from "../core/VerifierRegistry.sol";
import {MockERC20}                from "./mocks/MockERC20.sol";

/// @notice Economic-security variant of the machine-verification loop: verifiers
///         must stake real USDC to become active, then attest a binding so it can
///         settle through KarmaAttestationGateway.
contract KarmaVerifierStakeLoopTest is Test {
    KarmaBilateral          internal karma;
    KarmaAttestationGateway internal gateway;
    VerifierRegistry        internal registry;
    MockERC20               internal usdc;

    address internal admin      = makeAddr("admin");
    address internal arbitrator = makeAddr("arbitrator");
    address internal buyer      = makeAddr("buyer");
    address internal agent      = makeAddr("agent");

    uint256 internal v1Pk = 0xBEEF01;
    uint256 internal v2Pk = 0xBEEF02;
    uint256 internal v3Pk = 0xBEEF03;
    address internal v1;
    address internal v2;
    address internal v3;

    uint256 internal constant BUYER_LOCK = 100_000_000; // 100 USDC
    uint256 internal constant AGENT_LOCK =  50_000_000; //  50 USDC
    uint256 internal constant MIN_STAKE  = 100_000_000; // 100 USDC
    uint256 internal constant REWARD     =  10_000_000; //  10 USDC

    bytes32 internal constant SCOPE       = keccak256("task:legal-analysis-v1");
    bytes32 internal constant TASK_ID     = keccak256("task-001");
    bytes32 internal constant EVIDENCE    = keccak256("ipfs://QmProofHash");
    string  internal constant EVIDENCE_CID = "ipfs://QmProofHash";

    function setUp() public {
        v1 = vm.addr(v1Pk);
        v2 = vm.addr(v2Pk);
        v3 = vm.addr(v3Pk);

        usdc = new MockERC20();

        vm.startPrank(admin);
        registry = new VerifierRegistry(admin);
        registry.setStakingConfig(address(usdc), MIN_STAKE, REWARD);
        registry.registerVerifier(v1, "https://v1.karma.network", 0);
        registry.registerVerifier(v2, "https://v2.karma.network", 0);
        registry.registerVerifier(v3, "https://v3.karma.network", 0);
        registry.setThresholds(3, 3);

        karma = new KarmaBilateral(admin);
        karma.setTokenAllowed(address(usdc), true);

        gateway = new KarmaAttestationGateway(address(registry), address(karma), arbitrator, 1 hours);
        karma.setAttestationGateway(address(gateway));
        registry.setAuthorizedCaller(address(gateway), true);
        vm.stopPrank();

        // Fund verifiers and make them stake real USDC to activate.
        usdc.mint(v1, 1_000_000_000);
        usdc.mint(v2, 1_000_000_000);
        usdc.mint(v3, 1_000_000_000);
        vm.startPrank(v1);
        usdc.approve(address(registry), type(uint256).max);
        registry.stake(MIN_STAKE);
        vm.stopPrank();
        vm.startPrank(v2);
        usdc.approve(address(registry), type(uint256).max);
        registry.stake(MIN_STAKE);
        vm.stopPrank();
        vm.startPrank(v3);
        usdc.approve(address(registry), type(uint256).max);
        registry.stake(MIN_STAKE);
        vm.stopPrank();

        usdc.mint(buyer, 1_000_000_000);
        usdc.mint(agent, 1_000_000_000);
        vm.prank(buyer); usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent); usdc.approve(address(karma), type(uint256).max);
    }

    function test_fullAttestationLoop_withRealStake() public {
        // Verifiers are active only because they deposited real stake.
        assertTrue(registry.isActiveVerifier(v1));
        assertTrue(registry.isActiveVerifier(v2));
        assertTrue(registry.isActiveVerifier(v3));
        (, , , uint256 stakeAmount, , , , ) = registry.verifiers(v1);
        assertEq(stakeAmount, MIN_STAKE);
        assertEq(usdc.balanceOf(address(registry)), 3 * MIN_STAKE);

        // lock + bindWithAttestation
        vm.prank(buyer); uint256 buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 agentBill = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer); uint256 bindingId = karma.bindWithAttestation(buyerBill, agentBill, SCOPE, TASK_ID);

        // evidence published on-chain
        vm.prank(buyer);
        gateway.publishEvidence(TASK_ID, EVIDENCE, EVIDENCE_CID);
        assertEq(gateway.taskEvidence(TASK_ID), EVIDENCE);

        // 3 staked verifiers sign EIP-712 and attest
        _attest(v1Pk, v1, true);
        _attest(v2Pk, v2, true);
        _attest(v3Pk, v3, true);
        assertEq(gateway.validAttestationCount(TASK_ID), 3);
        assertTrue(gateway.isQuorumReached(TASK_ID));

        // challenge window passes undisputed
        vm.warp(block.timestamp + 1 hours + 1);
        assertTrue(gateway.isChallengeWindowClosed(TASK_ID));

        uint256 buyerBefore = usdc.balanceOf(buyer);
        uint256 agentBefore = usdc.balanceOf(agent);

        // permissionless settlement through the attestation gate
        gateway.settleWithAttestation(TASK_ID, bindingId, EVIDENCE);

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.SETTLED));
        assertEq(usdc.balanceOf(buyer), buyerBefore);
        assertEq(usdc.balanceOf(agent), agentBefore + BUYER_LOCK + AGENT_LOCK);

        // verifier stake stays locked as slashable economic security
        assertEq(usdc.balanceOf(address(registry)), 3 * MIN_STAKE);
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    function _attest(uint256 pk, address verifier, bool valid) internal {
        bytes32 evidenceHash = gateway.taskEvidence(TASK_ID);
        string  memory cid   = gateway.taskEvidenceCid(TASK_ID);

        bytes32 structHash = keccak256(abi.encode(
            gateway.ATTESTATION_TYPEHASH(),
            TASK_ID,
            evidenceHash,
            cid,
            verifier,
            block.chainid,
            address(gateway)
        ));
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", gateway.DOMAIN_SEPARATOR(), structHash));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(pk, digest);

        vm.prank(verifier);
        gateway.submitAttestation(TASK_ID, v, r, s, valid);
    }
}

