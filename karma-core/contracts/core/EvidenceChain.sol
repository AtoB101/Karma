// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Types} from "../libraries/Types.sol";

/// @title EvidenceChain
/// @notice Immutable on-chain evidence log for Karma service verifications.
///         Verifiers submit structured evidence proving each requirement field
///         of an IntentPackage was fulfilled. Once written, evidence cannot be
///         modified — it forms the audit trail for dispute resolution.
///
///         This contract does NOT judge correctness. It stores evidence.
///         ScoringEngine and arbitrators consume this data.
contract EvidenceChain {

    // ═══════════════════════════ Errors ══════════════════════════════════════

    error Unauthorized();
    error AlreadySubmitted();
    error EvidenceNotFound();
    error InvalidBinding();

    // ═══════════════════════════ Storage ═════════════════════════════════════

    address public immutable admin;
    address public authorizedVerifier;           // VerifierRegistry or KarmaBilateral

    uint256 private _evidenceCounter;

    /// @notice bindingId → evidenceId[] (ordered evidence chain per binding)
    mapping(uint256 => uint256[]) public bindingEvidenceIds;

    /// @notice evidenceId → Evidence
    mapping(uint256 => Types.Evidence) public evidences;

    // ═══════════════════════════ Events ══════════════════════════════════════

    event EvidenceSubmitted(
        uint256 indexed evidenceId,
        uint256 indexed bindingId,
        address indexed verifier,
        bytes32 fieldHash
    );

    event EvidenceInvalidated(uint256 indexed evidenceId, string reason);
    event AuthorizedVerifierUpdated(address indexed verifier);

    // ═══════════════════════════ Modifiers ════════════════════════════════════

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyAuthorized() {
        if (msg.sender != authorizedVerifier && msg.sender != admin) revert Unauthorized();
        _;
    }

    // ═══════════════════════════ Constructor ══════════════════════════════════

    constructor(address admin_) {
        admin = admin_;
    }

    // ═══════════════════════════ Admin ════════════════════════════════════════

    function setAuthorizedVerifier(address verifier) external onlyAdmin {
        authorizedVerifier = verifier;
        emit AuthorizedVerifierUpdated(verifier);
    }

    // ═══════════════════════════ Evidence Submission ══════════════════════════

    /// @notice Submit a single piece of evidence for a binding.
    function submitEvidence(
        uint256 bindingId,
        bytes   calldata data,
        bytes32 fieldHash
    )
        external
        onlyAuthorized
        returns (uint256 evidenceId)
    {
        return _submitEvidence(bindingId, data, fieldHash);
    }

    /// @notice Submit a batch of evidence entries for a binding.
    function submitEvidenceBatch(
        uint256   bindingId,
        bytes[]   calldata dataArray,
        bytes32[] calldata fieldHashes
    )
        external
        onlyAuthorized
        returns (uint256[] memory evidenceIds)
    {
        uint256 len = dataArray.length;
        require(len == fieldHashes.length, "Length mismatch");
        evidenceIds = new uint256[](len);

        for (uint256 i = 0; i < len; i++) {
            evidenceIds[i] = _submitEvidence(bindingId, dataArray[i], fieldHashes[i]);
        }
    }

    function _submitEvidence(
        uint256 bindingId,
        bytes   calldata data,
        bytes32 fieldHash
    )
        internal
        returns (uint256 evidenceId)
    {
        unchecked { evidenceId = ++_evidenceCounter; }

        evidences[evidenceId] = Types.Evidence({
            evidenceId: evidenceId,
            bindingId:  bindingId,
            verifier:   msg.sender,
            data:       data,
            fieldHash:  fieldHash,
            timestamp:  block.timestamp,
            valid:      true
        });

        bindingEvidenceIds[bindingId].push(evidenceId);

        emit EvidenceSubmitted(evidenceId, bindingId, msg.sender, fieldHash);
    }

    /// @notice Mark evidence as invalid (used when arbitration overturns verification).
    function invalidateEvidence(uint256 evidenceId, string calldata reason) external onlyAdmin {
        Types.Evidence storage ev = evidences[evidenceId];
        if (ev.evidenceId == 0) revert EvidenceNotFound();
        ev.valid = false;
        emit EvidenceInvalidated(evidenceId, reason);
    }

    // ═══════════════════════════ Views ════════════════════════════════════════

    function getEvidence(uint256 evidenceId) external view returns (Types.Evidence memory) {
        return evidences[evidenceId];
    }

    function getBindingEvidence(uint256 bindingId)
        external
        view
        returns (Types.Evidence[] memory)
    {
        uint256[] storage ids = bindingEvidenceIds[bindingId];
        Types.Evidence[] memory result = new Types.Evidence[](ids.length);
        for (uint256 i = 0; i < ids.length; i++) {
            result[i] = evidences[ids[i]];
        }
        return result;
    }

    function getBindingEvidenceCount(uint256 bindingId) external view returns (uint256) {
        return bindingEvidenceIds[bindingId].length;
    }

    function totalEvidence() external view returns (uint256) {
        return _evidenceCounter;
    }
}
