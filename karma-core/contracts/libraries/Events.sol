// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

library Events {
    event DIDRegistered(bytes32 indexed did, address indexed agent, address indexed owner, uint256 validUntil);
    event DIDRevoked(address indexed agent, address indexed owner);
    event PermissionUpdated(address indexed agent, bytes32 newHash);

    event LockPoolCreated(bytes32 indexed poolId, address indexed owner, address indexed agent, address token, uint256 amount);
    event LockPoolToppedUp(bytes32 indexed poolId, uint256 amount);
    event LockPoolWithdrawn(bytes32 indexed poolId, uint256 amount);

    event AuthTokenIssued(bytes32 indexed tokenId, address indexed owner, address indexed agent, uint256 validUntil);
    event AuthTokenRevoked(bytes32 indexed tokenId, address indexed owner);

    event BillCreated(uint256 indexed billId, uint256 indexed batchId, bytes32 indexed poolId, address fromAgent, address toAgent, uint256 amount);
    event BillConfirmed(uint256 indexed billId, address indexed owner);
    event BillCancelled(uint256 indexed billId, address indexed owner);

    event BatchClosed(uint256 indexed batchId, bytes32 indexed poolId);
    event BatchSettled(uint256 indexed batchId, bytes32 indexed poolId, uint256 amount);

    event HumanApprovalThresholdUpdated(address indexed owner, uint256 amount);
    event AgentPaused(address indexed agent, string reason);
    event AgentResumed(address indexed agent);
    event GlobalCircuitBreakerTriggered(address indexed triggeredBy, string reason);
    event GlobalCircuitBreakerResumed(address indexed triggeredBy);
}
