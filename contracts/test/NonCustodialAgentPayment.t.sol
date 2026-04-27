// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {NonCustodialAgentPayment} from "../core/NonCustodialAgentPayment.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {INonCustodialAgentPayment} from "../interfaces/INonCustodialAgentPayment.sol";

contract NonCustodialAgentPaymentTest is Test {
    NonCustodialAgentPayment internal protocol;
    MockERC20 internal token;

    uint256 internal buyerPk = 0xB0B;
    uint256 internal sellerPk = 0xCAFE;
    uint256 internal arbitratorPk = 0xA11CE;

    address internal buyer;
    address internal seller;
    address internal arbitrator;

    function setUp() public {
        buyer = vm.addr(buyerPk);
        seller = vm.addr(sellerPk);
        arbitrator = vm.addr(arbitratorPk);

        protocol = new NonCustodialAgentPayment(arbitrator, 3000, 1 days);
        token = new MockERC20();

        token.mint(buyer, 1_000_000);
        token.mint(seller, 1_000_000);

        vm.prank(buyer);
        token.approve(address(protocol), type(uint256).max);
        vm.prank(seller);
        token.approve(address(protocol), type(uint256).max);

        vm.prank(buyer);
        protocol.lockFunds(address(token), 100_000);
        vm.prank(seller);
        protocol.lockFunds(address(token), 100_000);
    }

    function testCreateBillReservesBuyerAndSeller() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope"), "ipfs://proof-1", block.timestamp + 1 days);

        INonCustodialAgentPayment.AccountState memory buyerState = protocol.getAccountState(buyer, address(token));
        INonCustodialAgentPayment.AccountState memory sellerState = protocol.getAccountState(seller, address(token));
        INonCustodialAgentPayment.Bill memory b = protocol.getBill(billId);

        assertEq(buyerState.active, 90_000);
        assertEq(buyerState.reserved, 10_000);
        assertEq(sellerState.active, 97_000);
        assertEq(sellerState.reserved, 3_000);
        assertEq(uint8(b.status), uint8(INonCustodialAgentPayment.BillStatus.Pending));
        assertTrue(protocol.isAccountConsistent(buyer, address(token)));
        assertTrue(protocol.isAccountConsistent(seller, address(token)));
    }

    function testConfirmedBillCanSettleAndReleaseBond() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope"), "ipfs://proof-2", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);

        uint256 sellerBefore = token.balanceOf(seller);
        bool ok = protocol.requestBillPayout(billId);
        uint256 sellerAfter = token.balanceOf(seller);

        assertTrue(ok);
        assertEq(sellerAfter - sellerBefore, 10_000);

        INonCustodialAgentPayment.AccountState memory buyerState = protocol.getAccountState(buyer, address(token));
        INonCustodialAgentPayment.AccountState memory sellerState = protocol.getAccountState(seller, address(token));
        INonCustodialAgentPayment.Bill memory b = protocol.getBill(billId);

        assertEq(buyerState.locked, 90_000);
        assertEq(buyerState.reserved, 0);
        assertEq(sellerState.active, 100_000);
        assertEq(sellerState.reserved, 0);
        assertEq(uint8(b.status), uint8(INonCustodialAgentPayment.BillStatus.Settled));
        assertTrue(protocol.isAccountConsistent(buyer, address(token)));
        assertTrue(protocol.isAccountConsistent(seller, address(token)));
    }

    function testCancelRestoresReservedToActive() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope"), "ipfs://proof-3", block.timestamp + 1 days);

        vm.prank(buyer);
        protocol.cancelBill(billId);

        INonCustodialAgentPayment.AccountState memory buyerState = protocol.getAccountState(buyer, address(token));
        INonCustodialAgentPayment.AccountState memory sellerState = protocol.getAccountState(seller, address(token));
        INonCustodialAgentPayment.Bill memory b = protocol.getBill(billId);

        assertEq(buyerState.active, 100_000);
        assertEq(buyerState.reserved, 0);
        assertEq(sellerState.active, 100_000);
        assertEq(sellerState.reserved, 0);
        assertEq(uint8(b.status), uint8(INonCustodialAgentPayment.BillStatus.Cancelled));
        assertTrue(protocol.isAccountConsistent(buyer, address(token)));
        assertTrue(protocol.isAccountConsistent(seller, address(token)));
    }

    function testUnlockCannotTouchReserved() public {
        vm.prank(buyer);
        protocol.createBill(seller, address(token), 10_000, keccak256("scope"), "ipfs://proof-4", block.timestamp + 1 days);

        vm.prank(buyer);
        vm.expectRevert();
        protocol.unlockFunds(address(token), 95_000);
    }

    function testSplitResolvedWorksInV1() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope"), "ipfs://proof-5", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.prank(seller);
        protocol.disputeBill(billId);

        uint256 buyerBefore = token.balanceOf(buyer);
        uint256 sellerBefore = token.balanceOf(seller);

        vm.prank(arbitrator);
        protocol.resolveDisputeSplit(billId, 2000); // buyer 20% share

        uint256 buyerAfter = token.balanceOf(buyer);
        uint256 sellerAfter = token.balanceOf(seller);
        INonCustodialAgentPayment.Bill memory b = protocol.getBill(billId);

        // buyer pays 80% of bill (8_000) and receives 20% of seller bond (600)
        assertEq(buyerBefore - buyerAfter, 7_400);
        assertEq(sellerAfter - sellerBefore, 7_400);
        assertEq(uint8(b.status), uint8(INonCustodialAgentPayment.BillStatus.SplitResolved));
        assertTrue(protocol.isAccountConsistent(buyer, address(token)));
        assertTrue(protocol.isAccountConsistent(seller, address(token)));
    }

    function testBatchCloseAndSettleFlow() public {
        vm.startPrank(buyer);
        uint256 bill1 =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-a"), "ipfs://proof-a", block.timestamp + 1 days);
        uint256 bill2 =
            protocol.createBill(seller, address(token), 5_000, keccak256("scope-b"), "ipfs://proof-b", block.timestamp + 1 days);
        protocol.confirmBill(bill1);
        protocol.confirmBill(bill2);
        vm.stopPrank();

        INonCustodialAgentPayment.Bill memory b1 = protocol.getBill(bill1);
        INonCustodialAgentPayment.Batch memory batchBefore = protocol.getBatch(b1.batchId);
        assertEq(uint8(batchBefore.status), uint8(INonCustodialAgentPayment.BatchStatus.Open));
        assertEq(batchBefore.totalPending, 15_000);

        vm.prank(buyer);
        protocol.closeBatch(b1.batchId);
        vm.prank(buyer);
        (uint256 settledCount, uint256 settledAmount) = protocol.settleBatch(b1.batchId, 0);
        assertEq(settledCount, 2);
        assertEq(settledAmount, 15_000);

        INonCustodialAgentPayment.Batch memory batchAfter = protocol.getBatch(b1.batchId);
        assertEq(uint8(batchAfter.status), uint8(INonCustodialAgentPayment.BatchStatus.Settled));
        assertEq(batchAfter.totalPending, 0);
    }

    function testCloseBatchRevertsWithBatchNotFound() public {
        vm.prank(buyer);
        vm.expectRevert(NonCustodialAgentPayment.BatchNotFound.selector);
        protocol.closeBatch(999_999);
    }

    function testSettleBatchRevertsWhenBatchNotClosed() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 2_000, keccak256("scope-c"), "ipfs://proof-c", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        INonCustodialAgentPayment.Bill memory bill = protocol.getBill(billId);

        vm.prank(buyer);
        vm.expectRevert(NonCustodialAgentPayment.BatchNotClosed.selector);
        protocol.settleBatch(bill.batchId, 0);
    }

    function testCloseBatchRevertsForNonOwner() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 2_000, keccak256("scope-d"), "ipfs://proof-d", block.timestamp + 1 days);
        INonCustodialAgentPayment.Bill memory bill = protocol.getBill(billId);

        vm.prank(seller);
        vm.expectRevert(NonCustodialAgentPayment.BatchOwnerMismatch.selector);
        protocol.closeBatch(bill.batchId);
    }
}
