// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Verifies a TEE (enclave) settlement attestation for KarmaBilateral.
///         Reverts on any invalid attestation; returns silently on success.
interface ITEESettlementVerifier {
    /// @param bindingId  Binding being settled.
    /// @param proofHash  keccak256 of the execution proof / evidence bundle.
    /// @param imageHash  Expected enclave image measurement (PCR-derived).
    /// @param v,r,s      secp256k1 signature over the EIP-712 TeeSettlement digest.
    function verifySettlement(
        uint256 bindingId,
        bytes32 proofHash,
        bytes32 imageHash,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external view;
}
