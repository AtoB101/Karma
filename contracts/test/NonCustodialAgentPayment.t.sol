// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {NonCustodialAgentPayment} from "../core/NonCustodialAgentPayment.sol";
import {MockERC20} from "./mocks/MockERC20.sol";
import {INonCustodialAgentPayment} from "../interfaces/INonCustodialAgentPayment.sol";

contract NonCustodialAgentPaymentTest is Test {
    event InvalidTransferIntent(address indexed caller, uint256 indexed billId, string reason);
    event PolicyUpdated(
        address indexed buyer,
        bool enabled,
        uint256 perTxLimit,
        uint256 dailyLimit,
        uint256 maxTxPerMinute,
        uint256 validUntil
    );
    event PolicyViolation(address indexed buyer, string reason);

    NonCustodialAgentPayment internal protocol;
    MockERC20 internal token;

    uint256 internal buyerPk = 0xB0B;
    uint256 internal sellerPk = 0xCAFE;
    uint256 internal arbitratorPk = 0xA11CE;

    address internal buyer;
    address internal seller;
    address internal arbitrator;
    bytes32 internal constant EIP712_DOMAIN_TYPEHASH =
        keccak256("EIP712Domain(string name,string version,uint256 chainId,address verifyingContract)");
    bytes32 internal constant CONFIRM_BILL_TYPEHASH =
        keccak256("ConfirmBill(uint256 billId,uint256 nonce,uint256 deadline,address relayer)");

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

    function testSettleBatchProgressesWithSmallMaxBills() public {
        vm.startPrank(buyer);
        uint256 bill1 =
            protocol.createBill(seller, address(token), 1_000, keccak256("scope-p1"), "ipfs://proof-p1", block.timestamp + 1 days);
        uint256 bill2 =
            protocol.createBill(seller, address(token), 1_000, keccak256("scope-p2"), "ipfs://proof-p2", block.timestamp + 1 days);
        uint256 bill3 =
            protocol.createBill(seller, address(token), 1_000, keccak256("scope-p3"), "ipfs://proof-p3", block.timestamp + 1 days);
        protocol.confirmBill(bill1);
        protocol.confirmBill(bill2);
        protocol.confirmBill(bill3);
        vm.stopPrank();

        uint256 sellerBefore = token.balanceOf(seller);
        uint256 batchId = protocol.getBill(bill1).batchId;

        vm.prank(buyer);
        protocol.closeBatch(batchId);

        vm.prank(buyer);
        (uint256 c1, uint256 a1) = protocol.settleBatch(batchId, 1);
        vm.prank(buyer);
        (uint256 c2, uint256 a2) = protocol.settleBatch(batchId, 1);
        vm.prank(buyer);
        (uint256 c3, uint256 a3) = protocol.settleBatch(batchId, 1);

        assertEq(c1 + c2 + c3, 3);
        assertEq(a1 + a2 + a3, 3_000);
        assertEq(token.balanceOf(seller) - sellerBefore, 3_000);
        assertEq(uint8(protocol.getBatch(batchId).status), uint8(INonCustodialAgentPayment.BatchStatus.Settled));
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
        vm.expectRevert(
            abi.encodeWithSelector(
                NonCustodialAgentPayment.InvalidBatchStatus.selector,
                bill.batchId,
                INonCustodialAgentPayment.BatchStatus.Closed,
                INonCustodialAgentPayment.BatchStatus.Open
            )
        );
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

    function testConfirmBillBySignatureSuccess() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 3_000, keccak256("scope-sig1"), "ipfs://proof-sig1", block.timestamp + 1 days);

        uint256 nonce = protocol.confirmNonce(buyer);
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 digest = _confirmBillDigest(billId, nonce, deadline, address(this));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(buyerPk, digest);

        protocol.confirmBillBySignature(billId, deadline, v, r, s);
        INonCustodialAgentPayment.Bill memory b = protocol.getBill(billId);
        assertEq(uint8(b.status), uint8(INonCustodialAgentPayment.BillStatus.Confirmed));
        assertEq(protocol.confirmNonce(buyer), nonce + 1);
    }

    function testConfirmBillBySignatureRevertsOnReplay() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 3_000, keccak256("scope-sig2"), "ipfs://proof-sig2", block.timestamp + 1 days);

        uint256 nonce = protocol.confirmNonce(buyer);
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 digest = _confirmBillDigest(billId, nonce, deadline, address(this));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(buyerPk, digest);

        protocol.confirmBillBySignature(billId, deadline, v, r, s);
        vm.expectRevert(
            abi.encodeWithSelector(
                NonCustodialAgentPayment.InvalidBillStatus.selector,
                billId,
                INonCustodialAgentPayment.BillStatus.Pending,
                INonCustodialAgentPayment.BillStatus.Confirmed
            )
        );
        protocol.confirmBillBySignature(billId, deadline, v, r, s);
    }

    function testConfirmBillBySignatureRevertsOnBadSignature() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 3_000, keccak256("scope-sig3"), "ipfs://proof-sig3", block.timestamp + 1 days);

        uint256 nonce = protocol.confirmNonce(buyer);
        uint256 deadline = block.timestamp + 1 hours;
        bytes32 digest = _confirmBillDigest(billId, nonce, deadline, address(this));
        (uint8 v, bytes32 r, bytes32 s) = vm.sign(sellerPk, digest);

        vm.expectRevert(NonCustodialAgentPayment.InvalidSignature.selector);
        protocol.confirmBillBySignature(billId, deadline, v, r, s);
    }

    function testExpireBillRestoresBothPartiesReserved() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-exp"), "ipfs://proof-exp", block.timestamp + 1 days);

        INonCustodialAgentPayment.AccountState memory buyerBefore = protocol.getAccountState(buyer, address(token));
        INonCustodialAgentPayment.AccountState memory sellerBefore = protocol.getAccountState(seller, address(token));
        assertEq(buyerBefore.reserved, 10_000);
        assertEq(sellerBefore.reserved, 3_000);

        vm.warp(block.timestamp + 1 days + 1);
        vm.prank(address(0xdead));
        protocol.expireBill(billId);

        INonCustodialAgentPayment.AccountState memory buyerSt = protocol.getAccountState(buyer, address(token));
        INonCustodialAgentPayment.AccountState memory sellerSt = protocol.getAccountState(seller, address(token));
        INonCustodialAgentPayment.Bill memory b = protocol.getBill(billId);
        assertEq(buyerSt.active, 100_000);
        assertEq(buyerSt.reserved, 0);
        assertEq(sellerSt.active, 100_000);
        assertEq(sellerSt.reserved, 0);
        assertEq(uint8(b.status), uint8(INonCustodialAgentPayment.BillStatus.Expired));
        assertTrue(protocol.isAccountConsistent(buyer, address(token)));
        assertTrue(protocol.isAccountConsistent(seller, address(token)));
    }

    function testExpireBillRevertsBeforeDeadline() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-exp2"), "ipfs://proof-exp2", block.timestamp + 1 days);
        vm.expectRevert(NonCustodialAgentPayment.InvalidState.selector);
        protocol.expireBill(billId);
    }

    function testExpireBillWorksOnConfirmedState() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-exp3"), "ipfs://proof-exp3", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.warp(block.timestamp + 1 days + 1);
        protocol.expireBill(billId);
        INonCustodialAgentPayment.Bill memory b = protocol.getBill(billId);
        assertEq(uint8(b.status), uint8(INonCustodialAgentPayment.BillStatus.Expired));
    }

    function testExpireBillOnSettledFails() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-exp4"), "ipfs://proof-exp4", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        protocol.requestBillPayout(billId);
        vm.warp(block.timestamp + 1 days + 1);
        vm.expectRevert(NonCustodialAgentPayment.InvalidState.selector);
        protocol.expireBill(billId);
    }

    function testExpireBillAfterBuyerUnlock() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-exp5"), "ipfs://proof-exp5", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.unlockFunds(address(token), 90_000);
        vm.warp(block.timestamp + 1 days + 1);
        protocol.expireBill(billId);
        INonCustodialAgentPayment.AccountState memory sellerSt = protocol.getAccountState(seller, address(token));
        assertEq(sellerSt.active, 100_000);
        assertEq(sellerSt.reserved, 0);
    }

    function testResolveDisputeBuyerTransfersPenalty() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-db"), "ipfs://proof-db", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.prank(seller);
        protocol.disputeBill(billId);

        uint256 buyerBefore = token.balanceOf(buyer);
        uint256 sellerBefore = token.balanceOf(seller);
        vm.prank(arbitrator);
        protocol.resolveDisputeBuyer(billId);

        uint256 buyerAfter = token.balanceOf(buyer);
        uint256 sellerAfter = token.balanceOf(seller);
        INonCustodialAgentPayment.Bill memory b = protocol.getBill(billId);
        INonCustodialAgentPayment.AccountState memory buyerSt = protocol.getAccountState(buyer, address(token));
        INonCustodialAgentPayment.AccountState memory sellerSt = protocol.getAccountState(seller, address(token));
        assertEq(buyerAfter - buyerBefore, 3_000);
        assertEq(sellerBefore - sellerAfter, 3_000);
        assertEq(buyerSt.active, 100_000);
        assertEq(buyerSt.reserved, 0);
        assertEq(sellerSt.active, 97_000);
        assertEq(sellerSt.reserved, 0);
        assertEq(sellerSt.locked, 97_000);
        assertEq(uint8(b.status), uint8(INonCustodialAgentPayment.BillStatus.ResolvedBuyer));
    }

    function testResolveDisputeBuyerRevertsIfNotArbitrator() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-db2"), "ipfs://proof-db2", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.prank(seller);
        protocol.disputeBill(billId);
        vm.prank(buyer);
        vm.expectRevert(NonCustodialAgentPayment.Unauthorized.selector);
        protocol.resolveDisputeBuyer(billId);
    }

    function testResolveDisputeBuyerRevertsIfNotDisputed() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-db3"), "ipfs://proof-db3", block.timestamp + 1 days);
        vm.prank(arbitrator);
        vm.expectRevert(
            abi.encodeWithSelector(
                NonCustodialAgentPayment.InvalidBillStatus.selector,
                billId,
                INonCustodialAgentPayment.BillStatus.Disputed,
                INonCustodialAgentPayment.BillStatus.Pending
            )
        );
        protocol.resolveDisputeBuyer(billId);
    }

    function testResolveDisputeSellerTransfersPayment() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-ds"), "ipfs://proof-ds", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.prank(seller);
        protocol.disputeBill(billId);
        uint256 sellerBefore = token.balanceOf(seller);
        vm.prank(arbitrator);
        protocol.resolveDisputeSeller(billId);
        uint256 sellerAfter = token.balanceOf(seller);
        INonCustodialAgentPayment.Bill memory b = protocol.getBill(billId);
        INonCustodialAgentPayment.AccountState memory sellerSt = protocol.getAccountState(seller, address(token));
        assertEq(sellerAfter - sellerBefore, 10_000);
        assertEq(sellerSt.reserved, 0);
        assertEq(sellerSt.active, 100_000);
        assertEq(uint8(b.status), uint8(INonCustodialAgentPayment.BillStatus.ResolvedSeller));
    }

    function testResolveDisputeSellerRevertsIfNotArbitrator() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-ds2"), "ipfs://proof-ds2", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.prank(seller);
        protocol.disputeBill(billId);
        vm.prank(buyer);
        vm.expectRevert(NonCustodialAgentPayment.Unauthorized.selector);
        protocol.resolveDisputeSeller(billId);
    }

    function testSplitResolvedBuyerGetsZero() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-s0"), "ipfs://proof-s0", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.prank(seller);
        protocol.disputeBill(billId);
        uint256 sellerBefore = token.balanceOf(seller);
        vm.prank(arbitrator);
        protocol.resolveDisputeSplit(billId, 0);
        uint256 sellerAfter = token.balanceOf(seller);
        assertEq(sellerAfter - sellerBefore, 10_000);
    }

    function testSplitResolvedBuyerGetsAll() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-s1"), "ipfs://proof-s1", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.prank(seller);
        protocol.disputeBill(billId);
        uint256 buyerBefore = token.balanceOf(buyer);
        vm.prank(arbitrator);
        protocol.resolveDisputeSplit(billId, 10_000);
        uint256 buyerAfter = token.balanceOf(buyer);
        assertEq(buyerAfter - buyerBefore, 3_000);
    }

    function testSplitResolvedRevertsInvalidShare() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-s2"), "ipfs://proof-s2", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.prank(seller);
        protocol.disputeBill(billId);
        vm.prank(arbitrator);
        vm.expectRevert(NonCustodialAgentPayment.InvalidShare.selector);
        protocol.resolveDisputeSplit(billId, 10_001);
    }

    function testSplitResolvedFiftyFifty() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-s3"), "ipfs://proof-s3", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.prank(seller);
        protocol.disputeBill(billId);
        uint256 buyerBefore = token.balanceOf(buyer);
        uint256 sellerBefore = token.balanceOf(seller);
        vm.prank(arbitrator);
        protocol.resolveDisputeSplit(billId, 5000);
        uint256 buyerAfter = token.balanceOf(buyer);
        uint256 sellerAfter = token.balanceOf(seller);
        assertEq(buyerBefore - buyerAfter, 3_500);
        assertEq(sellerAfter - sellerBefore, 3_500);
    }

    function testInvalidTransferIntentBillNotFound() public {
        vm.expectEmit(true, true, true, true);
        emit InvalidTransferIntent(address(this), 999, "bill-not-found");
        bool ok = protocol.requestBillPayout(999);
        assertFalse(ok);
    }

    function testInvalidTransferIntentNotConfirmed() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-it"), "ipfs://proof-it", block.timestamp + 1 days);
        vm.expectEmit(true, true, true, true);
        emit InvalidTransferIntent(address(this), billId, "bill-not-confirmed");
        bool ok = protocol.requestBillPayout(billId);
        assertFalse(ok);
    }

    function testInvalidTransferIntentExpired() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-it2"), "ipfs://proof-it2", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.warp(block.timestamp + 1 days + 1);
        vm.expectEmit(true, true, true, true);
        emit InvalidTransferIntent(address(this), billId, "bill-expired");
        bool ok = protocol.requestBillPayout(billId);
        assertFalse(ok);
    }

    function testInvalidTransferIntentInsufficientAllowance() public {
        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 10_000, keccak256("scope-it3"), "ipfs://proof-it3", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.prank(buyer);
        token.approve(address(protocol), 0);
        vm.expectEmit(true, true, true, true);
        emit InvalidTransferIntent(address(this), billId, "buyer-capacity-insufficient");
        bool ok = protocol.requestBillPayout(billId);
        assertFalse(ok);
        INonCustodialAgentPayment.Bill memory b = protocol.getBill(billId);
        assertEq(uint8(b.status), uint8(INonCustodialAgentPayment.BillStatus.Confirmed));
    }

    function testConcurrentBillsMaintainInvariant() public {
        uint256[] memory billIds = new uint256[](5);
        for (uint256 i = 0; i < 5; i++) {
            vm.prank(buyer);
            billIds[i] = protocol.createBill(
                seller,
                address(token),
                5_000,
                keccak256(abi.encode(i)),
                string(abi.encodePacked("ipfs://proof-cb-", vm.toString(i))),
                block.timestamp + 1 days
            );
            assertTrue(protocol.isAccountConsistent(buyer, address(token)));
            assertTrue(protocol.isAccountConsistent(seller, address(token)));
        }

        vm.startPrank(buyer);
        protocol.confirmBill(billIds[0]);
        vm.stopPrank();
        protocol.requestBillPayout(billIds[0]);

        vm.startPrank(buyer);
        protocol.confirmBill(billIds[2]);
        protocol.cancelBill(billIds[4]);
        protocol.confirmBill(billIds[1]);
        vm.stopPrank();
        protocol.requestBillPayout(billIds[1]);
        protocol.requestBillPayout(billIds[2]);

        vm.startPrank(buyer);
        protocol.cancelBill(billIds[3]);
        vm.stopPrank();

        INonCustodialAgentPayment.AccountState memory buyerSt = protocol.getAccountState(buyer, address(token));
        INonCustodialAgentPayment.AccountState memory sellerSt = protocol.getAccountState(seller, address(token));
        assertEq(buyerSt.reserved, 0);
        assertEq(sellerSt.reserved, 0);
        assertTrue(protocol.isAccountConsistent(buyer, address(token)));
        assertTrue(protocol.isAccountConsistent(seller, address(token)));
    }

    function testSetPolicyAndReadBack() public {
        vm.prank(buyer);
        protocol.setPolicy(true, 20_000, 50_000, 10, block.timestamp + 1 days);

        INonCustodialAgentPayment.Policy memory p = protocol.getPolicy(buyer);
        assertTrue(p.enabled);
        assertEq(p.perTxLimit, 20_000);
        assertEq(p.dailyLimit, 50_000);
        assertEq(p.maxTxPerMinute, 10);
        assertGt(p.validUntil, block.timestamp);
    }

    function testCreateBillBlockedByPerTxPolicy() public {
        vm.prank(buyer);
        protocol.setPolicy(true, 3_000, 100_000, 0, block.timestamp + 1 days);

        vm.prank(buyer);
        vm.expectRevert(NonCustodialAgentPayment.PolicyViolation.selector);
        protocol.createBill(seller, address(token), 4_000, keccak256("scope-policy-1"), "ipfs://proof-policy-1", block.timestamp + 1 days);
    }

    function testCreateBillBlockedByDailyPolicy() public {
        vm.prank(buyer);
        protocol.setPolicy(true, 10_000, 5_000, 0, block.timestamp + 1 days);

        vm.prank(buyer);
        protocol.createBill(seller, address(token), 3_000, keccak256("scope-policy-2"), "ipfs://proof-policy-2", block.timestamp + 1 days);
        vm.prank(buyer);
        vm.expectRevert(NonCustodialAgentPayment.PolicyViolation.selector);
        protocol.createBill(seller, address(token), 3_000, keccak256("scope-policy-3"), "ipfs://proof-policy-3", block.timestamp + 1 days);
    }

    function testCreateBillBlockedByPolicyExpiry() public {
        vm.prank(buyer);
        protocol.setPolicy(true, 10_000, 100_000, 0, block.timestamp + 10);
        vm.warp(block.timestamp + 11);

        vm.prank(buyer);
        vm.expectRevert(NonCustodialAgentPayment.PolicyViolation.selector);
        protocol.createBill(seller, address(token), 1_000, keccak256("scope-policy-4"), "ipfs://proof-policy-4", block.timestamp + 1 days);
    }

    function testCreateBillBlockedByRateLimit() public {
        vm.prank(buyer);
        protocol.setPolicy(true, 10_000, 100_000, 1, block.timestamp + 1 days);

        vm.prank(buyer);
        protocol.createBill(seller, address(token), 1_000, keccak256("scope-policy-5"), "ipfs://proof-policy-5", block.timestamp + 1 days);
        vm.prank(buyer);
        vm.expectRevert(NonCustodialAgentPayment.PolicyViolation.selector);
        protocol.createBill(seller, address(token), 1_000, keccak256("scope-policy-6"), "ipfs://proof-policy-6", block.timestamp + 1 days);
    }

    function testPolicyUsageResetsNextDay() public {
        vm.prank(buyer);
        protocol.setPolicy(true, 10_000, 5_000, 0, block.timestamp + 2 days);

        vm.prank(buyer);
        protocol.createBill(seller, address(token), 4_000, keccak256("scope-policy-7"), "ipfs://proof-policy-7", block.timestamp + 1 days);
        (, uint256 spentDay0,, uint256 day0) = protocol.getPolicyUsage(buyer);
        assertEq(spentDay0, 4_000);

        vm.warp(block.timestamp + 1 days + 1);
        vm.prank(buyer);
        protocol.createBill(seller, address(token), 4_000, keccak256("scope-policy-8"), "ipfs://proof-policy-8", block.timestamp + 1 days);
        (, uint256 spentDay1,, uint256 day1) = protocol.getPolicyUsage(buyer);
        assertEq(spentDay1, 4_000);
        assertGt(day1, day0);
    }

    function testCloseBatchBlockedByPolicyWhenNoScopeRule() public {
        vm.prank(buyer);
        protocol.setPolicy(true, 50_000, 100_000, 0, block.timestamp + 1 days);

        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 1_000, keccak256("scope-policy-batch"), "ipfs://proof-policy-batch", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        uint256 batchId = protocol.getBill(billId).batchId;

        vm.prank(buyer);
        vm.expectRevert(NonCustodialAgentPayment.PolicyViolation.selector);
        protocol.closeBatch(batchId);
    }

    function testCloseBatchAllowedAfterScopeRule() public {
        vm.prank(buyer);
        protocol.setPolicy(true, 50_000, 100_000, 0, block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.setPolicyAllowedScope(keccak256("action:batch:close"), true);

        vm.prank(buyer);
        uint256 billId =
            protocol.createBill(seller, address(token), 1_000, keccak256("scope-policy-batch-allow"), "ipfs://proof-policy-batch-allow", block.timestamp + 1 days);
        vm.prank(buyer);
        protocol.confirmBill(billId);
        uint256 batchId = protocol.getBill(billId).batchId;

        vm.prank(buyer);
        protocol.closeBatch(batchId);
        assertEq(uint8(protocol.getBatch(batchId).status), uint8(INonCustodialAgentPayment.BatchStatus.Closed));
    }

    function _confirmBillDigest(uint256 billId, uint256 nonce, uint256 deadline, address relayer)
        internal
        view
        returns (bytes32)
    {
        bytes32 domainSeparator = keccak256(
            abi.encode(
                EIP712_DOMAIN_TYPEHASH,
                keccak256("NonCustodialAgentPayment"),
                keccak256("1"),
                block.chainid,
                address(protocol)
            )
        );
        bytes32 structHash = keccak256(abi.encode(CONFIRM_BILL_TYPEHASH, billId, nonce, deadline, relayer));
        return keccak256(abi.encodePacked("\x19\x01", domainSeparator, structHash));
    }
}
