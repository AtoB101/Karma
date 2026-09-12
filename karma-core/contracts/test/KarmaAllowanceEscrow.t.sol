// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaAllowanceEscrow} from "../core/KarmaAllowanceEscrow.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

/// @notice v2 non-custodial settlement: the money stays in the payer's wallet,
///         the contract only records responsibility and executes the pull.
contract KarmaAllowanceEscrowTest is Test {
    KarmaAllowanceEscrow internal escrow;
    MockERC20 internal token;

    address internal buyer = address(0xB0B0);
    address internal seller = address(0x5E11E5);
    address internal executor = address(0xE0E0); // Karma settlement executor / agent
    address internal stranger = address(0xBAD);

    uint256 internal constant PRICE = 30e6;
    uint256 internal constant STAKE = 9e6; // 30% of PRICE

    uint256 internal constant DISPUTE_WINDOW = 60;
    uint256 internal constant SETTLE_DELAY = 30;

    event Settled(uint256 indexed bindingId, address from, address to, address token, uint256 amount);

    function setUp() public {
        escrow = new KarmaAllowanceEscrow(DISPUTE_WINDOW, SETTLE_DELAY);
        token = new MockERC20();
        escrow.setTokenAllowed(address(token), true);

        token.mint(buyer, 1_000e6);
        token.mint(seller, 1_000e6);
    }

    // ───────────────────────────────────────────────────────────── helpers

    function _commit(address owner, uint256 amount, address operator) internal returns (uint256 billId) {
        vm.startPrank(owner);
        token.approve(address(escrow), amount);
        billId = escrow.commit(address(token), amount, operator);
        vm.stopPrank();
    }

    function _bind(uint256 buyerBill, uint256 sellerBill, uint256 amount, uint256 stake)
        internal
        returns (uint256 bindingId)
    {
        vm.prank(executor);
        bindingId = escrow.bind(buyerBill, sellerBill, keccak256("task-1"), amount, stake);
    }

    function _openPair() internal returns (uint256 buyerBill, uint256 sellerBill) {
        buyerBill = _commit(buyer, 1_000e6, executor);
        sellerBill = _commit(seller, 1_000e6, executor);
    }

    // ────────────────────────────────────────────────────────── committing

    function testCommitRecordsResponsibilityWithoutMovingFunds() public {
        uint256 billId = _commit(buyer, 500e6, executor);

        assertEq(billId, 1);
        assertEq(token.balanceOf(buyer), 1_000e6, "money must stay in the wallet");
        assertEq(token.balanceOf(address(escrow)), 0, "escrow must never hold funds");

        KarmaAllowanceEscrow.Bill memory bill = escrow.getBill(billId);
        assertEq(bill.owner, buyer);
        assertEq(bill.operator, executor);
        assertEq(bill.amount, 500e6);
        assertEq(escrow.available(billId), 500e6);
        assertTrue(escrow.checkNoCustody(address(token)));
    }

    function testCommitRequiresAllowance() public {
        vm.prank(buyer);
        vm.expectRevert(
            abi.encodeWithSelector(KarmaAllowanceEscrow.InsufficientAllowance.selector, 0, 500e6)
        );
        escrow.commit(address(token), 500e6, executor);
    }

    function testCommitRejectsUnknownToken() public {
        MockERC20 other = new MockERC20();
        other.mint(buyer, 10e6);
        vm.startPrank(buyer);
        other.approve(address(escrow), 10e6);
        vm.expectRevert(KarmaAllowanceEscrow.TokenNotAllowed.selector);
        escrow.commit(address(other), 10e6, executor);
        vm.stopPrank();
    }

    // ───────────────────────────────────────────────────────────── binding

    /// The whole point of v2: the buyer signs once (approve + commit) and the
    /// operator drives every later order without touching the buyer's key.
    function testOperatorBindsWithoutBuyerSignature() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();

        vm.prank(executor);
        uint256 bindingId = escrow.bind(buyerBill, sellerBill, keccak256("order-1"), PRICE, STAKE);

        assertEq(bindingId, 1);
        KarmaAllowanceEscrow.Binding memory b = escrow.getBinding(bindingId);
        assertEq(b.amount, PRICE);
        assertEq(b.stakeAmount, STAKE);
        assertEq(uint8(b.state), uint8(KarmaAllowanceEscrow.BindingState.ACTIVE));
        assertEq(escrow.available(buyerBill), 1_000e6 - PRICE);
    }

    function testStrangerCannotBindBuyerBill() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.NotBillOperator.selector, buyerBill));
        escrow.bind(buyerBill, sellerBill, keccak256("order-1"), PRICE, STAKE);
    }

    function testOwnerCanRemoveOperator() public {
        uint256 billId = _commit(buyer, 100e6, executor);
        vm.startPrank(buyer);
        escrow.setOperator(billId, address(0));
        token.approve(address(escrow), 0);
        vm.stopPrank();
        assertFalse(escrow.canActFor(billId, executor));
        assertFalse(escrow.isBacked(billId));
    }

    function testOnlyOwnerCanSetOperator() public {
        uint256 billId = _commit(buyer, 100e6, executor);
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.NotBillOwner.selector, billId));
        escrow.setOperator(billId, stranger);
    }

    function testCannotOverBindCommitment() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        _bind(buyerBill, sellerBill, 900e6, STAKE);
        vm.prank(executor);
        vm.expectRevert(
            abi.encodeWithSelector(KarmaAllowanceEscrow.InsufficientCommitment.selector, 100e6, 200e6)
        );
        escrow.bind(buyerBill, sellerBill, keccak256("order-2"), 200e6, STAKE);
    }

    function testBindingRejectsSameOwnerAndTokenMismatch() public {
        uint256 buyerBill = _commit(buyer, 500e6, executor);
        uint256 secondBuyerBill = _commit(buyer, 500e6, executor);
        vm.prank(executor);
        vm.expectRevert(KarmaAllowanceEscrow.SameOwner.selector);
        escrow.bind(buyerBill, secondBuyerBill, bytes32(0), PRICE, STAKE);

        MockERC20 otherToken = new MockERC20();
        escrow.setTokenAllowed(address(otherToken), true);
        otherToken.mint(seller, 10e6);
        vm.startPrank(seller);
        otherToken.approve(address(escrow), 10e6);
        uint256 foreignBill = escrow.commit(address(otherToken), 10e6, executor);
        vm.stopPrank();

        vm.prank(executor);
        vm.expectRevert(KarmaAllowanceEscrow.TokenMismatch.selector);
        escrow.bind(buyerBill, foreignBill, bytes32(0), PRICE, 1e6);
    }

    // ────────────────────────────────────────────────────── happy path pull

    function testSettlementPullsWalletToWalletWithNoCustody() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);

        uint256 buyerBefore = token.balanceOf(buyer);
        uint256 sellerBefore = token.balanceOf(seller);

        vm.warp(vm.getBlockTimestamp() + SETTLE_DELAY + 1);
        vm.prank(executor);
        escrow.submitSettlement(bindingId, keccak256("proof"));

        // still inside the dispute window -> nothing may be pulled yet
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaAllowanceEscrow.SettleDelayActive.selector, vm.getBlockTimestamp() + DISPUTE_WINDOW
            )
        );
        escrow.finalizeSettlement(bindingId);

        vm.warp(vm.getBlockTimestamp() + DISPUTE_WINDOW + 1);
        vm.prank(stranger); // anyone may crank it: the window is the protection
        escrow.finalizeSettlement(bindingId);

        assertEq(token.balanceOf(buyer), buyerBefore - PRICE, "buyer paid exactly the price");
        assertEq(token.balanceOf(seller), sellerBefore + PRICE, "seller received the price");
        assertEq(token.balanceOf(address(escrow)), 0, "escrow still holds nothing");

        KarmaAllowanceEscrow.Binding memory b = escrow.getBinding(bindingId);
        assertEq(uint8(b.state), uint8(KarmaAllowanceEscrow.BindingState.SETTLED));
        assertEq(escrow.getBill(buyerBill).spent, PRICE);
        assertEq(escrow.getBill(buyerBill).reserved, 0);
        assertEq(escrow.getBill(sellerBill).reserved, 0, "seller stake freed, not spent");
        assertEq(escrow.getBill(sellerBill).spent, 0);
        assertEq(escrow.available(buyerBill), 1_000e6 - PRICE, "commitment is reusable");
        assertEq(token.allowance(buyer, address(escrow)), 1_000e6 - PRICE);
    }

    function testCommitmentServesManyOrders() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();

        for (uint256 i = 0; i < 3; i++) {
            uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);
            vm.warp(vm.getBlockTimestamp() + SETTLE_DELAY + 1);
            vm.prank(executor);
            escrow.submitSettlement(bindingId, keccak256(abi.encode("proof", i)));
            vm.warp(vm.getBlockTimestamp() + DISPUTE_WINDOW + 1);
            escrow.finalizeSettlement(bindingId);
        }

        assertEq(token.balanceOf(seller), 1_000e6 + 3 * PRICE);
        assertEq(escrow.getBill(buyerBill).spent, 3 * PRICE);
        assertEq(escrow.available(buyerBill), 1_000e6 - 3 * PRICE);
    }

    // ───────────────────────────────────────────────────── the kill switch

    function testRevokedAllowanceBlocksPullAndFundsAreNeverStuck() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);

        uint256 buyerBefore = token.balanceOf(buyer);
        uint256 sellerBefore = token.balanceOf(seller);

        vm.prank(buyer);
        token.approve(address(escrow), 0);
        assertFalse(escrow.isBacked(buyerBill));

        vm.warp(vm.getBlockTimestamp() + SETTLE_DELAY + 1);
        vm.prank(executor);
        escrow.submitSettlement(bindingId, keccak256("proof"));
        vm.warp(vm.getBlockTimestamp() + DISPUTE_WINDOW + 1);

        vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.InsufficientAllowance.selector, 0, PRICE));
        escrow.finalizeSettlement(bindingId);

        assertEq(token.balanceOf(buyer), buyerBefore, "buyer's money never left the wallet");
        assertEq(token.balanceOf(seller), sellerBefore);
        assertEq(token.balanceOf(address(escrow)), 0, "nothing was ever custodied to recover");

        // Re-approving makes the same binding payable again.
        vm.prank(buyer);
        token.approve(address(escrow), 1_000e6);
        escrow.finalizeSettlement(bindingId);
        assertEq(token.balanceOf(seller), sellerBefore + PRICE);
    }

    function testRevokeBlockedWhileReserved() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        _bind(buyerBill, sellerBill, PRICE, STAKE);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.ReservationActive.selector, PRICE));
        escrow.revoke(buyerBill);
        vm.prank(seller);
        vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.ReservationActive.selector, STAKE));
        escrow.revoke(sellerBill);
    }

    function testCancelReleasesReservations() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);

        // a stranger can never touch a live binding
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.NotSettlementParty.selector));
        escrow.cancelBinding(bindingId);

        // but either party's operator may release the reservations
        vm.prank(executor);
        escrow.cancelBinding(bindingId);
        assertEq(escrow.available(buyerBill), 1_000e6);
        assertEq(escrow.available(sellerBill), 1_000e6);
        assertEq(
            uint8(escrow.getBinding(bindingId).state),
            uint8(KarmaAllowanceEscrow.BindingState.CANCELLED)
        );

        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.WrongBindingState.selector, bindingId));
        escrow.cancelBinding(bindingId);
    }

    function testRevokeUnspentCommitment() public {
        uint256 billId = _commit(buyer, 100e6, executor);
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.NotBillOwner.selector, billId));
        escrow.revoke(billId);

        vm.prank(buyer);
        escrow.revoke(billId);
        assertEq(escrow.available(billId), 0);
        assertFalse(escrow.isBacked(billId), "revoked bill is not a live pledge");
        assertEq(token.balanceOf(buyer), 1_000e6, "revoke never moves money");
    }

    // ───────────────────────────────────────────────────────────── breach

    function testBreachSlashesSellerStake() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);

        vm.warp(vm.getBlockTimestamp() + SETTLE_DELAY + 1);
        vm.prank(executor);
        escrow.submitSettlement(bindingId, keccak256("disputed"));
        vm.warp(vm.getBlockTimestamp() + DISPUTE_WINDOW + 1);

        uint256 buyerBefore = token.balanceOf(buyer);
        uint256 sellerBefore = token.balanceOf(seller);

        vm.prank(stranger);
        vm.expectRevert(KarmaAllowanceEscrow.NotResolver.selector);
        escrow.finalizeBreach(bindingId);

        escrow.finalizeBreach(bindingId); // test contract is the resolver

        assertEq(token.balanceOf(buyer), buyerBefore + STAKE, "buyer is made whole from the stake");
        assertEq(token.balanceOf(seller), sellerBefore - STAKE);
        assertEq(token.balanceOf(address(escrow)), 0);
        assertEq(escrow.getBill(buyerBill).reserved, 0, "buyer's obligation cancelled");
        assertEq(escrow.getBill(buyerBill).spent, 0);
        assertEq(escrow.getBill(sellerBill).spent, STAKE);
    }

    function testSellerRevokingStakeIsRecordedAsUnpaidBreach() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);

        vm.prank(seller);
        token.approve(address(escrow), 0);

        vm.warp(vm.getBlockTimestamp() + SETTLE_DELAY + 1);
        vm.prank(executor);
        escrow.submitSettlement(bindingId, keccak256("disputed"));
        vm.warp(vm.getBlockTimestamp() + DISPUTE_WINDOW + 1);

        uint256 buyerBefore = token.balanceOf(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.InsufficientAllowance.selector, 0, STAKE));
        escrow.finalizeBreach(bindingId);
        assertEq(token.balanceOf(buyer), buyerBefore, "nothing moves when the stake is gone");
    }

    // ────────────────────────────────────────────────────── admin surface

    function testAdminConfigAndFrozenBrake() public {
        vm.startPrank(stranger);
        vm.expectRevert(bytes("not admin"));
        escrow.setFrozen(true);
        vm.expectRevert(bytes("not admin"));
        escrow.setDisputeWindow(1);
        vm.expectRevert(bytes("not admin"));
        escrow.setSettleDelay(1);
        vm.expectRevert(bytes("not admin"));
        escrow.setDisputeResolver(stranger);
        vm.expectRevert(bytes("not admin"));
        escrow.setTokenAllowed(address(token), false);
        vm.stopPrank();

        uint256 billId = _commit(buyer, 100e6, executor);
        escrow.setFrozen(true);
        vm.startPrank(buyer);
        token.approve(address(escrow), 100e6);
        vm.expectRevert(bytes("frozen"));
        escrow.commit(address(token), 100e6, executor);
        vm.stopPrank();

        // an existing commitment can still settle: the brake only stops new risk
        escrow.setFrozen(false);
        uint256 sellerBill = _commit(seller, 100e6, executor);
        uint256 bindingId = _bind(billId, sellerBill, 10e6, 3e6);
        escrow.setFrozen(true);
        vm.warp(vm.getBlockTimestamp() + SETTLE_DELAY + 1);
        vm.prank(executor);
        escrow.submitSettlement(bindingId, bytes32("p"));
        vm.warp(vm.getBlockTimestamp() + DISPUTE_WINDOW + 1);
        escrow.finalizeSettlement(bindingId);
        assertEq(token.balanceOf(seller), 1_000e6 + 10e6);
    }

    function testResolverCanBeRotated() public {
        escrow.setDisputeResolver(executor);
        assertEq(escrow.disputeResolver(), executor);
        vm.expectRevert(KarmaAllowanceEscrow.ZeroAddress.selector);
        escrow.setDisputeResolver(address(0));
    }

    function testSubmitRequiresParty() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);

        vm.warp(vm.getBlockTimestamp() + SETTLE_DELAY + 1);
        vm.prank(stranger);
        vm.expectRevert(KarmaAllowanceEscrow.NotSettlementParty.selector);
        escrow.submitSettlement(bindingId, bytes32("p"));

        // the buyer herself may always submit — no operator needed
        vm.prank(buyer);
        escrow.submitSettlement(bindingId, bytes32("p"));
    }

    function testSubmitNotAllowedBeforeCoolOff() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);
        vm.prank(executor);
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaAllowanceEscrow.SettleDelayActive.selector, vm.getBlockTimestamp() + SETTLE_DELAY
            )
        );
        escrow.submitSettlement(bindingId, bytes32("p"));
    }

    function testCustodyInvariantHoldsAcrossLifecycle() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);
        assertTrue(escrow.checkNoCustody(address(token)));
        vm.warp(vm.getBlockTimestamp() + SETTLE_DELAY + 1);
        vm.prank(executor);
        escrow.submitSettlement(bindingId, bytes32("p"));
        assertTrue(escrow.checkNoCustody(address(token)));
        vm.warp(vm.getBlockTimestamp() + DISPUTE_WINDOW + 1);
        escrow.finalizeSettlement(bindingId);
        assertTrue(escrow.checkNoCustody(address(token)));
    }
}