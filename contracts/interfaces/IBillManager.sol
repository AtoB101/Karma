// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IBillManager {
    function createBill(
        bytes32 poolId,
        address toAgent,
        uint256 amount,
        string memory purpose,
        string memory proofHash,
        bytes32 tokenId,
        uint256 authDeadline,
        uint8 v,
        bytes32 r,
        bytes32 s
    ) external returns (uint256 billId);

    function confirmBill(uint256 billId, bytes32 tokenId, uint256 authDeadline, uint8 v, bytes32 r, bytes32 s) external;
    function cancelBill(uint256 billId, bytes32 tokenId, uint256 authDeadline, uint8 v, bytes32 r, bytes32 s) external;
    function closeBatch(uint256 batchId) external;
    function settleBatch(uint256 batchId) external;
    function closeAndSettleBatch(uint256 batchId) external;
}
