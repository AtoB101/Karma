// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

library Types {
    struct AgentDID {
        address owner;
        address agent;
        uint256 registeredAt;
        uint256 validUntil;
        bytes32 permissionsHash;
        bool isActive;
    }

    struct LockPool {
        bytes32 poolId;
        address owner;
        address agent;
        address token;
        uint256 totalLocked;
        uint256 mappingBalance;
        uint256 pendingAmount;
        uint256 settledAmount;
        uint256 batchId;
        uint256 createdAt;
    }

    struct Bill {
        uint256 billId;
        uint256 batchId;
        address fromAgent;
        address toAgent;
        uint256 amount;
        string purpose;
        string proofHash;
        BillStatus status;
        uint256 createdAt;
        uint256 deadline;
    }

    struct Batch {
        uint256 batchId;
        bytes32 poolId;
        uint256 totalPending;
        uint256 billCount;
        BatchStatus status;
        uint256 createdAt;
        uint256 settledAt;
    }

    struct AuthToken {
        bytes32 tokenId;
        address owner;
        address agent;
        OperationType opType;
        uint256 maxAmount;
        uint256 validUntil;
        bool used;
        uint256 nonce;
    }

    // ═══════════════════════════ Intent Package ═══════════════════════════════

    /// @notice Structured service intent — replaces raw bytes32 scopeHash.
    ///         Defines who does what, for how much, by when, with what proof.
    struct IntentPackage {
        // Parties
        address buyer;
        address seller;
        // Service definition
        bytes32 serviceType;                   // keccak256("flight_booking"|"food_delivery"|...)
        bytes   requirements;                  // calldata: structured service spec
        // Payment terms
        uint256 amount;                        // agreed payment
        uint256 penaltyRate;                   // basis points: 1000 = 10% penalty on failure
        // Timing
        uint256 deadline;                      // must complete by this timestamp
        uint256 expiresAt;                     // intent expires — must bind before this
        // Verification
        bytes32 proofSchema;                   // fingerprint of expected proof structure
        bytes32[] requiredProofFields;         // keys that must appear in proof
        address verifier;                      // external verifier (address(0) = pure on-chain)
        // Dispute
        uint256 disputeWindow;                 // seconds after settle for dispute
        address[] arbitrators;                 // arbitration panel
    }

    /// @notice Multi-dimension scoring vector for all three parties.
    struct ScoringVector {
        // Universal
        uint256 totalTransactions;
        uint256 reputationScore;               // 0-10000, composite
        // Supplier (seller) dimensions
        uint256 completionRate;                // basis points: 10000 = 100%
        uint256 avgCompletionSpeed;            // relative to deadline (10000 = on time, >10000 = early)
        uint256 disputeRate;                   // basis points
        uint256 disputeWinRate;                // basis points
        uint256 penaltyCount;
        // Buyer dimensions
        uint256 confirmationSpeed;             // how fast buyer confirms receipt
        uint256 maliciousDisputeRate;          // basis points: disputes lost by buyer
        // Verifier dimensions
        uint256 verificationAccuracy;          // basis points: verifications not overturned
        uint256 verificationVolume;            // total verifications performed
        uint256 slashedCount;                  // times penalized for bad verification
        // Metadata
        uint256 lastUpdated;
    }

    /// @notice Evidence record submitted by a verifier.
    struct Evidence {
        uint256 evidenceId;
        uint256 bindingId;
        address verifier;
        bytes   data;                          // actual evidence (API response hash, GPS trace, etc.)
        bytes32 fieldHash;                     // which requirement field this proves
        uint256 timestamp;
        bool    valid;
    }

    enum OperationType {
        CreateBill,
        ConfirmBill,
        CancelBill,
        SetThreshold
    }

    enum BillStatus {
        Pending,
        Confirmed,
        Cancelled,
        Settled
    }

    enum BatchStatus {
        Open,
        Closed,
        Settled
    }
}
