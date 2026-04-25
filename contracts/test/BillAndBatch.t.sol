// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KYARegistry} from "../core/KYARegistry.sol";
import {LockPoolManager} from "../core/LockPoolManager.sol";
import {CircuitBreaker} from "../core/CircuitBreaker.sol";
import {BillManager} from "../core/BillManager.sol";
import {AuthTokenManager} from "../core/AuthTokenManager.sol";
import {Errors} from "../libraries/Errors.sol";
import {Types} from "../libraries/Types.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {AuthTestHelper} from "./helpers/AuthTestHelper.sol";

contract BillAndBatchTest is AuthTestHelper {
    KYARegistry internal registry;
    LockPoolManager internal pool;
    CircuitBreaker internal breaker;
    BillManager internal bill;
    AuthTokenManager internal auth;
    MockERC20 internal tokenContract;
    uint256 internal payerPk = 0x1111;
    uint256 internal payeePk = 0xBEEF;
    address internal payerAgent;
    address internal payeeAgent;

    function setUp() public {
        registry = new KYARegistry();
        pool = new LockPoolManager(address(registry));
        breaker = new CircuitBreaker(address(this));
        auth = new AuthTokenManager();
        bill = new BillManager(address(pool), address(registry), address(breaker), address(auth));
        pool.setBillManager(address(bill));
        tokenContract = new MockERC20();
        payerAgent = vm.addr(payerPk);
        payeeAgent = vm.addr(payeePk);
        vm.deal(payerAgent, 1 ether);
        vm.deal(payeeAgent, 1 ether);
        tokenContract.mint(payerAgent, 1_000_000);
        vm.prank(payerAgent);
        tokenContract.approve(address(pool), type(uint256).max);
    }

    function testCreateConfirmCloseSettleFlow() public {
        vm.prank(payerAgent);
        registry.registerDID{value: 0.01 ether}(payerAgent, keccak256("payer"), 30);
        vm.prank(payeeAgent);
        registry.registerDID{value: 0.01 ether}(payeeAgent, keccak256("payee"), 30);
        vm.prank(payerAgent);
        bytes32 poolId = pool.createLockPool(payerAgent, address(tokenContract), 1000);

        vm.prank(payerAgent);
        (bytes32 createTokenId, uint256 createDeadline, uint8 cv, bytes32 cr, bytes32 cs) =
            issueAndSignAuth(auth, payerPk, payerAgent, Types.OperationType.CreateBill, 100);
        uint256 billId =
            bill.createBill(poolId, payeeAgent, 100, "api call", "ipfs://proof", createTokenId, createDeadline, cv, cr, cs);
        vm.prank(payerAgent);
        (bytes32 confirmTokenId, uint256 confirmDeadline, uint8 fv, bytes32 fr, bytes32 fs) =
            issueAndSignAuth(auth, payerPk, payerAgent, Types.OperationType.ConfirmBill, 100);
        bill.confirmBill(billId, confirmTokenId, confirmDeadline, fv, fr, fs);
        vm.prank(payerAgent);
        bill.closeBatch(1);
        vm.prank(payerAgent);
        bill.settleBatch(1);

        (
            uint256 loadedBatchId,
            bytes32 loadedPoolId,
            uint256 totalPending,
            uint256 billCount,
            uint8 status,
            uint256 createdAt,
            uint256 settledAt
        ) = bill.batches(1);
        assertEq(loadedBatchId, 1, "batch id");
        assertEq(loadedPoolId, poolId, "pool id");
        assertEq(totalPending, 100, "pending snapshot");
        assertEq(billCount, 1, "bill count");
        assertEq(status, uint8(2), "status should be Settled");
        assertGt(createdAt, 0, "createdAt");
        assertGt(settledAt, 0, "settledAt");
    }

    function testCloseAndSettleBatchFlow() public {
        vm.prank(payerAgent);
        registry.registerDID{value: 0.01 ether}(payerAgent, keccak256("payer"), 30);
        vm.prank(payeeAgent);
        registry.registerDID{value: 0.01 ether}(payeeAgent, keccak256("payee"), 30);
        vm.prank(payerAgent);
        bytes32 poolId = pool.createLockPool(payerAgent, address(tokenContract), 1000);

        vm.prank(payerAgent);
        (bytes32 createTokenId, uint256 createDeadline, uint8 cv, bytes32 cr, bytes32 cs) =
            issueAndSignAuth(auth, payerPk, payerAgent, Types.OperationType.CreateBill, 100);
        uint256 billId =
            bill.createBill(poolId, payeeAgent, 100, "api call", "ipfs://proof", createTokenId, createDeadline, cv, cr, cs);

        vm.prank(payerAgent);
        (bytes32 confirmTokenId, uint256 confirmDeadline, uint8 fv, bytes32 fr, bytes32 fs) =
            issueAndSignAuth(auth, payerPk, payerAgent, Types.OperationType.ConfirmBill, 100);
        bill.confirmBill(billId, confirmTokenId, confirmDeadline, fv, fr, fs);

        uint256 payeeBefore = tokenContract.balanceOf(payeeAgent);
        vm.prank(payerAgent);
        bill.closeAndSettleBatch(1);
        uint256 payeeAfter = tokenContract.balanceOf(payeeAgent);

        assertEq(payeeAfter - payeeBefore, 100, "payee should receive settled amount");
        (, , , , uint8 status,,) = bill.batches(1);
        assertEq(status, uint8(Types.BatchStatus.Settled), "batch should be settled");
    }

    function testCreateBillRevertsWhenGlobalPaused() public {
        vm.prank(payerAgent);
        registry.registerDID{value: 0.01 ether}(payerAgent, keccak256("payer"), 30);
        vm.prank(payeeAgent);
        registry.registerDID{value: 0.01 ether}(payeeAgent, keccak256("payee"), 30);
        vm.prank(payerAgent);
        bytes32 poolId = pool.createLockPool(payerAgent, address(tokenContract), 1000);

        breaker.emergencyPause("incident");
        vm.prank(payerAgent);
        vm.expectRevert(Errors.CircuitBreakerActive.selector);
        (bytes32 createTokenId, uint256 createDeadline, uint8 cv, bytes32 cr, bytes32 cs) =
            issueAndSignAuth(auth, payerPk, payerAgent, Types.OperationType.CreateBill, 100);
        bill.createBill(poolId, payeeAgent, 100, "api call", "ipfs://proof", createTokenId, createDeadline, cv, cr, cs);
    }

    function testUnauthorizedAddressCannotConfirmOrCancelBill() public {
        vm.prank(payerAgent);
        registry.registerDID{value: 0.01 ether}(payerAgent, keccak256("payer"), 30);
        vm.prank(payeeAgent);
        registry.registerDID{value: 0.01 ether}(payeeAgent, keccak256("payee"), 30);
        vm.prank(payerAgent);
        bytes32 poolId = pool.createLockPool(payerAgent, address(tokenContract), 1000);

        vm.prank(payerAgent);
        (bytes32 createTokenId, uint256 createDeadline, uint8 cv, bytes32 cr, bytes32 cs) =
            issueAndSignAuth(auth, payerPk, payerAgent, Types.OperationType.CreateBill, 100);
        uint256 billId =
            bill.createBill(poolId, payeeAgent, 100, "api call", "ipfs://proof", createTokenId, createDeadline, cv, cr, cs);

        vm.prank(payeeAgent);
        vm.expectRevert(Errors.Unauthorized.selector);
        (bytes32 confirmTokenId, uint256 confirmDeadline, uint8 fv, bytes32 fr, bytes32 fs) =
            issueAndSignAuth(auth, payeePk, payeeAgent, Types.OperationType.ConfirmBill, 100);
        bill.confirmBill(billId, confirmTokenId, confirmDeadline, fv, fr, fs);

        vm.prank(payeeAgent);
        vm.expectRevert(Errors.Unauthorized.selector);
        (bytes32 cancelTokenId, uint256 cancelDeadline, uint8 xv, bytes32 xr, bytes32 xs) =
            issueAndSignAuth(auth, payeePk, payeeAgent, Types.OperationType.CancelBill, 100);
        bill.cancelBill(billId, cancelTokenId, cancelDeadline, xv, xr, xs);
    }

    function testUnauthorizedAddressCannotCloseOrSettleBatch() public {
        vm.prank(payerAgent);
        registry.registerDID{value: 0.01 ether}(payerAgent, keccak256("payer"), 30);
        vm.prank(payeeAgent);
        registry.registerDID{value: 0.01 ether}(payeeAgent, keccak256("payee"), 30);
        vm.prank(payerAgent);
        bytes32 poolId = pool.createLockPool(payerAgent, address(tokenContract), 1000);

        vm.prank(payerAgent);
        (bytes32 createTokenId, uint256 createDeadline, uint8 cv, bytes32 cr, bytes32 cs) =
            issueAndSignAuth(auth, payerPk, payerAgent, Types.OperationType.CreateBill, 100);
        uint256 billId =
            bill.createBill(poolId, payeeAgent, 100, "api call", "ipfs://proof", createTokenId, createDeadline, cv, cr, cs);
        vm.prank(payerAgent);
        (bytes32 confirmTokenId, uint256 confirmDeadline, uint8 fv, bytes32 fr, bytes32 fs) =
            issueAndSignAuth(auth, payerPk, payerAgent, Types.OperationType.ConfirmBill, 100);
        bill.confirmBill(billId, confirmTokenId, confirmDeadline, fv, fr, fs);

        vm.prank(payeeAgent);
        vm.expectRevert(Errors.Unauthorized.selector);
        bill.closeBatch(1);

        vm.prank(payerAgent);
        bill.closeBatch(1);

        vm.prank(payeeAgent);
        vm.expectRevert(Errors.Unauthorized.selector);
        bill.settleBatch(1);
    }
}
