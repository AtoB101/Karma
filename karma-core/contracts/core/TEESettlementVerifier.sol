// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {SignatureValidator} from "../libraries/SignatureValidator.sol";
import {ITEESettlementVerifier} from "../interfaces/ITEESettlementVerifier.sol";

/// @title  TEESettlementVerifier
/// @notice On-chain verifier for TEE (enclave) settlement attestations.
///
/// @dev Trust model (see docs/TEE_ATTESTATION_SPEC.md):
///   - An enclave (e.g. AWS Nitro) holds a secp256k1 key that never leaves the
///     trusted hardware. The enclave's public address is bound to the enclave
///     image measurement (`imageHash`, PCR-derived) at registration time.
///   - `registerEnclave` is called by the `attester` role AFTER the operator has
///     verified the raw hardware attestation quote off-chain against the vendor
///     root of trust. The reference verifier ships in `scripts/tee_attestation/`.
///   - After registration, the enclave signs an EIP-712 digest over
///     (bindingId, proofHash, imageHash). This contract recovers the signer and
///     checks it is a registered, active enclave whose image matches, so
///     KarmaBilateral can settle immediately (skipping the Layer 1 dispute window).
///
/// @dev Why per-settlement verification is cheap: the expensive RSA+CBOR quote
///      verification happens ONCE per enclave at registration (off-chain). Each
///      settlement is a single secp256k1 `ecrecover`, which is gas- and
///      bytecode-size-friendly on-chain.
contract TEESettlementVerifier is ITEESettlementVerifier {
    struct Enclave {
        bytes32 imageHash;
        bool active;
        uint256 registeredAt;
    }

    /// @notice Governance (AdminTimelock on mainnet).
    address public immutable admin;
    /// @notice The KarmaBilateral allowed to call verifySettlement.
    address public core;
    /// @notice Role that verifies hardware quotes off-chain and registers keys.
    address public attester;

    /// @dev enclave secp256k1 address => registration record.
    mapping(address => Enclave) public enclaves;

    error Unauthorized();
    error ZeroAddress();
    error InvalidAttestation();
    error EnclaveNotActive(address enclave);
    error ImageMismatch(address enclave, bytes32 expected, bytes32 provided);

    bytes32 private constant TEE_TYPEHASH =
        keccak256("TeeSettlement(uint256 bindingId,bytes32 proofHash,bytes32 imageHash)");
    bytes32 private constant DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");

    bytes32 public immutable DOMAIN_SEPARATOR;

    event CoreUpdated(address indexed core);
    event AttesterUpdated(address indexed attester);
    event EnclaveRegistered(address indexed enclave, bytes32 imageHash);
    event EnclaveRevoked(address indexed enclave);

    constructor(address admin_, address core_) {
        if (admin_ == address(0) || core_ == address(0)) revert ZeroAddress();
        admin = admin_;
        core = core_;
        DOMAIN_SEPARATOR = keccak256(
            abi.encode(
                DOMAIN_TYPEHASH,
                keccak256("KarmaTEESettlementVerifier"),
                keccak256("1"),
                block.chainid,
                address(this)
            )
        );
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyAttester() {
        if (msg.sender != attester) revert Unauthorized();
        _;
    }

    modifier onlyCore() {
        if (msg.sender != core) revert Unauthorized();
        _;
    }

    function setCore(address core_) external onlyAdmin {
        if (core_ == address(0)) revert ZeroAddress();
        core = core_;
        emit CoreUpdated(core_);
    }

    function setAttester(address attester_) external onlyAdmin {
        if (attester_ == address(0)) revert ZeroAddress();
        attester = attester_;
        emit AttesterUpdated(attester_);
    }

    /// @notice Register an enclave key after off-chain quote verification.
    function registerEnclave(address enclave, bytes32 imageHash) external onlyAttester {
        if (enclave == address(0)) revert ZeroAddress();
        enclaves[enclave] = Enclave({imageHash: imageHash, active: true, registeredAt: block.timestamp});
        emit EnclaveRegistered(enclave, imageHash);
    }

    /// @notice Revoke an enclave key (governance kill-switch / key rotation).
    function revokeEnclave(address enclave) external onlyAdmin {
        enclaves[enclave].active = false;
        emit EnclaveRevoked(enclave);
    }

    /// @inheritdoc ITEESettlementVerifier
    function verifySettlement(
        uint256 bindingId,
        bytes32 proofHash,
        bytes32 imageHash,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external view onlyCore {
        bytes32 structHash = keccak256(abi.encode(TEE_TYPEHASH, bindingId, proofHash, imageHash));
        bytes32 digest = keccak256(abi.encodePacked("\x19\x01", DOMAIN_SEPARATOR, structHash));

        address signer = SignatureValidator.recoverStrict(digest, v, r, s);
        if (signer == address(0)) revert InvalidAttestation();

        Enclave memory enclave = enclaves[signer];
        if (!enclave.active) revert EnclaveNotActive(signer);
        if (enclave.imageHash != imageHash) revert ImageMismatch(signer, enclave.imageHash, imageHash);
    }
}
