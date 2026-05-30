// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

// ─────────────────────────────────────────────────────────────────────────────
//  IKarmaBilateral — Public interface for KarmaBilateral.sol
//
//  Three core methods:
//    lock()   → mint Bill Token, USDC enters escrow
//    bind()   → bilateral bind, both Bills enter BOUND (frozen)
//    settle() → verify proof, burn Bills, release USDC atomically
//
//  Invariant guaranteed by implementation:
//    totalBillSupply[token] == totalLocked[token]  at all times
// ─────────────────────────────────────────────────────────────────────────────

interface IKarmaBilateral {

    // ═══════════════════════════ Enums ═══════════════════════════════════════

    /// @notice Life cycle of a single Bill Token (SBT, non-transferable).
    enum BillState {
        MINTED,  // locked, available to bind
        BOUND,   // frozen in active responsibility — cannot withdraw or re-bind
        BURNED   // settled or refunded — terminal
    }

    /// @notice Life cycle of a bilateral binding.
    enum BindingState {
        ACTIVE,    // both Bills BOUND, task executing
        PENDING,   // batch threshold reached, awaiting settle
        SETTLED,   // proof accepted, USDC released — terminal
        DISPUTED,  // dispute raised, awaiting admin resolution
        REFUNDED   // timeout recovery or pre-execution cancellation — terminal
    }

    // ═══════════════════════════ Structs ═════════════════════════════════════

    struct BillToken {
        uint256 billId;
        address owner;
        address token;
        uint256 amount;
        BillState state;
        uint256 mintedAt;
    }

    struct Binding {
        uint256 bindingId;
        uint256 buyerBillId;
        uint256 agentBillId;
        bytes32 scopeHash;
        BindingState state;
        uint256 createdAt;
        uint256 settleAfter;
        bytes32 proofHash;
        uint256 disputedAt;
        address disputeInitiator;
    }

    // ═══════════════════════════ Events ══════════════════════════════════════

    event BillMinted(uint256 indexed billId, address indexed owner, address token, uint256 amount);
    event BillBurned(uint256 indexed billId, address indexed owner, uint256 amount, string reason);
    event BillsBound(uint256 indexed bindingId, uint256 buyerBillId, uint256 agentBillId, bytes32 scopeHash);
    event BindingSettled(uint256 indexed bindingId, bytes32 proofHash, uint256 buyerAmount, uint256 agentAmount);
    event BindingRefunded(uint256 indexed bindingId, uint256 buyerAmount, uint256 agentAmount);
    event DisputeRaised(uint256 indexed bindingId, address indexed initiator);
    event DisputeResolved(uint256 indexed bindingId, uint256 buyerShareBps);
    event BatchThresholdUpdated(address indexed token, uint256 threshold);
    event TokenAllowed(address indexed token, bool allowed);
    event InvariantChecked(address indexed token, uint256 supply, uint256 locked);

    // ═══════════════════════════ Core Interface ═══════════════════════════════

    /// @notice Lock ERC-20 tokens and mint a Bill Token (SBT) to caller.
    /// @dev    Pulls `amount` from caller via transferFrom. Token must be allowlisted.
    ///         Post-condition: totalBillSupply[token] == totalLocked[token].
    /// @param  token   Allowlisted ERC-20 address (e.g. USDC)
    /// @param  amount  Amount to lock (in token decimals)
    /// @return billId  Newly minted Bill Token ID
    function lock(address token, uint256 amount) external returns (uint256 billId);

    /// @notice Bilaterally bind a buyer Bill and an agent Bill into a Binding.
    /// @dev    Caller must own buyerBillId. Both bills must be in MINTED state.
    ///         Both bills transition MINTED → BOUND atomically.
    ///         BOUND bills cannot be withdrawn, transferred, or re-bound.
    /// @param  buyerBillId  Bill Token held by the demand side
    /// @param  agentBillId  Bill Token held by the supply side
    /// @param  scopeHash    keccak256 of the task scope / service agreement
    /// @return bindingId    ID of the created Binding
    function bind(uint256 buyerBillId, uint256 agentBillId, bytes32 scopeHash)
        external
        returns (uint256 bindingId);

    /// @notice Settle a binding: verify proof, burn both Bills, release USDC atomically.
    /// @dev    Callable by buyer or agent after the dispute window has passed.
    ///         Burn and transfer are atomic — no partial execution possible.
    ///         Post-condition: totalBillSupply[token] == totalLocked[token].
    /// @param  bindingId  Binding to settle (must be ACTIVE or PENDING)
    /// @param  proofHash  keccak256 of execution proof / evidence bundle CID
    function settle(uint256 bindingId, bytes32 proofHash) external;

    // ═══════════════════════════ Dispute & Timeout ════════════════════════════

    /// @notice Raise a dispute on an ACTIVE binding. Caller must be buyer or agent.
    function dispute(uint256 bindingId) external;

    /// @notice Admin resolves a DISPUTED binding by specifying buyer's BPS share.
    /// @param  buyerShareBps  Buyer fraction of combined pool (0–10000)
    function resolveDispute(uint256 bindingId, uint16 buyerShareBps) external;

    /// @notice Buyer recovers all funds after settleTimeoutSeconds with no settle.
    function refundOnTimeout(uint256 bindingId) external;

    // ═══════════════════════════ Pre-bind Unlock ══════════════════════════════

    /// @notice Withdraw a MINTED (unbound) Bill Token and reclaim locked funds.
    /// @dev    Reverts if bill is BOUND — funds locked until settle/dispute/timeout.
    function unlock(uint256 billId) external;

    // ═══════════════════════════ Views ════════════════════════════════════════

    function getBill(uint256 billId) external view returns (BillToken memory);
    function getBinding(uint256 bindingId) external view returns (Binding memory);
    function ownerBills(address owner) external view returns (uint256[] memory);

    /// @notice Returns true if totalBillSupply[token] == totalLocked[token].
    function checkInvariant(address token) external view returns (bool);

    function totalBillSupply(address token) external view returns (uint256);
    function totalLocked(address token) external view returns (uint256);
    function pendingBatchAmount(address token) external view returns (uint256);
    function batchThreshold(address token) external view returns (uint256);
    function tokenAllowed(address token) external view returns (bool);
    function disputeWindowSeconds() external view returns (uint256);
    function settleTimeoutSeconds() external view returns (uint256);

    // ═══════════════════════════ Admin ════════════════════════════════════════

    function setTokenAllowed(address token, bool allowed) external;
    function setBatchThreshold(address token, uint256 threshold) external;
    function setDisputeWindow(uint256 seconds_) external;
    function setSettleTimeout(uint256 seconds_) external;
}
