// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface INonCustodialAgentPayment {
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
        address buyer;
        address seller;
        address token;
        uint256 amount;
        uint256 sellerBond;
        bytes32 scopeHash;
        BillStatus status;
        uint256 createdAt;
        uint256 deadline;
    }

    function lockFunds(address token, uint256 amount) external;
    function unlockFunds(address token, uint256 amount) external;
    function createBill(address seller, address token, uint256 amount, bytes32 scopeHash, uint256 deadline)
        external
        returns (uint256 billId);
    function confirmBill(uint256 billId) external;
    function cancelBill(uint256 billId) external;
    function disputeBill(uint256 billId) external;
    function requestBillPayout(uint256 billId) external returns (bool ok);
    function expireBill(uint256 billId) external;
    function resolveDisputeBuyer(uint256 billId) external;
    function resolveDisputeSeller(uint256 billId) external;
    function resolveDisputeSplit(uint256 billId, uint16 buyerShareBps) external;
    function getAccountState(address user, address token) external view returns (AccountState memory);
    function getBill(uint256 billId) external view returns (Bill memory);
    function isAccountConsistent(address user, address token) external view returns (bool);
}
