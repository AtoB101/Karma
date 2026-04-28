// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface INonCustodialAgentPayment {
    struct PolicyConfig {
        bool enabled;
        uint256 dailyLimit;
        uint256 perTxLimit;
        uint256 maxTxPerHour;
        uint256 validUntil;
    }

    struct Policy {
        uint256 perTxLimit;
        uint256 dailyLimit;
        uint256 maxTxPerMinute;
        uint256 validUntil;
        bool enabled;
    }

    struct PolicyUsage {
        uint256 dayIndex;
        uint256 spentToday;
        uint256 txCountToday;
        uint256 hourIndex;
        uint256 txCountHour;
    }

    enum BatchStatus {
        Open,
        Closed,
        Settled
    }

    enum BillStatus {
        Pending,
        Confirmed,
        Disputed,
        Settled,
        Cancelled,
        Expired,
        ResolvedBuyer,
        ResolvedSeller,
        SplitResolved
    }

    struct AccountState {
        uint256 locked;
        uint256 active;
        uint256 reserved;
    }

    struct Bill {
        uint256 billId;
        uint256 batchId;
        address buyer;
        address seller;
        address token;
        uint256 amount;
        uint256 sellerBond;
        bytes32 scopeHash;
        string proofHash;
        BillStatus status;
        uint256 createdAt;
        uint256 deadline;
    }

    struct Batch {
        uint256 batchId;
        uint256 totalPending;
        uint256 billCount;
        BatchStatus status;
        uint256 createdAt;
        uint256 settledAt;
    }

    function lockFunds(address token, uint256 amount) external;
    function unlockFunds(address token, uint256 amount) external;
    function createBill(address seller, address token, uint256 amount, bytes32 scopeHash, string calldata proofHash, uint256 deadline)
        external
        returns (uint256 billId);
    function confirmBill(uint256 billId) external;
    function confirmBillBySignature(uint256 billId, uint256 deadline, uint8 v, bytes32 r, bytes32 s) external;
    function cancelBill(uint256 billId) external;
    /// @notice Buyer or seller can raise a dispute on a confirmed bill.
    /// @dev Seller-initiated disputes have no direct economic cost besides gas and can be abused for DoS-style friction.
    /// Frontend/operator tooling should warn and rate-limit suspicious seller dispute patterns.
    function disputeBill(uint256 billId) external;
    function requestBillPayout(uint256 billId) external returns (bool ok);
    function expireBill(uint256 billId) external;
    function resolveDisputeBuyer(uint256 billId) external;
    function resolveDisputeSeller(uint256 billId) external;
    function resolveDisputeSplit(uint256 billId, uint16 buyerShareBps) external;
    function closeBatch(uint256 batchId) external;
    function settleBatch(uint256 batchId, uint256 maxBills) external returns (uint256 settledCount, uint256 settledAmount);
    function setBatchModeEnabled(bool enabled) external;
    function setBatchCircuitBreakerPaused(bool paused) external;
    function getBatch(uint256 batchId) external view returns (Batch memory);
    function getBatchBillIds(uint256 batchId) external view returns (uint256[] memory);
    function getAccountState(address user, address token) external view returns (AccountState memory);
    function getBill(uint256 billId) external view returns (Bill memory);
    function confirmNonce(address buyer) external view returns (uint256);
    function isAccountConsistent(address user, address token) external view returns (bool);
    function setPolicy(uint256 perTxLimit, uint256 dailyLimit, uint256 maxTxPerMinute, uint256 validUntil, bool enabled)
        external;
    function setPolicyConfig(bool enabled, uint256 dailyLimit, uint256 perTxLimit, uint256 maxTxPerHour, uint256 validUntil)
        external;
    function setPolicyPayee(address payee, bool allowed) external;
    function setPolicyToken(address token, bool allowed) external;
    function setPolicyAllowedCounterparty(address counterparty, bool allowed) external;
    function setPolicyAllowedScope(bytes32 scopeHash, bool allowed) external;
    function getPolicy(address user) external view returns (Policy memory);
    function getPolicyConfig(address ownerAddr) external view returns (PolicyConfig memory);
    function getPolicyUsage(address ownerAddr) external view returns (uint256 txCountToday, uint256 spentToday, uint256 txCountHour, uint256 dayIndex);
    function getPolicyUsageStruct(address ownerAddr) external view returns (PolicyUsage memory);
    function isPolicyPayeeAllowed(address user, address payee) external view returns (bool);
    function isPolicyTokenAllowed(address user, address token) external view returns (bool);
    function isPolicyCounterpartyAllowed(address ownerAddr, address counterparty) external view returns (bool);
    function isPolicyScopeAllowed(address ownerAddr, bytes32 scopeHash) external view returns (bool);
    function setSettlementTokenAllowed(address token, bool allowed) external;
    function setSettlementTokenEnforced(bool enabled) external;
    function setMinSettlementAmount(uint256 amount) external;
    function isSettlementTokenAllowed(address token) external view returns (bool);
    function isSettlementTokenEnforced() external view returns (bool);
    function minSettlementAmount() external view returns (uint256);
}
