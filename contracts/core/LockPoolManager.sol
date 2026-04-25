// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ILockPoolManager} from "../interfaces/ILockPoolManager.sol";
import {IKYARegistry} from "../interfaces/IKYARegistry.sol";
import {IERC20} from "../interfaces/IERC20.sol";
import {Types} from "../libraries/Types.sol";
import {Errors} from "../libraries/Errors.sol";
import {Events} from "../libraries/Events.sol";

contract LockPoolManager is ILockPoolManager {
    IKYARegistry public immutable kyaRegistry;
    address public immutable admin;
    address public billManager;

    mapping(bytes32 poolId => Types.LockPool) public pools;
    mapping(address owner => uint256) public ownerPoolNonce;

    constructor(address kyaRegistry_) {
        if (kyaRegistry_ == address(0)) revert Errors.InvalidAddress();
        kyaRegistry = IKYARegistry(kyaRegistry_);
        admin = msg.sender;
    }

    function createLockPool(address agent, address token, uint256 amount) external override returns (bytes32 poolId) {
        if (agent == address(0) || token == address(0)) revert Errors.InvalidAddress();
        if (amount == 0) revert Errors.InvalidAmount();

        (bool ok, address owner,) = kyaRegistry.verifyDID(agent);
        if (!ok || owner != msg.sender) revert Errors.Unauthorized();

        uint256 nonce = ++ownerPoolNonce[msg.sender];
        poolId = keccak256(abi.encodePacked(msg.sender, agent, token, nonce, block.chainid));

        Types.LockPool storage p = pools[poolId];
        p.poolId = poolId;
        p.owner = msg.sender;
        p.agent = agent;
        p.token = token;
        p.totalLocked = amount;
        p.mappingBalance = amount;
        p.batchId = 1;
        p.createdAt = block.timestamp;
        if (!IERC20(token).transferFrom(msg.sender, address(this), amount)) revert Errors.TokenTransferFailed();

        emit Events.LockPoolCreated(poolId, msg.sender, agent, token, amount);
    }

    function topUpLockPool(bytes32 poolId, uint256 amount) external override {
        if (amount == 0) revert Errors.InvalidAmount();
        Types.LockPool storage p = pools[poolId];
        if (p.owner != msg.sender) revert Errors.Unauthorized();

        p.totalLocked += amount;
        p.mappingBalance += amount;
        if (!IERC20(p.token).transferFrom(msg.sender, address(this), amount)) revert Errors.TokenTransferFailed();
        emit Events.LockPoolToppedUp(poolId, amount);
    }

    function withdrawLockPool(bytes32 poolId, uint256 amount) external override {
        if (amount == 0) revert Errors.InvalidAmount();
        Types.LockPool storage p = pools[poolId];
        if (p.owner != msg.sender) revert Errors.Unauthorized();
        if (p.pendingAmount != 0) revert Errors.PendingAmountNotZero();
        if (p.mappingBalance < amount || p.totalLocked < amount) revert Errors.InsufficientMappingBalance();

        p.totalLocked -= amount;
        p.mappingBalance -= amount;
        if (!IERC20(p.token).transfer(msg.sender, amount)) revert Errors.TokenTransferFailed();
        emit Events.LockPoolWithdrawn(poolId, amount);
    }

    function getMappingBalance(bytes32 poolId) external view override returns (uint256) {
        return pools[poolId].mappingBalance;
    }

    function getPoolOwner(bytes32 poolId) external view override returns (address) {
        return pools[poolId].owner;
    }

    function getPoolAccounting(bytes32 poolId)
        external
        view
        override
        returns (uint256 totalLocked, uint256 mappingBalance, uint256 pendingAmount, uint256 settledAmount)
    {
        Types.LockPool storage p = pools[poolId];
        return (p.totalLocked, p.mappingBalance, p.pendingAmount, p.settledAmount);
    }

    function setBillManager(address billManager_) external override {
        if (msg.sender != admin) revert Errors.Unauthorized();
        if (billManager_ == address(0)) revert Errors.InvalidAddress();
        billManager = billManager_;
    }

    function reserveMappingForBill(bytes32 poolId, uint256 amount) external override {
        if (msg.sender != billManager) revert Errors.Unauthorized();
        if (amount == 0) revert Errors.InvalidAmount();

        Types.LockPool storage p = pools[poolId];
        if (p.poolId == bytes32(0)) revert Errors.NotFound();
        if (p.mappingBalance < amount) revert Errors.InsufficientMappingBalance();

        p.mappingBalance -= amount;
        p.pendingAmount += amount;
    }

    function releasePendingOnCancel(bytes32 poolId, uint256 amount) external override {
        if (msg.sender != billManager) revert Errors.Unauthorized();
        if (amount == 0) revert Errors.InvalidAmount();

        Types.LockPool storage p = pools[poolId];
        if (p.poolId == bytes32(0)) revert Errors.NotFound();
        if (p.pendingAmount < amount) revert Errors.InvalidState();

        p.pendingAmount -= amount;
        p.mappingBalance += amount;
    }

    function settleFromPendingAndPayout(bytes32 poolId, address to, uint256 amount) external override {
        if (msg.sender != billManager) revert Errors.Unauthorized();
        if (to == address(0) || amount == 0) revert Errors.InvalidAmount();

        Types.LockPool storage p = pools[poolId];
        if (p.poolId == bytes32(0)) revert Errors.NotFound();
        if (p.pendingAmount < amount) revert Errors.InvalidState();
        if (p.totalLocked < amount) revert Errors.InsufficientMappingBalance();

        p.pendingAmount -= amount;
        p.totalLocked -= amount;
        p.settledAmount += amount;
        if (!IERC20(p.token).transfer(to, amount)) revert Errors.TokenTransferFailed();
    }
}
