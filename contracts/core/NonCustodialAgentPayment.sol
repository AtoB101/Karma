// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {INonCustodialAgentPayment} from "../interfaces/INonCustodialAgentPayment.sol";

interface IERC20Extended {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
    function allowance(address owner, address spender) external view returns (uint256);
}

contract NonCustodialAgentPayment is INonCustodialAgentPayment {
    error InvalidAddress();
    error InvalidAmount();
    error InvalidDeadline();
    error Unauthorized();
    error InvalidState();
    error CapacityInsufficient();
    error TransferFailed();
    error InvalidShare();
    error InvariantBroken();
    error Reentrancy();

    uint16 public constant BPS_DENOMINATOR = 10_000;
    uint16 public immutable sellerBondBps;
    uint256 public immutable defaultBillTtlSeconds;
    address public immutable arbitrator;

    uint256 public nextBillId = 1;

    mapping(address user => mapping(address token => AccountState)) internal accountStates;
    mapping(uint256 billId => Bill) internal bills;
    bool private entered;

    event LockModeEnabled(address indexed user, address indexed token, uint256 amount, uint256 lockedTotal);
    event LockModeReduced(address indexed user, address indexed token, uint256 amount, uint256 lockedTotal);
    event BillCreated(
        uint256 indexed billId,
        address indexed buyer,
        address indexed seller,
        address token,
        uint256 amount,
        uint256 sellerBond,
        uint256 deadline
    );
    event BillConfirmed(uint256 indexed billId, address indexed buyer);
    event BillCancelled(uint256 indexed billId, address indexed by);
    event BillDisputed(uint256 indexed billId, address indexed by);
    event BillSettled(uint256 indexed billId, uint256 amount);
    event BillExpired(uint256 indexed billId);
    event BillResolvedBuyer(uint256 indexed billId, uint256 sellerPenalty);
    event BillResolvedSeller(uint256 indexed billId, uint256 paidAmount);
    event BillSplitResolved(uint256 indexed billId, uint16 buyerShareBps, uint256 buyerRefund, uint256 sellerPaid);
    event InvalidTransferIntent(address indexed caller, uint256 indexed billId, string reason);

    constructor(address arbitrator_, uint16 sellerBondBps_, uint256 defaultBillTtlSeconds_) {
        if (arbitrator_ == address(0)) revert InvalidAddress();
        if (sellerBondBps_ > BPS_DENOMINATOR) revert InvalidShare();
        if (defaultBillTtlSeconds_ == 0) revert InvalidAmount();
        arbitrator = arbitrator_;
        sellerBondBps = sellerBondBps_;
        defaultBillTtlSeconds = defaultBillTtlSeconds_;
    }

    function lockFunds(address token, uint256 amount) external override {
        if (token == address(0)) revert InvalidAddress();
        if (amount == 0) revert InvalidAmount();

        AccountState storage st = accountStates[msg.sender][token];
        st.locked += amount;
        st.active += amount;

        if (_spendable(msg.sender, token) < st.locked) revert CapacityInsufficient();
        _assertAccountInvariant(msg.sender, token);
        emit LockModeEnabled(msg.sender, token, amount, st.locked);
    }

    function unlockFunds(address token, uint256 amount) external override {
        if (token == address(0)) revert InvalidAddress();
        if (amount == 0) revert InvalidAmount();

        AccountState storage st = accountStates[msg.sender][token];
        if (st.active < amount || st.locked < amount) revert CapacityInsufficient();
        st.active -= amount;
        st.locked -= amount;
        _assertAccountInvariant(msg.sender, token);
        emit LockModeReduced(msg.sender, token, amount, st.locked);
    }

    function createBill(address seller, address token, uint256 amount, bytes32 scopeHash, uint256 deadline)
        external
        override
        returns (uint256 billId)
    {
        if (seller == address(0) || token == address(0)) revert InvalidAddress();
        if (seller == msg.sender) revert Unauthorized();
        if (amount == 0) revert InvalidAmount();

        uint256 finalDeadline = deadline == 0 ? block.timestamp + defaultBillTtlSeconds : deadline;
        if (finalDeadline <= block.timestamp) revert InvalidDeadline();

        AccountState storage buyerSt = accountStates[msg.sender][token];
        uint256 sellerBond = _sellerBond(amount);
        AccountState storage sellerSt = accountStates[seller][token];

        if (buyerSt.active < amount || sellerSt.active < sellerBond) revert CapacityInsufficient();

        buyerSt.active -= amount;
        buyerSt.reserved += amount;
        sellerSt.active -= sellerBond;
        sellerSt.reserved += sellerBond;
        _assertAccountInvariant(msg.sender, token);
        _assertAccountInvariant(seller, token);

        billId = nextBillId++;
        bills[billId] = Bill({
            billId: billId,
            buyer: msg.sender,
            seller: seller,
            token: token,
            amount: amount,
            sellerBond: sellerBond,
            scopeHash: scopeHash,
            status: BillStatus.Pending,
            createdAt: block.timestamp,
            deadline: finalDeadline
        });

        emit BillCreated(billId, msg.sender, seller, token, amount, sellerBond, finalDeadline);
    }

    function confirmBill(uint256 billId) external override {
        Bill storage b = bills[billId];
        if (b.billId == 0) revert InvalidState();
        if (msg.sender != b.buyer) revert Unauthorized();
        if (b.status != BillStatus.Pending) revert InvalidState();
        b.status = BillStatus.Confirmed;
        emit BillConfirmed(billId, msg.sender);
    }

    function cancelBill(uint256 billId) external override {
        Bill storage b = bills[billId];
        if (b.billId == 0) revert InvalidState();
        if (msg.sender != b.buyer) revert Unauthorized();
        if (b.status != BillStatus.Pending) revert InvalidState();
        _releaseOnCancelOrExpire(b);
        b.status = BillStatus.Cancelled;
        emit BillCancelled(billId, msg.sender);
    }

    function disputeBill(uint256 billId) external override {
        Bill storage b = bills[billId];
        if (b.billId == 0) revert InvalidState();
        if (msg.sender != b.buyer && msg.sender != b.seller) revert Unauthorized();
        if (b.status != BillStatus.Confirmed) revert InvalidState();
        b.status = BillStatus.Disputed;
        emit BillDisputed(billId, msg.sender);
    }

    function requestBillPayout(uint256 billId) external override returns (bool ok) {
        if (entered) revert Reentrancy();
        entered = true;
        Bill storage b = bills[billId];
        if (b.billId == 0) {
            emit InvalidTransferIntent(msg.sender, billId, "bill-not-found");
            entered = false;
            return false;
        }
        if (b.status != BillStatus.Confirmed) {
            emit InvalidTransferIntent(msg.sender, billId, "bill-not-confirmed");
            entered = false;
            return false;
        }
        if (block.timestamp > b.deadline) {
            emit InvalidTransferIntent(msg.sender, billId, "bill-expired");
            entered = false;
            return false;
        }
        if (!_hasSpendableBalance(b.buyer, b.token, b.amount)) {
            emit InvalidTransferIntent(msg.sender, billId, "buyer-capacity-insufficient");
            entered = false;
            return false;
        }

        _settleConfirmedBill(b);
        entered = false;
        return true;
    }

    function expireBill(uint256 billId) external override {
        Bill storage b = bills[billId];
        if (b.billId == 0) revert InvalidState();
        if (b.status != BillStatus.Pending && b.status != BillStatus.Confirmed) revert InvalidState();
        if (block.timestamp <= b.deadline) revert InvalidState();
        _releaseOnCancelOrExpire(b);
        b.status = BillStatus.Expired;
        _assertAccountInvariant(b.buyer, b.token);
        _assertAccountInvariant(b.seller, b.token);
        emit BillExpired(billId);
    }

    function resolveDisputeBuyer(uint256 billId) external override onlyArbitrator {
        Bill storage b = bills[billId];
        if (b.status != BillStatus.Disputed) revert InvalidState();

        AccountState storage buyerSt = accountStates[b.buyer][b.token];
        AccountState storage sellerSt = accountStates[b.seller][b.token];

        buyerSt.reserved -= b.amount;
        buyerSt.active += b.amount;

        uint256 penalty = b.sellerBond;
        sellerSt.reserved -= b.sellerBond;
        sellerSt.locked -= b.sellerBond;
        if (!_safeTransferFrom(b.token, b.seller, b.buyer, penalty)) revert TransferFailed();

        b.status = BillStatus.ResolvedBuyer;
        _assertAccountInvariant(b.buyer, b.token);
        _assertAccountInvariant(b.seller, b.token);
        emit BillResolvedBuyer(billId, penalty);
    }

    function resolveDisputeSeller(uint256 billId) external override onlyArbitrator {
        Bill storage b = bills[billId];
        if (b.status != BillStatus.Disputed) revert InvalidState();
        _settleDisputedBillSellerWins(b);
        b.status = BillStatus.ResolvedSeller;
        _assertAccountInvariant(b.buyer, b.token);
        _assertAccountInvariant(b.seller, b.token);
        emit BillResolvedSeller(billId, b.amount);
    }

    function resolveDisputeSplit(uint256 billId, uint16 buyerShareBps) external override onlyArbitrator {
        Bill storage b = bills[billId];
        if (b.status != BillStatus.Disputed) revert InvalidState();
        if (buyerShareBps > BPS_DENOMINATOR) revert InvalidShare();

        uint256 buyerRefund = (b.amount * buyerShareBps) / BPS_DENOMINATOR;
        uint256 sellerPaid = b.amount - buyerRefund;
        uint256 sellerPenalty = (b.sellerBond * buyerShareBps) / BPS_DENOMINATOR;

        AccountState storage buyerSt = accountStates[b.buyer][b.token];
        AccountState storage sellerSt = accountStates[b.seller][b.token];

        buyerSt.reserved -= b.amount;
        if (buyerRefund > 0) buyerSt.active += buyerRefund;
        if (sellerPaid > 0) {
            if (!_safeTransferFrom(b.token, b.buyer, b.seller, sellerPaid)) revert TransferFailed();
            buyerSt.locked -= sellerPaid;
        }

        sellerSt.reserved -= b.sellerBond;
        if (sellerPenalty > 0) {
            if (!_safeTransferFrom(b.token, b.seller, b.buyer, sellerPenalty)) revert TransferFailed();
            sellerSt.locked -= sellerPenalty;
        }
        uint256 sellerBondRemainder = b.sellerBond - sellerPenalty;
        if (sellerBondRemainder > 0) {
            sellerSt.active += sellerBondRemainder;
        }

        b.status = BillStatus.SplitResolved;
        _assertAccountInvariant(b.buyer, b.token);
        _assertAccountInvariant(b.seller, b.token);
        emit BillSplitResolved(billId, buyerShareBps, buyerRefund, sellerPaid);
    }

    function getAccountState(address user, address token) external view override returns (AccountState memory) {
        return accountStates[user][token];
    }

    function getBill(uint256 billId) external view override returns (Bill memory) {
        return bills[billId];
    }

    function isAccountConsistent(address user, address token) external view override returns (bool) {
        AccountState memory st = accountStates[user][token];
        return st.active + st.reserved == st.locked;
    }

    function _releaseOnCancelOrExpire(Bill storage b) internal {
        AccountState storage buyerSt = accountStates[b.buyer][b.token];
        AccountState storage sellerSt = accountStates[b.seller][b.token];

        buyerSt.reserved -= b.amount;
        buyerSt.active += b.amount;
        sellerSt.reserved -= b.sellerBond;
        sellerSt.active += b.sellerBond;
        _assertAccountInvariant(b.buyer, b.token);
        _assertAccountInvariant(b.seller, b.token);
    }

    function _settleConfirmedBill(Bill storage b) internal {
        AccountState storage buyerSt = accountStates[b.buyer][b.token];
        AccountState storage sellerSt = accountStates[b.seller][b.token];

        buyerSt.reserved -= b.amount;
        buyerSt.locked -= b.amount;

        if (!_safeTransferFrom(b.token, b.buyer, b.seller, b.amount)) revert TransferFailed();

        sellerSt.reserved -= b.sellerBond;
        sellerSt.active += b.sellerBond;

        b.status = BillStatus.Settled;
        _assertAccountInvariant(b.buyer, b.token);
        _assertAccountInvariant(b.seller, b.token);
        emit BillSettled(b.billId, b.amount);
    }

    function _settleDisputedBillSellerWins(Bill storage b) internal {
        AccountState storage buyerSt = accountStates[b.buyer][b.token];
        AccountState storage sellerSt = accountStates[b.seller][b.token];

        buyerSt.reserved -= b.amount;
        buyerSt.locked -= b.amount;
        if (!_safeTransferFrom(b.token, b.buyer, b.seller, b.amount)) revert TransferFailed();

        sellerSt.reserved -= b.sellerBond;
        sellerSt.active += b.sellerBond;
        _assertAccountInvariant(b.buyer, b.token);
        _assertAccountInvariant(b.seller, b.token);
    }

    function _sellerBond(uint256 amount) internal view returns (uint256) {
        return (amount * sellerBondBps) / BPS_DENOMINATOR;
    }

    function _spendable(address owner, address token) internal view returns (uint256) {
        uint256 bal = IERC20Extended(token).balanceOf(owner);
        uint256 allw = IERC20Extended(token).allowance(owner, address(this));
        return bal < allw ? bal : allw;
    }

    function _hasSpendableBalance(address owner, address token, uint256 amount) internal view returns (bool) {
        return _spendable(owner, token) >= amount;
    }

    function _safeTransferFrom(address token, address from, address to, uint256 amount) internal returns (bool) {
        if (amount == 0) return true;
        return IERC20Extended(token).transferFrom(from, to, amount);
    }

    function _assertAccountInvariant(address user, address token) internal view {
        AccountState memory st = accountStates[user][token];
        if (st.active + st.reserved != st.locked) revert InvariantBroken();
    }

    modifier onlyArbitrator() {
        if (msg.sender != arbitrator) revert Unauthorized();
        _;
    }
}
