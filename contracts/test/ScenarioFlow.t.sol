// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KYARegistry} from "../core/KYARegistry.sol";
import {LockPoolManager} from "../core/LockPoolManager.sol";
import {CircuitBreaker} from "../core/CircuitBreaker.sol";
import {AuthTokenManager} from "../core/AuthTokenManager.sol";
import {BillManager} from "../core/BillManager.sol";
import {Types} from "../libraries/Types.sol";
import {Errors} from "../libraries/Errors.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {AuthTestHelper} from "./helpers/AuthTestHelper.sol";

contract ScenarioFlowTest is AuthTestHelper {
    KYARegistry internal registry;
    LockPoolManager internal pool;
    CircuitBreaker internal breaker;
    AuthTokenManager internal auth;
    BillManager internal bill;
    MockERC20 internal token;

    uint256 internal ownerPk = 0x1001;
    uint256 internal buyerAgentPk = 0x1002;
    uint256 internal sellerAgentPk = 0x1003;

    address internal owner;
    address internal buyerAgent;
    address internal sellerAgent;

    function setUp() public {
        owner = vm.addr(ownerPk);
        buyerAgent = vm.addr(buyerAgentPk);
        sellerAgent = vm.addr(sellerAgentPk);

        registry = new KYARegistry();
        pool = new LockPoolManager(address(registry));
        breaker = new CircuitBreaker(address(this));
        auth = new AuthTokenManager();
        bill = new BillManager(address(pool), address(registry), address(breaker), address(auth));
        pool.setBillManager(address(bill));
        token = new MockERC20();

        vm.deal(owner, 10 ether);
        vm.deal(buyerAgent, 10 ether);
        vm.deal(sellerAgent, 10 ether);
        token.mint(owner, 1_000_000);
        vm.prank(owner);
        token.approve(address(pool), type(uint256).max);
    }

    function _registerScenarioDIDs() internal {
        vm.prank(owner);
        registry.registerDID{value: 0.01 ether}(buyerAgent, keccak256("buyer-perm"), 30);
        vm.prank(sellerAgent);
        registry.registerDID{value: 0.01 ether}(sellerAgent, keccak256("seller-perm"), 30);
    }

    function _createScenarioPool() internal returns (bytes32 poolId) {
        vm.prank(owner);
        poolId = pool.createLockPool(buyerAgent, address(token), 10_000);
        assertEq(pool.getMappingBalance(poolId), 10_000, "mapping balance mismatch");
    }

    function _createBillWithSignedAuth(bytes32 poolId, uint256 amount) internal returns (uint256 billId) {
        (bytes32 tokenId, uint256 deadline, uint8 v, bytes32 r, bytes32 s) =
            issueAndSignAuth(auth, buyerAgentPk, buyerAgent, Types.OperationType.CreateBill, amount);
        vm.prank(buyerAgent);
        billId = bill.createBill(poolId, sellerAgent, amount, "compute-task", "ipfs://proof", tokenId, deadline, v, r, s);
    }

    function _confirmBillWithSignedAuth(uint256 billId, uint256 amount) internal {
        (bytes32 tokenId, uint256 deadline, uint8 v, bytes32 r, bytes32 s) =
            issueAndSignAuth(auth, ownerPk, owner, Types.OperationType.ConfirmBill, amount);
        vm.prank(owner);
        bill.confirmBill(billId, tokenId, deadline, v, r, s);
    }

    function testScenario_EndToEndPaymentFlow() public {
        _registerScenarioDIDs();
        bytes32 poolId = _createScenarioPool();
        uint256 billId = _createBillWithSignedAuth(poolId, 500);
        _confirmBillWithSignedAuth(billId, 500);

        // 5) Close & settle batch by owner (single focused entry point)
        uint256 sellerBefore = token.balanceOf(sellerAgent);
        vm.prank(owner);
        bill.closeAndSettleBatch(1);
        uint256 sellerAfter = token.balanceOf(sellerAgent);

        assertEq(sellerAfter - sellerBefore, 500, "seller payout mismatch");
        (uint256 totalLocked, uint256 mappingBalance, uint256 pendingAmount, uint256 settledAmount) =
            pool.getPoolAccounting(poolId);
        assertEq(totalLocked, mappingBalance + pendingAmount, "escrow conservation broken");
        assertEq(settledAmount, 500, "settled amount mismatch");
    }

    function testScenario_ReplayAuthIsRejected() public {
        _registerScenarioDIDs();
        bytes32 poolId = _createScenarioPool();

        (bytes32 createTokenId, uint256 createDeadline, uint8 cv, bytes32 cr, bytes32 cs) =
            issueAndSignAuth(auth, buyerAgentPk, buyerAgent, Types.OperationType.CreateBill, 500);

        vm.prank(buyerAgent);
        bill.createBill(poolId, sellerAgent, 500, "compute-task", "ipfs://proof", createTokenId, createDeadline, cv, cr, cs);

        vm.prank(buyerAgent);
        vm.expectRevert(Errors.TokenUsed.selector);
        bill.createBill(poolId, sellerAgent, 500, "compute-task", "ipfs://proof", createTokenId, createDeadline, cv, cr, cs);
    }

    function testScenario_ExpiredAuthDeadlineIsRejected() public {
        _registerScenarioDIDs();
        bytes32 poolId = _createScenarioPool();

        vm.prank(buyerAgent);
        bytes32 tokenId = auth.issueAuthToken(buyerAgent, Types.OperationType.CreateBill, 500, 1 days);
        uint256 expiredDeadline = block.timestamp + 10;
        bytes32 digest = auth.getAuthDigest(tokenId, buyerAgent, Types.OperationType.CreateBill, 500, expiredDeadline);
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(buyerAgentPk, digest);

        vm.warp(expiredDeadline + 1);
        vm.prank(buyerAgent);
        vm.expectRevert(Errors.DeadlineExpired.selector);
        bill.createBill(poolId, sellerAgent, 500, "compute-task", "ipfs://proof", tokenId, expiredDeadline, v, r, s);
    }
}
