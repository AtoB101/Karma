// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KYARegistry} from "../core/KYARegistry.sol";
import {LockPoolManager} from "../core/LockPoolManager.sol";
import {CircuitBreaker} from "../core/CircuitBreaker.sol";
import {AuthTokenManager} from "../core/AuthTokenManager.sol";
import {BillManager} from "../core/BillManager.sol";
import {Types} from "../libraries/Types.sol";
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

    function testScenario_EndToEndPaymentFlow() public {
        // 1) DID registration
        vm.prank(owner);
        registry.registerDID{value: 0.01 ether}(buyerAgent, keccak256("buyer-perm"), 30);
        vm.prank(sellerAgent);
        registry.registerDID{value: 0.01 ether}(sellerAgent, keccak256("seller-perm"), 30);

        // 2) Lock pool creation
        vm.prank(owner);
        bytes32 poolId = pool.createLockPool(buyerAgent, address(token), 10_000);
        assertEq(pool.getMappingBalance(poolId), 10_000, "mapping balance mismatch");

        // 3) Signed create bill
        (bytes32 createTokenId, uint256 createDeadline, uint8 cv, bytes32 cr, bytes32 cs) =
            issueAndSignAuth(auth, buyerAgentPk, buyerAgent, Types.OperationType.CreateBill, 500);
        vm.prank(buyerAgent);
        uint256 billId = bill.createBill(
            poolId,
            sellerAgent,
            500,
            "compute-task",
            "ipfs://proof",
            createTokenId,
            createDeadline,
            cv,
            cr,
            cs
        );

        // 4) Signed confirm bill by pool owner
        (bytes32 confirmTokenId, uint256 confirmDeadline, uint8 fv, bytes32 fr, bytes32 fs) =
            issueAndSignAuth(auth, ownerPk, owner, Types.OperationType.ConfirmBill, 500);
        vm.prank(owner);
        bill.confirmBill(billId, confirmTokenId, confirmDeadline, fv, fr, fs);

        // 5) Close & settle batch by owner
        vm.prank(owner);
        bill.closeBatch(1);
        uint256 sellerBefore = token.balanceOf(sellerAgent);
        vm.prank(owner);
        bill.settleBatch(1);
        uint256 sellerAfter = token.balanceOf(sellerAgent);

        // 6) Assertions
        assertEq(sellerAfter - sellerBefore, 500, "seller payout mismatch");
        (, , , , uint256 totalLocked, uint256 mappingBalance, uint256 pendingAmount, uint256 settledAmount, ,) =
            pool.pools(poolId);
        assertEq(totalLocked, mappingBalance + pendingAmount, "escrow conservation broken");
        assertEq(settledAmount, 500, "settled amount mismatch");
    }
}
