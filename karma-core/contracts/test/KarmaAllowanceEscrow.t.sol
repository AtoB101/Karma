// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaAllowanceEscrow} from "../core/KarmaAllowanceEscrow.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

/// @notice non-custodial settlement: the money stays in the payer's wallet,
///         the contract only records responsibility and executes the pull.
///         v3: the resolver is the only account that may open a settlement.
///         v4: the binding's state machine gates cancellation (no cancel once
///         submitted) and ``buyerConfirm`` shortens the window.
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
        // v3 起 ``submitSettlement`` 是 resolver-only：平台的验证账户就是 executor。
        escrow.setDisputeResolver(executor);

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

        vm.prank(executor); // the resolver rules the breach
        escrow.finalizeBreach(bindingId);

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
        vm.prank(executor);
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

    function testSubmitIsResolverOnly() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);

        vm.warp(vm.getBlockTimestamp() + SETTLE_DELAY + 1);

        // v3: neither party, nor their operator, may open the window — the
        // default is that no money is claimable until verification has passed.
        address[3] memory notResolver = [buyer, seller, stranger];
        for (uint256 i = 0; i < notResolver.length; i++) {
            vm.prank(notResolver[i]);
            vm.expectRevert(KarmaAllowanceEscrow.NotResolver.selector);
            escrow.submitSettlement(bindingId, bytes32("p"));
        }

        vm.prank(executor); // the resolver may
        escrow.submitSettlement(bindingId, bytes32("p"));
        assertEq(
            uint8(escrow.getBinding(bindingId).state),
            uint8(KarmaAllowanceEscrow.BindingState.FINALIZING)
        );
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

    // ─────────────────────────────────────── v4: 买方确认与状态机取消闸

    /// 双方都确认了就没有窗口可等：验证通过（resolver submit）+ 买方自己点头，
    /// 划款立刻可执行，不必再等 DISPUTE_WINDOW。
    function testBuyerConfirmReleasesWithoutWaitingForTheWindow() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);

        vm.warp(vm.getBlockTimestamp() + SETTLE_DELAY + 1);
        vm.prank(executor);
        escrow.submitSettlement(bindingId, keccak256("proof"));

        uint256 sellerBefore = token.balanceOf(seller);
        // 窗口还没过：没有买方的确认标记，任何人来推都要被拒
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaAllowanceEscrow.SettleDelayActive.selector, vm.getBlockTimestamp() + DISPUTE_WINDOW
            )
        );
        escrow.finalizeSettlement(bindingId);

        vm.prank(buyer);
        escrow.buyerConfirm(bindingId);

        vm.prank(stranger); // 确认之后仍然谁都能推，窗口不再是阻碍
        escrow.finalizeSettlement(bindingId);

        assertEq(token.balanceOf(seller), sellerBefore + PRICE, "seller paid immediately");
        assertEq(token.balanceOf(address(escrow)), 0);
    }

    function testBuyerConfirmOnlyInFinalizingAndOnlyByTheBuyer() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);

        // ACTIVE：还没提交过，没有任何东西可以确认
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.WrongBindingState.selector, bindingId));
        escrow.buyerConfirm(bindingId);

        vm.warp(vm.getBlockTimestamp() + SETTLE_DELAY + 1);
        vm.prank(executor);
        escrow.submitSettlement(bindingId, bytes32("p"));

        // 陌生人不行；卖方也不行 —— 确认只能是买方的意思表示
        vm.prank(stranger);
        vm.expectRevert(KarmaAllowanceEscrow.NotSettlementParty.selector);
        escrow.buyerConfirm(bindingId);
        vm.prank(seller);
        vm.expectRevert(KarmaAllowanceEscrow.NotSettlementParty.selector);
        escrow.buyerConfirm(bindingId);

        // 买方自己在账单上装的 operator（agent / Karma 执行器）可以
        vm.prank(executor);
        escrow.buyerConfirm(bindingId);
        assertTrue(escrow.getBinding(bindingId).buyerConfirmed);

        // 只能确认一次
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.AlreadyConfirmed.selector, bindingId));
        escrow.buyerConfirm(bindingId);
    }

    /// 取消的判据是**状态**，不是时间：一旦 submit，买方/卖方/双方 operator/resolver
    /// 全都拿不回预留，窗口过点之后也一样。
    function testCancelIsRefusedOnceSubmitted() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);

        vm.warp(vm.getBlockTimestamp() + SETTLE_DELAY + 1);
        vm.prank(executor);
        escrow.submitSettlement(bindingId, bytes32("p"));

        address[3] memory parties = [buyer, seller, executor];
        for (uint256 i = 0; i < parties.length; i++) {
            vm.prank(parties[i]);
            vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.WrongBindingState.selector, bindingId));
            escrow.cancelBinding(bindingId);
        }

        vm.warp(vm.getBlockTimestamp() + DISPUTE_WINDOW + 1);
        vm.prank(buyer);
        vm.expectRevert(abi.encodeWithSelector(KarmaAllowanceEscrow.WrongBindingState.selector, bindingId));
        escrow.cancelBinding(bindingId);

        assertEq(escrow.available(buyerBill), 1_000e6 - PRICE, "reservation still held");
        assertEq(escrow.available(sellerBill), 1_000e6 - STAKE, "stake still held");
    }

    /// ACTIVE 上的取消仍然畅通：这是「绑错了 / 没人推进的孤儿绑定」的唯一出路。
    function testCancelStillWorksWhileActive() public {
        (uint256 buyerBill, uint256 sellerBill) = _openPair();
        uint256 bindingId = _bind(buyerBill, sellerBill, PRICE, STAKE);

        vm.prank(executor);
        escrow.cancelBinding(bindingId);

        assertEq(escrow.available(buyerBill), 1_000e6);
        assertEq(escrow.available(sellerBill), 1_000e6);
        assertEq(
            uint8(escrow.getBinding(bindingId).state),
            uint8(KarmaAllowanceEscrow.BindingState.CANCELLED)
        );
        assertEq(token.balanceOf(buyer), 1_000e6, "cancel never moves money");
    }
}
