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
