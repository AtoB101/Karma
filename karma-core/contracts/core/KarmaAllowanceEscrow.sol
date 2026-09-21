// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title KarmaAllowanceEscrow (v3) — non-custodial bilateral settlement
///
/// v3 (2026-09-20): ``submitSettlement`` is resolver-gated. v2 let either party
/// open the settlement window with an unvalidated ``proofHash``, so a seller
/// could pull the buyer's allowance without any delivery or confirmation — the
/// platform's verification was advisory. v3 makes "verified" a *condition*:
/// only the resolver (Karma's verification account) can start a settlement.
///
/// v4 (2026-09-21): the binding's *state machine* is the cancel gate, and the
/// buyer gets their own mark.
///
///   * ``buyerConfirm`` — the buyer's own "pay the seller" mark. It can only be
///     set while the binding is FINALIZING, i.e. after the resolver already
///     authorized the pull, and it only **shortens the wait**: once set,
///     ``finalizeSettlement`` no longer requires ``settleAfter`` to have
///     elapsed. It can never start a payment, raise an amount, or move money on
///     its own — every path it opens was already open, just slower.
///   * ``cancelBinding`` — allowed **only** from ``ACTIVE``, the one state in
///     which no money carries a responsibility. Once ``submitSettlement`` lands,
///     the funds have an owner-in-waiting, and both reservations may only be
///     released by the two exits that close the binding *and* move the money
///     (``finalizeSettlement`` / ``finalizeBreach``). Deliberate: a window that
///     either party can revoke is not protection for the other party, it is an
///     option to walk away after delivery.
///
/// v1 (`KarmaBilateral`) moved the payer's USDC *into* the contract, so every
/// later step needed the bill owner's signature again. v2 never takes custody:
///
///   * the payer keeps the USDC in their own wallet and grants this contract a
///     one-time ERC-20 allowance;
///   * `commit()` records a *responsibility* — "this wallet has committed up to
///     X" — backed by that allowance, not by funds this contract holds;
///   * settlement pulls straight from payer wallet to payee wallet
///         USDC: payerWallet --transferFrom--> payeeWallet
///   * the contract's token balance is always zero, enforced on every pull and
///     verifiable by anyone through `checkNoCustody()`.
///
/// `operator` is how the pledge becomes usable without per-order signatures:
/// the payer sets the operator (Karma's settlement executor, or their own agent)
/// once at commit time. The operator may bind and submit, but it can *never*
/// move funds on its own: the pull only succeeds while the payer's own ERC-20
/// allowance stands. Revoking the allowance is the payer's kill switch, and
/// `revoke()` / `setOperator(billId, address(0))` are the immediate ones.
interface IERC20Allowance {
    function allowance(address owner, address spender) external view returns (uint256);
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function balanceOf(address account) external view returns (uint256);
}

contract KarmaAllowanceEscrow {
    // ───────────────────────────────────────────────────────────────── errors
    error TokenNotAllowed();
    error ZeroAmount();
    error ZeroAddress();
    error NotBillOwner(uint256 billId);
    error NotBillOperator(uint256 billId);
    error WrongBillState(uint256 billId);
    error InsufficientAllowance(uint256 have, uint256 need);
    error InsufficientCommitment(uint256 available, uint256 need);
    error TokenMismatch();
    error SameOwner();
    error UnknownBinding(uint256 bindingId);
    error WrongBindingState(uint256 bindingId);
    error SettleDelayActive(uint256 settleAfter);
    error NotSettlementParty();
    error NotResolver();
    error PullFailed();
    error CustodyViolation();
    error ReservationActive(uint256 reserved);
    error AlreadyConfirmed(uint256 bindingId);

    enum BillState { NONE, OPEN, CLOSED }
    enum BindingState { NONE, ACTIVE, FINALIZING, SETTLED, SLASHED, CANCELLED }

    struct Bill {
        uint256 billId;
        address owner;    // wallet whose own funds back this responsibility
        address operator; // may bind/submit for this bill; can never move funds
        address token;
        uint256 amount;   // total committed
        uint256 reserved; // sum of amounts reserved by live bindings
        uint256 spent;    // settled out of this commitment
        BillState state;
        uint256 createdAt;
    }

    struct Binding {
        uint256 bindingId;
        uint256 buyerBillId;
        uint256 sellerBillId;
        bytes32 scopeHash;   // task/contract scope agreed off-chain
        uint256 amount;      // price pulled buyer -> seller on success
        uint256 stakeAmount; // seller stake pulled seller -> buyer on breach
        BindingState state;
        uint256 createdAt;
        uint256 settleAfter; // timestamp before which nothing may be pulled
        bytes32 proofHash;
        uint256 closedAt;
        //: 买方的「确认放款」标记。只在 FINALIZING 可置位；置位后 finalize 不等窗口。
        bool buyerConfirmed;
        uint256 confirmedAt;
    }

    address public immutable admin;
    address public disputeResolver;      // Karma verification / arbitration account
    uint256 public disputeWindowSeconds; // challenge window after submit()
    uint256 public settleDelaySeconds;   // cooling-off window before submit() is allowed
    bool public frozen;                  // emergency brake on *new* commitments only

    mapping(address => bool) public tokenAllowed;
    mapping(uint256 => Bill) public bills;
    mapping(uint256 => Binding) public bindings;
    mapping(address => uint256[]) private _ownerBills;
    uint256 private _billCounter;
    uint256 private _bindingCounter;

    event BillCommitted(uint256 indexed billId, address indexed owner, address indexed operator, address token, uint256 amount);
    event BillOperatorSet(uint256 indexed billId, address indexed operator);
    event BillRevoked(uint256 indexed billId, address indexed owner, uint256 unspent);
    event BillsBound(uint256 indexed bindingId, uint256 buyerBillId, uint256 sellerBillId, bytes32 scopeHash, uint256 amount, uint256 stakeAmount);
    event SettleSubmitted(uint256 indexed bindingId, bytes32 proofHash, uint256 pullAfter);
    event Settled(uint256 indexed bindingId, address from, address to, address token, uint256 amount);
    event StakeSlashed(uint256 indexed bindingId, address from, address to, address token, uint256 amount);
    event BindingCancelled(uint256 indexed bindingId);
    event BuyerConfirmed(uint256 indexed bindingId, address indexed by, uint256 confirmedAt);
    event DisputeWindowUpdated(uint256 seconds_);
    event SettleDelayUpdated(uint256 seconds_);
    event DisputeResolverUpdated(address indexed resolver);
    event TokenAllowedUpdated(address indexed token, bool allowed);
    event Frozen(bool value);

    constructor(uint256 disputeWindowSeconds_, uint256 settleDelaySeconds_) {
        admin = msg.sender;
        disputeResolver = msg.sender;
        disputeWindowSeconds = disputeWindowSeconds_;
        settleDelaySeconds = settleDelaySeconds_;
    }

    modifier onlyAdmin() {
        require(msg.sender == admin, "not admin");
        _;
    }

    modifier notFrozen() {
        // The brake can pause *new* commitments; it can never move, freeze or
        // unlock anybody's funds — those never left their own wallets.
        require(!frozen, "frozen");
        _;
    }

    // ───────────────────────────────────────────────────────────────── config

    function setTokenAllowed(address token, bool allowed) external onlyAdmin {
        if (token == address(0)) revert ZeroAddress();
        tokenAllowed[token] = allowed;
        emit TokenAllowedUpdated(token, allowed);
    }

    function setDisputeWindow(uint256 seconds_) external onlyAdmin {
        disputeWindowSeconds = seconds_;
        emit DisputeWindowUpdated(seconds_);
    }

    function setSettleDelay(uint256 seconds_) external onlyAdmin {
        settleDelaySeconds = seconds_;
        emit SettleDelayUpdated(seconds_);
    }

    function setDisputeResolver(address resolver) external onlyAdmin {
        if (resolver == address(0)) revert ZeroAddress();
        disputeResolver = resolver;
        emit DisputeResolverUpdated(resolver);
    }

    function setFrozen(bool value) external onlyAdmin {
        frozen = value;
        emit Frozen(value);
    }

    // ────────────────────────────────────────────────────────── commitments

    /// @notice Record `amount` of `token` as a responsibility backed by the
    ///         caller's own wallet. No tokens move. `operator` may later bind and
    ///         submit on the caller's behalf, but never move funds.
    function commit(address token, uint256 amount, address operator) external notFrozen returns (uint256 billId) {
        if (!tokenAllowed[token]) revert TokenNotAllowed();
        if (amount == 0) revert ZeroAmount();
        uint256 have = IERC20Allowance(token).allowance(msg.sender, address(this));
        if (have < amount) revert InsufficientAllowance(have, amount);

        unchecked { billId = ++_billCounter; }
        bills[billId] = Bill({
            billId: billId,
            owner: msg.sender,
            operator: operator,
            token: token,
            amount: amount,
            reserved: 0,
            spent: 0,
            state: BillState.OPEN,
            createdAt: block.timestamp
        });
        _ownerBills[msg.sender].push(billId);
        emit BillCommitted(billId, msg.sender, operator, token, amount);
    }

    /// @notice Hand (or take back) the right to bind/submit for this bill.
    ///         `address(0)` removes every delegate. Funds stay pullable only
    ///         through the owner's ERC-20 allowance either way.
    function setOperator(uint256 billId, address operator) external {
        Bill storage bill = _requireOpenBill(billId);
        if (bill.owner != msg.sender) revert NotBillOwner(billId);
        bill.operator = operator;
        emit BillOperatorSet(billId, operator);
    }

    /// @notice Cancel an unspent commitment. Fails while a live binding still
    ///         reserves part of it. The ERC-20 allowance itself is untouched —
    ///         lowering it is a plain `approve` from the owner's wallet.
    function revoke(uint256 billId) external {
        Bill storage bill = _requireOpenBill(billId);
        if (bill.owner != msg.sender) revert NotBillOwner(billId);
        if (bill.reserved != 0) revert ReservationActive(bill.reserved);
        bill.state = BillState.CLOSED;
        emit BillRevoked(billId, msg.sender, bill.amount - bill.spent);
    }

    // ─────────────────────────────────────────────────────────────── binding

    /// @notice Bind a buyer commitment against a seller commitment for a
    ///         specific price. Called by the buyer, or by the buyer's operator
    ///         (Karma executor / the buyer's agent) — that is what makes the
    ///         pledge usable without a signature per order.
    function bind(
        uint256 buyerBillId,
        uint256 sellerBillId,
        bytes32 scopeHash,
        uint256 amount,
        uint256 stakeAmount
    ) external notFrozen returns (uint256 bindingId) {
        Bill storage buyerBill = bills[buyerBillId];
        Bill storage sellerBill = bills[sellerBillId];
        if (buyerBill.state != BillState.OPEN) revert WrongBillState(buyerBillId);
        if (sellerBill.state != BillState.OPEN) revert WrongBillState(sellerBillId);
        if (!_canAct(buyerBill, msg.sender)) revert NotBillOperator(buyerBillId);
        if (buyerBill.token != sellerBill.token) revert TokenMismatch();
        if (buyerBill.owner == sellerBill.owner) revert SameOwner();
        if (amount == 0) revert ZeroAmount();
        if (stakeAmount == 0) revert ZeroAmount();

        uint256 buyerAvailable = buyerBill.amount - buyerBill.reserved - buyerBill.spent;
        if (buyerAvailable < amount) revert InsufficientCommitment(buyerAvailable, amount);
        uint256 sellerAvailable = sellerBill.amount - sellerBill.reserved - sellerBill.spent;
        if (sellerAvailable < stakeAmount) revert InsufficientCommitment(sellerAvailable, stakeAmount);

        buyerBill.reserved += amount;
        sellerBill.reserved += stakeAmount;

        unchecked { bindingId = ++_bindingCounter; }
        bindings[bindingId] = Binding({
            bindingId: bindingId,
            buyerBillId: buyerBillId,
            sellerBillId: sellerBillId,
            scopeHash: scopeHash,
            amount: amount,
            stakeAmount: stakeAmount,
            state: BindingState.ACTIVE,
            createdAt: block.timestamp,
            settleAfter: block.timestamp + settleDelaySeconds,
            proofHash: bytes32(0),
            closedAt: 0,
            buyerConfirmed: false,
            confirmedAt: 0
        });
        emit BillsBound(bindingId, buyerBillId, sellerBillId, scopeHash, amount, stakeAmount);
    }

    /// @notice Release both reservations — **only while the binding is ACTIVE**.
    ///
    ///         ``ACTIVE`` is the one state in which this binding's money carries
    ///         no responsibility: no proof has been submitted, nobody has been
    ///         told they will be paid, and the window has not started. Releasing
    ///         the reservations there just puts "you may spend this again" back
    ///         on both bills.
    ///
    ///         From ``FINALIZING`` on, the money has an owner-in-waiting: the
    ///         resolver has already ruled that delivery is verified and the pull
    ///         is armed. Letting either side cancel there would turn the dispute
    ///         window into an option to walk away *after* delivery — the seller
    ///         would have delivered and the buyer could still take the pledge
    ///         back with no arbitration. So the state machine refuses it, and the
    ///         only two exits left are the ones that also move the money:
    ///         ``finalizeSettlement`` (pay the seller) or ``finalizeBreach``
    ///         (slash the seller's stake to the buyer).
    ///
    ///         This is a *state* gate, never a clock gate: a binding whose
    ///         window has long elapsed but whose pull has not been cranked yet
    ///         is still FINALIZING and still not cancellable.
    function cancelBinding(uint256 bindingId) external {
        Binding storage b = _requireBinding(bindingId);
        if (b.state != BindingState.ACTIVE) revert WrongBindingState(bindingId);
        Bill storage buyerBill = bills[b.buyerBillId];
        Bill storage sellerBill = bills[b.sellerBillId];
        if (
            !_canAct(buyerBill, msg.sender) && !_canAct(sellerBill, msg.sender) && msg.sender != disputeResolver
        ) revert NotSettlementParty();

        buyerBill.reserved -= b.amount;
        sellerBill.reserved -= b.stakeAmount;
        b.state = BindingState.CANCELLED;
        b.closedAt = block.timestamp;
        emit BindingCancelled(bindingId);
    }

    /// @notice The buyer's own "this delivery is confirmed, pay the seller" mark.
    ///
    ///         The buyer (bill owner, or the operator they installed on that bill
    ///         — the same delegate that may bind for them) marks a binding that
    ///         the resolver has already submitted. From then on
    ///         ``finalizeSettlement`` pays out immediately instead of waiting
    ///         for ``settleAfter``: when both sides have confirmed there is
    ///         nothing left to dispute, so the window has no job.
    ///
    ///         What it can *not* do: open a settlement (resolver-only), change
    ///         the amount or the stake (fixed at ``bind``), touch another
    ///         binding, or outlive its own binding (FINALIZING only, and the
    ///         binding is single-use). Marking is therefore never a new power
    ///         over funds — it only makes an already-authorized pull faster.
    ///
    ///         If the buyer says nothing, nothing changes: the window still
    ///         expires on its own and the pull goes through.
    function buyerConfirm(uint256 bindingId) external {
        Binding storage b = _requireBinding(bindingId);
        if (b.state != BindingState.FINALIZING) revert WrongBindingState(bindingId);
        Bill storage buyerBill = bills[b.buyerBillId];
        if (!_canAct(buyerBill, msg.sender)) revert NotSettlementParty();
        if (b.buyerConfirmed) revert AlreadyConfirmed(bindingId);

        b.buyerConfirmed = true;
        b.confirmedAt = block.timestamp;
        emit BuyerConfirmed(bindingId, msg.sender, block.timestamp);
    }

    // ───────────────────────────────────────────────────────────── settling

    /// @notice Submit a verification proof and open the dispute window.
    ///
    ///         Only ``disputeResolver`` may call this. The resolver is the account
    ///         that runs verification off-chain, so the on-chain rule now matches
    ///         the product rule: **a settlement can only be started once
    ///         verification has passed**.
    ///
    ///         In v2 either party (and either operator) could open the window with
    ///         an arbitrary ``proofHash``. That let a seller pull the buyer's
    ///         allowance with no delivery, no confirmation and no arbitration —
    ///         every off-chain check was a convention, not a condition, and the
    ///         only real protection was the length of the window.
    ///
    ///         The rule after v3:
    ///           * verification passed  -> resolver opens the window, then
    ///             ``finalizeSettlement`` pays out once the window elapses
    ///             (permissionless: the destination is already fixed).
    ///           * verification failed  -> nobody can start the pull. Parties may
    ///             only ``cancelBinding``, which releases reservations and moves
    ///             no money.
    ///           * inside the window the reservations are **frozen**: this call
    ///             is the line after which only ``finalizeSettlement`` /
    ///             ``finalizeBreach`` may close the binding (v4).
    function submitSettlement(uint256 bindingId, bytes32 proofHash) external {
        Binding storage b = _requireBinding(bindingId);
        if (b.state != BindingState.ACTIVE) revert WrongBindingState(bindingId);
        if (msg.sender != disputeResolver) revert NotResolver();
        if (block.timestamp < b.settleAfter) revert SettleDelayActive(b.settleAfter);

        b.state = BindingState.FINALIZING;
        b.proofHash = proofHash;
        b.settleAfter = block.timestamp + disputeWindowSeconds;
        emit SettleSubmitted(bindingId, proofHash, b.settleAfter);
    }

    /// @notice Execute the pull: buyer wallet -> seller wallet.
    ///         Anyone may call — the window is the protection, not access control.
    ///         If the buyer revoked the allowance, this reverts and the seller is
    ///         simply not paid: an off-chain breach, never a stuck fund.
    ///
    ///         The window is skipped when the buyer has already marked this
    ///         binding with ``buyerConfirm``: verified delivery + the buyer's own
    ///         yes is exactly the case the window was there to wait out.
    function finalizeSettlement(uint256 bindingId) external returns (uint256 paid) {
        Binding storage b = _requireBinding(bindingId);
        if (b.state != BindingState.FINALIZING) revert WrongBindingState(bindingId);
        if (block.timestamp < b.settleAfter && !b.buyerConfirmed) revert SettleDelayActive(b.settleAfter);

        Bill storage buyerBill = bills[b.buyerBillId];
        Bill storage sellerBill = bills[b.sellerBillId];
        paid = b.amount;

        buyerBill.reserved -= paid;
        buyerBill.spent += paid;
        if (buyerBill.spent >= buyerBill.amount) buyerBill.state = BillState.CLOSED;
        sellerBill.reserved -= b.stakeAmount;

        b.state = BindingState.SETTLED;
        b.closedAt = block.timestamp;

        _pull(buyerBill.token, buyerBill.owner, sellerBill.owner, paid);
        emit Settled(bindingId, buyerBill.owner, sellerBill.owner, buyerBill.token, paid);
    }

    /// @notice Slash the seller's stake to the buyer when the resolver rules the
    ///         delivery a breach. Same non-custodial pull, opposite direction.
    function finalizeBreach(uint256 bindingId) external returns (uint256 slashed) {
        Binding storage b = _requireBinding(bindingId);
        if (b.state != BindingState.FINALIZING) revert WrongBindingState(bindingId);
        if (msg.sender != disputeResolver) revert NotResolver();
        if (block.timestamp < b.settleAfter) revert SettleDelayActive(b.settleAfter);

        Bill storage buyerBill = bills[b.buyerBillId];
        Bill storage sellerBill = bills[b.sellerBillId];
        slashed = b.stakeAmount;

        buyerBill.reserved -= b.amount;
        sellerBill.reserved -= slashed;
        sellerBill.spent += slashed;
        if (sellerBill.spent >= sellerBill.amount) sellerBill.state = BillState.CLOSED;

        b.state = BindingState.SLASHED;
        b.closedAt = block.timestamp;

        _pull(sellerBill.token, sellerBill.owner, buyerBill.owner, slashed);
        emit StakeSlashed(bindingId, sellerBill.owner, buyerBill.owner, sellerBill.token, slashed);
    }

    // ───────────────────────────────────────────────────────────────── views

    function getBill(uint256 billId) external view returns (Bill memory) {
        return bills[billId];
    }

    function getBinding(uint256 bindingId) external view returns (Binding memory) {
        return bindings[bindingId];
    }

    function ownerBills(address owner) external view returns (uint256[] memory) {
        return _ownerBills[owner];
    }

    /// @notice Pledge still usable for new bindings.
    function available(uint256 billId) external view returns (uint256) {
        Bill storage bill = _requireBill(billId);
        if (bill.state != BillState.OPEN) return 0;
        return bill.amount - bill.reserved - bill.spent;
    }

    /// @notice The custodian-free invariant, callable by anyone at any time.
    function checkNoCustody(address token) external view returns (bool) {
        return IERC20Allowance(token).balanceOf(address(this)) == 0;
    }

    /// @notice A commitment is only as good as the balance + allowance behind it
    ///         right now. Anyone can read this before trusting a pledge.
    function isBacked(uint256 billId) external view returns (bool) {
        Bill storage bill = bills[billId];
        if (bill.state != BillState.OPEN) return false;
        uint256 live = bill.amount - bill.spent;
        if (live == 0) return true;
        if (IERC20Allowance(bill.token).balanceOf(bill.owner) < live) return false;
        return IERC20Allowance(bill.token).allowance(bill.owner, address(this)) >= live;
    }

    function canActFor(uint256 billId, address who) external view returns (bool) {
        return _canAct(bills[billId], who);
    }

    // ───────────────────────────────────────────────────────────── internal

    function _pull(address token, address from, address to, uint256 amount) private {
        if (IERC20Allowance(token).allowance(from, address(this)) < amount) revert InsufficientAllowance(0, amount);
        if (!IERC20Allowance(token).transferFrom(from, to, amount)) revert PullFailed();
        if (IERC20Allowance(token).balanceOf(address(this)) != 0) revert CustodyViolation();
    }

    function _canAct(Bill storage bill, address who) private view returns (bool) {
        return who == bill.owner || (bill.operator != address(0) && who == bill.operator);
    }

    function _requireBill(uint256 billId) private view returns (Bill storage) {
        Bill storage bill = bills[billId];
        if (bill.billId == 0 || bill.state == BillState.NONE) revert UnknownBinding(billId);
        return bill;
    }

    function _requireOpenBill(uint256 billId) private view returns (Bill storage) {
        Bill storage bill = bills[billId];
        if (bill.billId == 0 || bill.state != BillState.OPEN) revert WrongBillState(billId);
        return bill;
    }

    function _requireBinding(uint256 bindingId) private view returns (Binding storage) {
        Binding storage b = bindings[bindingId];
        if (b.bindingId == 0 || b.state == BindingState.NONE) revert UnknownBinding(bindingId);
        return b;
    }
}