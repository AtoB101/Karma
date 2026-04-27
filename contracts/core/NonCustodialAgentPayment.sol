// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {INonCustodialAgentPayment} from "../interfaces/INonCustodialAgentPayment.sol";

interface IERC20Extended {
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
    error BatchAlreadyClosed();
    error BatchPaused();
    error BatchNotFound();
    error BatchNotClosed();
    error BatchOwnerMismatch();

    uint16 public constant BPS_DENOMINATOR = 10_000;
    uint16 public immutable sellerBondBps;
    uint256 public immutable defaultBillTtlSeconds;
    address public immutable arbitrator;
    address public immutable owner;

    uint256 public nextBillId = 1;
    uint256 public nextBatchId = 1;

    bool public batchModeEnabled = true;
    bool public batchCircuitBreakerPaused;

    mapping(address user => mapping(address token => AccountState)) internal accountStates;
    mapping(uint256 billId => Bill) internal bills;
    mapping(uint256 batchId => Batch) internal batches;
    mapping(uint256 batchId => uint256[]) internal batchBillIds;
    mapping(uint256 billId => bool) internal billBatchFinalized;
    mapping(uint256 batchId => address) internal batchOwner;
    mapping(bytes32 ownerTokenKey => uint256 batchId) internal activeBatchByOwnerToken;
    uint256 private constant _NOT_ENTERED = 1;
    uint256 private constant _ENTERED = 2;
    uint256 private _status = _NOT_ENTERED;

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
    event BillResolvedBuyer(uint256 indexed billId, uint256 sellerPenalty, uint256 buyerRefunded);
    event BillResolvedSeller(uint256 indexed billId, uint256 paidAmount, uint256 sellerBondReturned);
    event BillSplitResolved(uint256 indexed billId, uint16 buyerShareBps, uint256 buyerRefund, uint256 sellerPaid);
    event InvalidTransferIntent(address indexed caller, uint256 indexed billId, string reason);
    event BatchCreated(uint256 indexed batchId, address indexed owner, address indexed token);
    event BatchClosed(uint256 indexed batchId, address indexed by);
    event BatchSettled(uint256 indexed batchId, uint256 settledCount, uint256 settledAmount);
    event BatchModeUpdated(bool enabled);
    event BatchCircuitBreakerUpdated(bool paused);

    /// @notice Creates the non-custodial payment protocol core.
    /// @param arbitrator_ Address allowed to resolve disputed bills.
    /// @param sellerBondBps_ Seller bond ratio in basis points (1e4 = 100%).
    /// @param defaultBillTtlSeconds_ Default bill TTL when createBill deadline is zero.
    constructor(address arbitrator_, uint16 sellerBondBps_, uint256 defaultBillTtlSeconds_) {
        if (arbitrator_ == address(0)) revert InvalidAddress();
        if (sellerBondBps_ > BPS_DENOMINATOR) revert InvalidShare();
        if (defaultBillTtlSeconds_ == 0) revert InvalidAmount();
        arbitrator = arbitrator_;
        sellerBondBps = sellerBondBps_;
        defaultBillTtlSeconds = defaultBillTtlSeconds_;
        owner = msg.sender;
    }

    /// @notice Increases logical lock capacity for caller on a token.
    /// @dev This does not custody funds; caller must keep enough balance+allowance in wallet.
    /// @param token ERC20 token used for accounting.
    /// @param amount Additional amount to lock.
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

    /// @notice Decreases caller lock capacity and releases active amount.
    /// @dev Reserved funds cannot be unlocked until related bill transitions finalize.
    /// @param token ERC20 token used for accounting.
    /// @param amount Amount to unlock from active capacity.
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

    /// @notice Creates a bill and reserves buyer amount plus seller bond.
    /// @dev When batch mode is enabled, bill is auto-attached to caller's open batch for the same token.
    /// @param seller Counterparty seller account.
    /// @param token Settlement token.
    /// @param amount Principal bill amount.
    /// @param scopeHash Off-chain scope commitment hash.
    /// @param proofHash Off-chain evidence pointer (e.g. IPFS URI hash string).
    /// @param deadline Explicit deadline; if zero, default TTL is applied.
    /// @return billId Newly created bill id.
    function createBill(address seller, address token, uint256 amount, bytes32 scopeHash, string calldata proofHash, uint256 deadline)
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

        uint256 batchId = 0;
        if (batchModeEnabled) {
            if (batchCircuitBreakerPaused) revert BatchPaused();
            batchId = _ensureOpenBatch(msg.sender, token);
        }

        billId = nextBillId++;
        bills[billId] = Bill({
            billId: billId,
            batchId: batchId,
            buyer: msg.sender,
            seller: seller,
            token: token,
            amount: amount,
            sellerBond: sellerBond,
            scopeHash: scopeHash,
            proofHash: proofHash,
            status: BillStatus.Pending,
            createdAt: block.timestamp,
            deadline: finalDeadline
        });

        if (batchId != 0) {
            Batch storage batch = batches[batchId];
            batch.totalPending += amount;
            batch.billCount += 1;
            batchBillIds[batchId].push(billId);
        }

        emit BillCreated(billId, msg.sender, seller, token, amount, sellerBond, finalDeadline);
    }

    /// @notice Confirms a pending bill, making it eligible for payout/dispute.
    /// @param billId Bill identifier.
    function confirmBill(uint256 billId) external override {
        Bill storage b = bills[billId];
        if (b.billId == 0) revert InvalidState();
        if (msg.sender != b.buyer) revert Unauthorized();
        if (b.status != BillStatus.Pending) revert InvalidState();
        b.status = BillStatus.Confirmed;
        emit BillConfirmed(billId, msg.sender);
    }

    /// @notice Cancels a pending bill and releases both parties' reserved amounts.
    /// @param billId Bill identifier.
    function cancelBill(uint256 billId) external override {
        Bill storage b = bills[billId];
        if (b.billId == 0) revert InvalidState();
        if (msg.sender != b.buyer) revert Unauthorized();
        if (b.status != BillStatus.Pending) revert InvalidState();
        _releaseOnCancelOrExpire(b);
        b.status = BillStatus.Cancelled;
        _finalizeBillFromBatch(b);
        emit BillCancelled(billId, msg.sender);
    }

    /// @notice Escalates a confirmed bill to disputed status.
    /// @dev Callable by buyer or seller.
    /// @param billId Bill identifier.
    function disputeBill(uint256 billId) external override {
        Bill storage b = bills[billId];
        if (b.billId == 0) revert InvalidState();
        if (msg.sender != b.buyer && msg.sender != b.seller) revert Unauthorized();
        if (b.status != BillStatus.Confirmed) revert InvalidState();
        b.status = BillStatus.Disputed;
        emit BillDisputed(billId, msg.sender);
    }

    /// @notice Attempts to settle a confirmed bill by direct token transfer.
    /// @dev Returns false and emits InvalidTransferIntent for non-terminal failures instead of reverting.
    /// @param billId Bill identifier.
    /// @return ok True when settlement succeeds.
    function requestBillPayout(uint256 billId) external override nonReentrant returns (bool ok) {
        Bill storage b = bills[billId];
        if (b.billId == 0) {
            emit InvalidTransferIntent(msg.sender, billId, "bill-not-found");
            return false;
        }
        if (b.status != BillStatus.Confirmed) {
            emit InvalidTransferIntent(msg.sender, billId, "bill-not-confirmed");
            return false;
        }
        if (block.timestamp > b.deadline) {
            emit InvalidTransferIntent(msg.sender, billId, "bill-expired");
            return false;
        }
        if (!_hasSpendableBalance(b.buyer, b.token, b.amount)) {
            emit InvalidTransferIntent(msg.sender, billId, "buyer-capacity-insufficient");
            return false;
        }

        _settleConfirmedBill(b);
        return true;
    }

    /// @notice Expires a pending/confirmed bill after deadline and releases reservations.
    /// @param billId Bill identifier.
    function expireBill(uint256 billId) external override {
        Bill storage b = bills[billId];
        if (b.billId == 0) revert InvalidState();
        if (b.status != BillStatus.Pending && b.status != BillStatus.Confirmed) revert InvalidState();
        if (block.timestamp <= b.deadline) revert InvalidState();
        _releaseOnCancelOrExpire(b);
        b.status = BillStatus.Expired;
        _finalizeBillFromBatch(b);
        _assertAccountInvariant(b.buyer, b.token);
        _assertAccountInvariant(b.seller, b.token);
        emit BillExpired(billId);
    }

    /// @notice Arbitrator resolves a dispute in buyer's favor.
    /// @dev Buyer gets principal back to active; seller bond is paid to buyer as penalty.
    /// @param billId Bill identifier.
    function resolveDisputeBuyer(uint256 billId) external override nonReentrant onlyArbitrator {
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
        _finalizeBillFromBatch(b);
        _assertAccountInvariant(b.buyer, b.token);
        _assertAccountInvariant(b.seller, b.token);
        emit BillResolvedBuyer(billId, penalty, b.amount);
    }

    /// @notice Arbitrator resolves a dispute in seller's favor.
    /// @dev Principal is paid to seller and seller bond is returned to seller active balance.
    /// @param billId Bill identifier.
    function resolveDisputeSeller(uint256 billId) external override nonReentrant onlyArbitrator {
        Bill storage b = bills[billId];
        if (b.status != BillStatus.Disputed) revert InvalidState();
        _settleDisputedBillSellerWins(b);
        b.status = BillStatus.ResolvedSeller;
        _finalizeBillFromBatch(b);
        _assertAccountInvariant(b.buyer, b.token);
        _assertAccountInvariant(b.seller, b.token);
        emit BillResolvedSeller(billId, b.amount, b.sellerBond);
    }

    /// @notice Arbitrator resolves a dispute by splitting outcome using basis points.
    /// @param billId Bill identifier.
    /// @param buyerShareBps Buyer share of principal/bond penalty in basis points.
    function resolveDisputeSplit(uint256 billId, uint16 buyerShareBps) external override nonReentrant onlyArbitrator {
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
        _finalizeBillFromBatch(b);
        _assertAccountInvariant(b.buyer, b.token);
        _assertAccountInvariant(b.seller, b.token);
        emit BillSplitResolved(billId, buyerShareBps, buyerRefund, sellerPaid);
    }

    /// @notice Closes an open batch so it can be settled.
    /// @param batchId Batch identifier.
    function closeBatch(uint256 batchId) external override {
        Batch storage batch = batches[batchId];
        if (batch.batchId == 0) revert BatchNotFound();
        if (batch.status != BatchStatus.Open) revert BatchAlreadyClosed();
        if (batchOwner[batchId] != msg.sender) revert BatchOwnerMismatch();
        batch.status = BatchStatus.Closed;
        bytes32 key = _batchKey(msg.sender, bills[batchBillIds[batchId][0]].token);
        if (activeBatchByOwnerToken[key] == batchId) {
            activeBatchByOwnerToken[key] = 0;
        }
        emit BatchClosed(batchId, msg.sender);
    }

    /// @notice Settles confirmed bills in a closed batch up to the requested limit.
    /// @dev Batch is marked settled once all included bills are finalized to terminal states.
    /// @param batchId Batch identifier.
    /// @param maxBills Max number of bills to process; zero means full batch.
    /// @return settledCount Number of successfully settled confirmed bills in this call.
    /// @return settledAmount Sum of settled principal amount in this call.
    function settleBatch(uint256 batchId, uint256 maxBills)
        external
        override
        returns (uint256 settledCount, uint256 settledAmount)
    {
        Batch storage batch = batches[batchId];
        if (batch.batchId == 0) revert BatchNotFound();
        if (batch.status != BatchStatus.Closed) revert BatchNotClosed();
        if (batchOwner[batchId] != msg.sender) revert BatchOwnerMismatch();

        uint256[] storage ids = batchBillIds[batchId];
        uint256 processLimit = maxBills == 0 || maxBills > ids.length ? ids.length : maxBills;

        for (uint256 i = 0; i < processLimit; i++) {
            Bill storage b = bills[ids[i]];
            if (b.status == BillStatus.Confirmed) {
                if (_hasSpendableBalance(b.buyer, b.token, b.amount)) {
                    _settleConfirmedBill(b);
                    settledCount += 1;
                    settledAmount += b.amount;
                } else {
                    emit InvalidTransferIntent(msg.sender, b.billId, "buyer-capacity-insufficient");
                }
            }
        }

        if (_isBatchFullyFinalized(batchId)) {
            batch.status = BatchStatus.Settled;
            batch.settledAt = block.timestamp;
        }
        emit BatchSettled(batchId, settledCount, settledAmount);
    }

    /// @notice Enables or disables automatic batch assignment on bill creation.
    /// @param enabled New batch mode flag.
    function setBatchModeEnabled(bool enabled) external override onlyOwner {
        batchModeEnabled = enabled;
        emit BatchModeUpdated(enabled);
    }

    /// @notice Pauses or resumes batch path via circuit-breaker style fuse.
    /// @param paused New breaker flag.
    function setBatchCircuitBreakerPaused(bool paused) external override onlyOwner {
        batchCircuitBreakerPaused = paused;
        emit BatchCircuitBreakerUpdated(paused);
    }

    /// @notice Returns batch snapshot by id.
    /// @param batchId Batch identifier.
    function getBatch(uint256 batchId) external view override returns (Batch memory) {
        return batches[batchId];
    }

    /// @notice Returns bill ids linked to a batch.
    /// @param batchId Batch identifier.
    function getBatchBillIds(uint256 batchId) external view override returns (uint256[] memory) {
        return batchBillIds[batchId];
    }

    /// @notice Returns account lock/active/reserved state for user-token pair.
    /// @param user Account address.
    /// @param token Token address.
    function getAccountState(address user, address token) external view override returns (AccountState memory) {
        return accountStates[user][token];
    }

    /// @notice Returns bill snapshot by id.
    /// @param billId Bill identifier.
    function getBill(uint256 billId) external view override returns (Bill memory) {
        return bills[billId];
    }

    /// @notice Checks account invariant active + reserved == locked.
    /// @param user Account address.
    /// @param token Token address.
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
        _finalizeBillFromBatch(b);
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
        _finalizeBillFromBatch(b);
        _assertAccountInvariant(b.buyer, b.token);
        _assertAccountInvariant(b.seller, b.token);
    }

    function _sellerBond(uint256 amount) internal view returns (uint256) {
        return (amount * sellerBondBps) / BPS_DENOMINATOR;
    }

    function _spendable(address account, address token) internal view returns (uint256) {
        uint256 bal = IERC20Extended(token).balanceOf(account);
        uint256 allw = IERC20Extended(token).allowance(account, address(this));
        return bal < allw ? bal : allw;
    }

    function _hasSpendableBalance(address account, address token, uint256 amount) internal view returns (bool) {
        uint256 bal = IERC20Extended(token).balanceOf(account);
        uint256 allw = IERC20Extended(token).allowance(account, address(this));
        return bal >= amount && allw >= amount;
    }

    function _safeTransferFrom(address token, address from, address to, uint256 amount) internal returns (bool) {
        if (amount == 0) return true;
        (bool success, bytes memory data) =
            token.call(abi.encodeWithSelector(bytes4(keccak256("transferFrom(address,address,uint256)")), from, to, amount));
        if (!success) {
            if (data.length > 0) {
                assembly {
                    revert(add(data, 0x20), mload(data))
                }
            }
            return false;
        }
        if (data.length == 0) return true;
        return abi.decode(data, (bool));
    }

    function _assertAccountInvariant(address user, address token) internal view {
        AccountState memory st = accountStates[user][token];
        if (st.active + st.reserved != st.locked) revert InvariantBroken();
    }

    function _batchKey(address batchOwnerAddr, address token) internal pure returns (bytes32) {
        return keccak256(abi.encodePacked(batchOwnerAddr, token));
    }

    function _ensureOpenBatch(address batchOwnerAddr, address token) internal returns (uint256 batchId) {
        bytes32 key = _batchKey(batchOwnerAddr, token);
        batchId = activeBatchByOwnerToken[key];
        if (batchId == 0 || batches[batchId].status != BatchStatus.Open) {
            batchId = nextBatchId++;
            batches[batchId] = Batch({
                batchId: batchId,
                totalPending: 0,
                billCount: 0,
                status: BatchStatus.Open,
                createdAt: block.timestamp,
                settledAt: 0
            });
            batchOwner[batchId] = batchOwnerAddr;
            activeBatchByOwnerToken[key] = batchId;
            emit BatchCreated(batchId, batchOwnerAddr, token);
        }
    }

    function _finalizeBillFromBatch(Bill storage b) internal {
        uint256 batchId = b.batchId;
        if (batchId == 0 || billBatchFinalized[b.billId]) return;
        Batch storage batch = batches[batchId];
        if (batch.totalPending >= b.amount) {
            batch.totalPending -= b.amount;
        } else {
            batch.totalPending = 0;
        }
        billBatchFinalized[b.billId] = true;
        if (batch.status == BatchStatus.Closed && _isBatchFullyFinalized(batchId)) {
            batch.status = BatchStatus.Settled;
            batch.settledAt = block.timestamp;
        }
    }

    function _isBatchFullyFinalized(uint256 batchId) internal view returns (bool) {
        uint256[] storage ids = batchBillIds[batchId];
        for (uint256 i = 0; i < ids.length; i++) {
            BillStatus status = bills[ids[i]].status;
            if (
                status != BillStatus.Settled && status != BillStatus.Cancelled && status != BillStatus.Expired
                    && status != BillStatus.ResolvedBuyer && status != BillStatus.ResolvedSeller
                    && status != BillStatus.SplitResolved
            ) {
                return false;
            }
        }
        return true;
    }

    modifier onlyArbitrator() {
        if (msg.sender != arbitrator) revert Unauthorized();
        _;
    }

    modifier onlyOwner() {
        if (msg.sender != owner) revert Unauthorized();
        _;
    }

    modifier nonReentrant() {
        if (_status == _ENTERED) revert Reentrancy();
        _status = _ENTERED;
        _;
        _status = _NOT_ENTERED;
    }
}
