// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {VerifierRegistry} from "./VerifierRegistry.sol";

/// @notice Minimal payment-contract interface consumed by the Gateway.
///        Full interface in INonCustodialAgentPayment.sol.
interface IPaymentSettlement {
    function confirmBill(uint256 billId) external;
    function getBill(uint256 billId)
        external
        view
        returns (
            uint256 billId_,
            uint256 batchId,
            address buyer,
            address seller,
            address token,
            uint256 amount,
            uint256 sellerBond,
            bytes32 scopeHash,
            string memory proofHash,
            uint8   status,
            uint256 createdAt,
            uint256 deadline
        );
}

/// @title KarmaAttestationGateway
/// @notice Settlement-permission layer that gates NonCustodialAgentPayment
///         confirmBill calls behind N-of-M verifier attestations and a
///         challenge window. It wraps the existing payment contract without
///         modifying it.
/// @dev   This contract is the "decentralized settlement gate":
///        1. Evidence is published (immutable record of the task output).
///        2. Verifiers submit EIP-712 attestations (N of M required).
///        3. A challenge window opens; anyone may raise a dispute.
///        4. Only after the window closes undisputed can settleWithAttestation
///           forward confirmBill to the underlying payment contract.
contract KarmaAttestationGateway {
    // ─────────────────────────────── Errors ──────────────────────────────────

    error Unauthorized();
    error EvidenceAlreadyPublished();
    error VerifierNotActive(address verifier);
    error AttestationAlreadySubmitted(address verifier, bytes32 taskId);
    error InvalidSignature();
    error InsufficientAttestations(uint256 valid, uint256 required);
    error QuorumNotReached();
    error ChallengeWindowOpen();
    error ChallengeAlreadyRaised();
    error NoActiveChallenge();
    error ChallengeResolved();
    error NotArbitrator();
    error InvalidAddress();
    error TaskNotFound();

    // ═══════════════════════════ State ═══════════════════════════════════════

    /// @notice The verifier registry that authorizes attesting nodes.
    VerifierRegistry public immutable registry;

    /// @notice The underlying NonCustodialAgentPayment contract.
    address public immutable paymentContract;

    /// @notice Address authorized to resolve challenges.
    address public immutable arbitrator;

    /// @notice Default challenge-window duration in seconds.
    uint256 public challengeWindowDuration;

    // ─────────────────────── Per-Task State ──────────────────────────────────

    /// @notice taskId → evidence hash committed at publication time.
    mapping(bytes32 taskId => bytes32 evidenceHash) public taskEvidence;

    /// @notice taskId → evidence IPFS/Arweave CID.
    mapping(bytes32 taskId => string cid) public taskEvidenceCid;

    /// @notice taskId → Unix timestamp when challenge window ends.
    mapping(bytes32 taskId => uint256) public challengeEnd;

    /// @notice taskId → whether a challenge was raised.
    mapping(bytes32 taskId => bool) public challenged;

    /// @notice taskId → challenge resolution status (true = upheld, false = overruled).
    mapping(bytes32 taskId => bool) public challengeUpheld;

    /// @notice taskId → challenge resolution (true = resolved).
    mapping(bytes32 taskId => bool) public challengeResolved;

    /// @notice taskId → verifier → has submitted attestation.
    mapping(bytes32 taskId => mapping(address => bool)) public attestationSubmitted;

    /// @notice taskId → count of valid STRUCT_OK attestations received.
    mapping(bytes32 taskId => uint256) public validAttestationCount;

    /// @notice taskId → count of STRUCT_FAIL attestations received.
    mapping(bytes32 taskId => uint256) public failAttestationCount;

    // ──────────────────── Attestation Type Hash ─────────────────────────────

    /// @dev EIP-712 type hash for KarmaAttestation.
    bytes32 public constant ATTESTATION_TYPEHASH = keccak256(
        "KarmaAttestation(bytes32 taskId,bytes32 evidenceHash,string cid,address verifier,uint256 chainId,address verifyingContract)"
    );

    bytes32 public immutable DOMAIN_SEPARATOR;

    // ──────────────────────────── Events ────────────────────────────────────

    event EvidencePublished(
        bytes32 indexed taskId,
        bytes32 evidenceHash,
        string cid
    );

    event AttestationSubmitted(
        bytes32 indexed taskId,
        address indexed verifier,
        bool valid
    );

    event SettlementApproved(
        bytes32 indexed taskId,
        uint256 billId
    );

    event ChallengeRaised(
        bytes32 indexed taskId,
        address indexed challenger,
        string reason,
        string evidenceCid
    );

    event ChallengeResolvedEvent(
        bytes32 indexed taskId,
        bool upheld,
        address arbitrator
    );

    event ChallengeWindowDurationUpdated(uint256 newDuration);

    // ──────────────────────────── Constructor ───────────────────────────────

    /// @param _registry Address of the VerifierRegistry contract.
    /// @param _paymentContract Address of NonCustodialAgentPayment.
    /// @param _arbitrator Address authorized to resolve challenges.
    /// @param _challengeWindowDuration Default challenge window in seconds.
    constructor(
        address _registry,
        address _paymentContract,
        address _arbitrator,
        uint256 _challengeWindowDuration
    ) {
        if (
            _registry == address(0) ||
            _paymentContract == address(0) ||
            _arbitrator == address(0)
        ) revert InvalidAddress();

        registry = VerifierRegistry(_registry);
        paymentContract = _paymentContract;
        arbitrator = _arbitrator;
        challengeWindowDuration = _challengeWindowDuration;

        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                keccak256(
                    "EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)"
                ),
                keccak256("KarmaAttestationGateway"),
                keccak256("1"),
                block.chainid,
                address(this)
            )
        );
    }

    // ═══════════════════════════ Evidence ════════════════════════════════════

    /// @notice Publish evidence for a task before attestations begin.
    ///         Creates an immutable on-chain record of the evidence hash + CID.
    /// @param taskId Unique task identifier.
    /// @param evidenceHash SHA-256 of the evidence bundle.
    /// @param _cid IPFS or Arweave content identifier for full evidence.
    function publishEvidence(
        bytes32 taskId,
        bytes32 evidenceHash,
        string calldata _cid
    ) external {
        if (taskEvidence[taskId] != bytes32(0)) revert EvidenceAlreadyPublished();
        taskEvidence[taskId] = evidenceHash;
        taskEvidenceCid[taskId] = _cid;
        // Challenge window starts from the moment of evidence publication.
        challengeEnd[taskId] = block.timestamp + challengeWindowDuration;
        emit EvidencePublished(taskId, evidenceHash, _cid);
    }

    // ═══════════════════════════ Attestation ═════════════════════════════════

    /// @notice Submit a single EIP-712 signed attestation for a task.
    /// @param taskId Unique task identifier.
    /// @param v Signature recovery id.
    /// @param r Signature r component.
    /// @param s Signature s component.
    /// @param valid True = STRUCT_OK, False = STRUCT_FAIL.
    /// @return accepted True if attestation was accepted.
    function submitAttestation(
        bytes32 taskId,
        uint8 v,
        bytes32 r,
        bytes32 s,
        bool valid
    ) external returns (bool accepted) {
        // 1. Evidence must be published.
        bytes32 evidenceHash = taskEvidence[taskId];
        if (evidenceHash == bytes32(0)) revert TaskNotFound();

        // 2. Verifier must be active in the registry.
        if (!registry.isActiveVerifier(msg.sender)) revert VerifierNotActive(msg.sender);

        // 3. Verifier must not have already attested for this task.
        if (attestationSubmitted[taskId][msg.sender]) {
            revert AttestationAlreadySubmitted(msg.sender, taskId);
        }

        // 4. Recover signer from EIP-712 signature.
        bytes32 structHash = keccak256(
            abi.encode(
                ATTESTATION_TYPEHASH,
                taskId,
                evidenceHash,
                taskEvidenceCid[taskId],
                msg.sender,
                block.chainid,
                address(this)
            )
        );
        bytes32 digest = keccak256(
            abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash)
        );
        address recovered = ecrecover(digest, v, r, s);
        if (recovered != msg.sender || recovered == address(0)) revert InvalidSignature();

        // 5. Record the attestation.
        attestationSubmitted[taskId][msg.sender] = true;

        if (valid) {
            validAttestationCount[taskId] += 1;
        } else {
            failAttestationCount[taskId] += 1;
        }

        // 6. Notify the registry for reputation tracking.
        registry.recordAttestation(msg.sender, valid);

        emit AttestationSubmitted(taskId, msg.sender, valid);
        accepted = true;
    }

    /// @notice Check if attestation quorum has been reached for a task.
    /// @param taskId Unique task identifier.
    /// @return reached True if N-of-M threshold is met.
    function isQuorumReached(bytes32 taskId) public view returns (bool reached) {
        return validAttestationCount[taskId] >= registry.getRequiredThreshold();
    }

    // ═══════════════════════════ Settlement ══════════════════════════════════

    /// @notice Settle a bill after N-of-M attestations pass and the
    ///         challenge window closes without dispute.
    ///
    ///         Gating conditions (any failure reverts):
    ///         1. Sufficient valid attestations (N-of-M).
    ///         2. Challenge window has ended.
    ///         3. No challenge was raised OR challenge was overruled.
    ///
    ///         On success, forwards confirmBill to the payment contract.
    ///
    /// @param taskId Task identifier (on-chain evidence key).
    /// @param billId The bill ID in NonCustodialAgentPayment to confirm.
    function settleWithAttestation(bytes32 taskId, uint256 billId) external {
        // ── Gate 1: Attestation quorum ──────────────────────────────────
        uint256 required = registry.getRequiredThreshold();
        if (validAttestationCount[taskId] < required) {
            revert InsufficientAttestations(validAttestationCount[taskId], required);
        }

        // ── Gate 2: Challenge window closed ────────────────────────────
        if (block.timestamp < challengeEnd[taskId]) {
            revert ChallengeWindowOpen();
        }

        // ── Gate 3: No active (upheld) challenge ───────────────────────
        if (challenged[taskId]) {
            // If challenge was resolved as overruled, proceed.
            // If resolved as upheld, block permanently.
            if (!challengeResolved[taskId]) {
                revert ChallengeRaised();
            }
            if (challengeUpheld[taskId]) {
                revert ChallengeRaised(); // upheld = settlement permanently blocked
            }
            // overruled → fall through and settle
        }

        // ── Forward to payment contract ────────────────────────────────
        IPaymentSettlement(paymentContract).confirmBill(billId);
        emit SettlementApproved(taskId, billId);
    }

    // ═══════════════════════════ Challenge ═════════════════════════════

    /// @notice Raise a challenge against a task during the challenge window.
    ///         Anyone can challenge; no stake is required for raising.
    /// @param taskId Task identifier being challenged.
    /// @param reason Human-readable reason code (e.g. "evidence_hash_mismatch").
    /// @param evidenceCid IPFS CID of challenge evidence.
    function raiseChallenge(
        bytes32 taskId,
        string calldata reason,
        string calldata evidenceCid
    ) external {
        if (taskEvidence[taskId] == bytes32(0)) revert TaskNotFound();
        if (block.timestamp > challengeEnd[taskId]) revert ChallengeWindowOpen();
        if (challenged[taskId]) revert ChallengeAlreadyRaised();

        challenged[taskId] = true;
        emit ChallengeRaised(taskId, msg.sender, reason, evidenceCid);
    }

    /// @notice Arbitrator resolves a challenge.
    /// @param taskId Task identifier.
    /// @param upheld True = challenge valid (settlement blocked).
    ///               False = challenge overruled (settlement may proceed).
    function resolveChallenge(bytes32 taskId, bool upheld) external {
        if (msg.sender != arbitrator) revert NotArbitrator();
        if (!challenged[taskId]) revert NoActiveChallenge();
        if (challengeResolved[taskId]) revert ChallengeResolved();

        challengeResolved[taskId] = true;
        challengeUpheld[taskId] = upheld;
        emit ChallengeResolvedEvent(taskId, upheld, msg.sender);
    }

    // ═══════════════════════════ Admin ═══════════════════════════════════════

    /// @notice Update the default challenge window duration.
    /// @param _duration New duration in seconds.
    function setChallengeWindowDuration(uint256 _duration) external {
        if (msg.sender != arbitrator) revert NotArbitrator();
        challengeWindowDuration = _duration;
        emit ChallengeWindowDurationUpdated(_duration);
    }

    // ═══════════════════════════ Views ═══════════════════════════════════════

    /// @notice Return whether the challenge window is currently open for a task.
    function isChallengeWindowOpen(bytes32 taskId) external view returns (bool) {
        return block.timestamp <= challengeEnd[taskId] && taskEvidence[taskId] != bytes32(0);
    }

    /// @notice Return whether the challenge window has closed for a task.
    function isChallengeWindowClosed(bytes32 taskId) external view returns (bool) {
        return block.timestamp > challengeEnd[taskId] && taskEvidence[taskId] != bytes32(0);
    }

    /// @notice Check if a task can be settled (all gates pass).
    function canSettle(bytes32 taskId) external view returns (bool) {
        if (taskEvidence[taskId] == bytes32(0)) return false;
        if (validAttestationCount[taskId] < registry.getRequiredThreshold()) return false;
        if (block.timestamp < challengeEnd[taskId]) return false;
        if (challenged[taskId]) {
            if (!challengeResolved[taskId]) return false;
            if (challengeUpheld[taskId]) return false;
        }
        return true;
    }

    /// @notice Get full attestation summary for a task.
    function getAttestationSummary(bytes32 taskId)
        external
        view
        returns (
            bytes32 evidenceHash,
            string memory cid_,
            uint256 challengeEnd_,
            uint256 validCount,
            uint256 failCount,
            uint256 requiredThreshold,
            bool isChallenged,
            bool isResolved,
            bool isUpheld
        )
    {
        evidenceHash = taskEvidence[taskId];
        cid_ = taskEvidenceCid[taskId];
        challengeEnd_ = challengeEnd[taskId];
        validCount = validAttestationCount[taskId];
        failCount = failAttestationCount[taskId];
        requiredThreshold = registry.getRequiredThreshold();
        isChallenged = challenged[taskId];
        isResolved = challengeResolved[taskId];
        isUpheld = challengeUpheld[taskId];
    }
}
