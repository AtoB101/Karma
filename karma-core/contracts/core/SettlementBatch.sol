// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IKarmaBilateralBatch {
    function settle(uint256 bindingId, bytes32 proofHash) external;
    function finalizeSettle(uint256 bindingId) external;
}

/// @title SettlementBatch
/// @notice Batches many `settle()` / `finalizeSettle()` calls into one transaction.
///
/// @dev Trust model (off-chain verify + on-chain anchor):
///   - The `operator` is the off-chain verifier. It already checked each state's
///     signatures and monotonic sequence (`services/settlement_channel.py`) and
///     data availability (`services/proof_availability.py`) BEFORE calling here.
///   - This contract forwards each `(bindingId, proofHash)` to `KarmaBilateral`,
///     which anchors the per-binding proofHash on-chain exactly as it does for a
///     single settle. The batch only amortizes the transaction count and nonce.
///   - `KarmaBilateral` must grant this contract its `settleOperator` role, so
///     the standard optimistic path accepts `msg.sender == address(this)`.
///
/// @dev Why not verify signatures on-chain: worker keys are Ed25519, whose EVM
///      verification is expensive and would blow the EIP-170 size budget. The
///      honest model is "off-chain verify + on-chain anchor", not on-chain force.
contract SettlementBatch {
    address public immutable admin;
    address public operator;
    IKarmaBilateralBatch public immutable core;

    error Unauthorized();
    error ZeroAddress();
    error EmptyBatch();

    event OperatorUpdated(address indexed operator);
    event BatchSettled(address indexed operator, uint256 count);
    event BatchFinalized(address indexed operator, uint256 count);

    constructor(address admin_, address core_) {
        if (admin_ == address(0) || core_ == address(0)) revert ZeroAddress();
        admin = admin_;
        core = IKarmaBilateralBatch(core_);
        operator = admin_;
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyOperator() {
        if (msg.sender != operator) revert Unauthorized();
        _;
    }

    function setOperator(address operator_) external onlyAdmin {
        if (operator_ == address(0)) revert ZeroAddress();
        operator = operator_;
        emit OperatorUpdated(operator_);
    }

    struct Settlement {
        uint256 bindingId;
        bytes32 proofHash;
    }

    /// @notice Settle many bindings in one transaction.
    /// @dev Each item must be a binding whose off-chain state was already
    ///      verified (signatures + seq) and whose proof data is retrievable.
    function batchSettle(Settlement[] calldata items) external onlyOperator {
        uint256 n = items.length;
        if (n == 0) revert EmptyBatch();
        for (uint256 i = 0; i < n; i++) {
            core.settle(items[i].bindingId, items[i].proofHash);
        }
        emit BatchSettled(msg.sender, n);
    }

    /// @notice Finalize many FINALIZING bindings whose dispute windows closed.
    function batchFinalize(uint256[] calldata bindingIds) external onlyOperator {
        uint256 n = bindingIds.length;
        if (n == 0) revert EmptyBatch();
        for (uint256 i = 0; i < n; i++) {
            core.finalizeSettle(bindingIds[i]);
        }
        emit BatchFinalized(msg.sender, n);
    }
}
