// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface ILockPoolManager {
    function createLockPool(address agent, address token, uint256 amount) external returns (bytes32 poolId);
    function topUpLockPool(bytes32 poolId, uint256 amount) external;
    function withdrawLockPool(bytes32 poolId, uint256 amount) external;
    function getMappingBalance(bytes32 poolId) external view returns (uint256);
    function getPoolOwner(bytes32 poolId) external view returns (address);
    function setBillManager(address billManager) external;
    function reserveMappingForBill(bytes32 poolId, uint256 amount) external;
    function releasePendingOnCancel(bytes32 poolId, uint256 amount) external;
    function settleFromPendingAndPayout(bytes32 poolId, address to, uint256 amount) external;
    function getPoolAccounting(bytes32 poolId)
        external
        view
        returns (uint256 totalLocked, uint256 mappingBalance, uint256 pendingAmount, uint256 settledAmount);
}
