// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IBillManager} from "../interfaces/IBillManager.sol";
import {ILockPoolManager} from "../interfaces/ILockPoolManager.sol";
import {IKYARegistry} from "../interfaces/IKYARegistry.sol";
import {ICircuitBreaker} from "../interfaces/ICircuitBreaker.sol";
import {IAuthTokenManager} from "../interfaces/IAuthTokenManager.sol";
import {Types} from "../libraries/Types.sol";
import {Errors} from "../libraries/Errors.sol";
import {Events} from "../libraries/Events.sol";

contract BillManager is IBillManager {
    ILockPoolManager public immutable lockPoolManager;
    IKYARegistry public immutable kyaRegistry;
    ICircuitBreaker public immutable circuitBreaker;
    IAuthTokenManager public immutable authTokenManager;

    uint256 public nextBillId = 1;
    uint256 public nextBatchId = 1;

    mapping(uint256 billId => Types.Bill) public bills;
    mapping(uint256 batchId => Types.Batch) public batches;
    mapping(uint256 batchId => uint256[]) public batchBills;
    mapping(uint256 billId => bytes32 poolId) public billPoolId;
    mapping(bytes32 poolId => uint256 batchId) public activeBatchByPool;

    constructor(address lockPoolManager_, address kyaRegistry_, address circuitBreaker_, address authTokenManager_) {
        if (
            lockPoolManager_ == address(0) || kyaRegistry_ == address(0) || circuitBreaker_ == address(0)
                || authTokenManager_ == address(0)
        ) {
            revert Errors.InvalidAddress();
        }
        lockPoolManager = ILockPoolManager(lockPoolManager_);
        kyaRegistry = IKYARegistry(kyaRegistry_);
        circuitBreaker = ICircuitBreaker(circuitBreaker_);
        authTokenManager = IAuthTokenManager(authTokenManager_);
    }

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
    )
        external
        override
        returns (uint256 billId)
    {
        if (circuitBreaker.isGlobalPaused() || circuitBreaker.isAgentPaused(msg.sender)) revert Errors.CircuitBreakerActive();
        if (toAgent == address(0) || amount == 0) revert Errors.InvalidAmount();

        (bool fromOk,,) = kyaRegistry.verifyDID(msg.sender);
        (bool toOk,,) = kyaRegistry.verifyDID(toAgent);
        if (!fromOk || !toOk) revert Errors.DIDNotActive();
        authTokenManager.consumeAuth(
            tokenId, msg.sender, Types.OperationType.CreateBill, amount, authDeadline, v, r, s
        );

        uint256 mappingBalance = lockPoolManager.getMappingBalance(poolId);
        if (mappingBalance < amount) revert Errors.InsufficientMappingBalance();
        lockPoolManager.reserveMappingForBill(poolId, amount);

        uint256 batchId = activeBatchByPool[poolId];
        if (batchId == 0) {
            batchId = nextBatchId++;
            activeBatchByPool[poolId] = batchId;
        }

        Types.Batch storage batch = batches[batchId];
        if (batch.status != Types.BatchStatus.Open) {
            batchId = nextBatchId++;
            activeBatchByPool[poolId] = batchId;
            batch = batches[batchId];
        }

        if (batch.createdAt == 0) {
            batch.batchId = batchId;
            batch.poolId = poolId;
            batch.status = Types.BatchStatus.Open;
            batch.createdAt = block.timestamp;
        }

        billId = nextBillId++;
        bills[billId] = Types.Bill({
            billId: billId,
            batchId: batchId,
            fromAgent: msg.sender,
            toAgent: toAgent,
            amount: amount,
            purpose: purpose,
            proofHash: proofHash,
            status: Types.BillStatus.Pending,
            createdAt: block.timestamp,
            deadline: block.timestamp + 1 days
        });

        batch.totalPending += amount;
        batch.billCount += 1;
        batchBills[batchId].push(billId);
        billPoolId[billId] = poolId;

        emit Events.BillCreated(billId, batchId, poolId, msg.sender, toAgent, amount);
    }

    function confirmBill(uint256 billId, bytes32 tokenId, uint256 authDeadline, uint8 v, bytes32 r, bytes32 s)
        external
        override
    {
        Types.Bill storage bill = bills[billId];
        if (bill.billId == 0) revert Errors.NotFound();
        if (bill.status != Types.BillStatus.Pending) revert Errors.InvalidState();
        address poolOwner = _checkBillOwnerAuthorization(billId);
        authTokenManager.consumeAuth(
            tokenId, poolOwner, Types.OperationType.ConfirmBill, bill.amount, authDeadline, v, r, s
        );
        bill.status = Types.BillStatus.Confirmed;
        emit Events.BillConfirmed(billId, msg.sender);
    }

    function cancelBill(uint256 billId, bytes32 tokenId, uint256 authDeadline, uint8 v, bytes32 r, bytes32 s)
        external
        override
    {
        Types.Bill storage bill = bills[billId];
        if (bill.billId == 0) revert Errors.NotFound();
        if (bill.status != Types.BillStatus.Pending) revert Errors.InvalidState();
        address poolOwner = _checkBillOwnerAuthorization(billId);
        authTokenManager.consumeAuth(
            tokenId, poolOwner, Types.OperationType.CancelBill, bill.amount, authDeadline, v, r, s
        );
        lockPoolManager.releasePendingOnCancel(billPoolId[billId], bill.amount);
        bill.status = Types.BillStatus.Cancelled;
        emit Events.BillCancelled(billId, msg.sender);
    }

    function closeBatch(uint256 batchId) external override {
        Types.Batch storage batch = _getExistingBatch(batchId);
        if (batch.status != Types.BatchStatus.Open) revert Errors.InvalidState();
        _checkBatchOwnerAuthorization(batchId);
        _closeBatch(batchId, batch);
    }

    function settleBatch(uint256 batchId) external override {
        Types.Batch storage batch = _getExistingBatch(batchId);
        if (batch.status != Types.BatchStatus.Closed) revert Errors.InvalidState();
        _checkBatchOwnerAuthorization(batchId);
        _settleBatch(batchId, batch);
    }

    /// @dev Convenience entry point for the demo-first core flow:
    /// close an open batch and settle it in one call.
    function closeAndSettleBatch(uint256 batchId) external override {
        Types.Batch storage batch = _getExistingBatch(batchId);
        if (batch.status == Types.BatchStatus.Open) {
            _checkBatchOwnerAuthorization(batchId);
            _closeBatch(batchId, batch);
        } else if (batch.status != Types.BatchStatus.Closed) {
            revert Errors.InvalidState();
        } else {
            _checkBatchOwnerAuthorization(batchId);
        }
        _settleBatch(batchId, batch);
    }

    function _getExistingBatch(uint256 batchId) internal view returns (Types.Batch storage batch) {
        batch = batches[batchId];
        if (batch.batchId == 0) revert Errors.NotFound();
    }

    function _closeBatch(uint256 batchId, Types.Batch storage batch) internal {
        batch.status = Types.BatchStatus.Closed;
        if (activeBatchByPool[batch.poolId] == batchId) {
            activeBatchByPool[batch.poolId] = 0;
        }
        emit Events.BatchClosed(batchId, batch.poolId);
    }

    function _settleBatch(uint256 batchId, Types.Batch storage batch) internal {
        uint256 totalSettled;
        uint256[] storage ids = batchBills[batchId];
        for (uint256 i = 0; i < ids.length; i++) {
            Types.Bill storage bill = bills[ids[i]];
            if (bill.status == Types.BillStatus.Confirmed) {
                lockPoolManager.settleFromPendingAndPayout(billPoolId[bill.billId], bill.toAgent, bill.amount);
                bill.status = Types.BillStatus.Settled;
                totalSettled += bill.amount;
            }
        }

        batch.status = Types.BatchStatus.Settled;
        batch.settledAt = block.timestamp;

        emit Events.BatchSettled(batchId, batch.poolId, totalSettled);
    }

    function _checkBillOwnerAuthorization(uint256 billId) internal view returns (address poolOwner) {
        bytes32 poolId = billPoolId[billId];
        poolOwner = lockPoolManager.getPoolOwner(poolId);
        if (poolOwner != msg.sender) revert Errors.Unauthorized();
    }

    function _checkBatchOwnerAuthorization(uint256 batchId) internal view {
        bytes32 poolId = batches[batchId].poolId;
        address poolOwner = lockPoolManager.getPoolOwner(poolId);
        if (poolOwner != msg.sender) revert Errors.Unauthorized();
    }
}
