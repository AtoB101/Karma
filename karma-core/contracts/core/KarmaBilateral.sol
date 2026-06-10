// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Types} from "../libraries/Types.sol";

// ─────────────────────────────────────────────────────────────────────────────
//  KarmaBilateral — Bilateral Lock + Bill Token + KarmaFSM + Threshold Batch
//                   + Single Commitment Principle (SCP)
//                   + Three-Layer Verification (Optimistic / TEE / ZK)
//
//  Core interfaces:
//    lock(token, amount)  -> billId         mint Bill Token, USDC enters escrow
//    bind(buyer, agent, scope)              bilateral bind, both enter BOUND
//    settle(bindingId, proofHash)           Layer 1: submit proof, start dispute window
//    finalizeSettle(bindingId)              Layer 1: finalize after undisputed window
//    dispute(bindingId, evidenceHash)       Layer 1: challenge within dispute window
//    submitArbitrationEvidence(bindingId, h) submit counter-evidence (agent side)
//    autoResolveArbitration(bindingId)      auto-resolve small disputes after evidence window
//
//  Layer 2 — TEE (interface reserved, not yet implemented):
//    settleWithTEE(bindingId, proofHash, teeAttestation)
//      valid attestation -> skip dispute window, immediate settlement
//      invalid           -> fallback to Layer 1 optimistic flow
//
//  Layer 3 — ZK (interface reserved, not yet implemented):
//    settleWithZKProof(bindingId, proofHash, zkProof)
//      valid proof  -> immediate settlement
//      invalid      -> immediate refund
//
//  SCP:
//    authorize / accept / cancelAuthorization / unlock
//
//  KarmaIdentity:
//    registerIdentity / addSubAgent / removeSubAgent / setSubAgentAllowance
//
//  Attestation gate (existing N-of-M path via KarmaAttestationGateway):
//    bindWithAttestation / settle() from gateway -> immediate settlement
//
//  Governance constants (admin-adjustable):
//    DISPUTE_WINDOW              = 24 h   (Layer 1: window after settle() for disputes)
//    EVIDENCE_WINDOW             = 72 h   (arbitration evidence submission deadline)
//    AUTO_ARBITRATION_THRESHOLD  = 100 USDC (auto-resolve below this; DAO above)
//    settleDelaySeconds          = 30 min (min time after bind before settle() allowed)
//
//  Global invariant: totalBillSupply[token] == totalLocked[token]
//  Per-address:      freeBalance[a] + boundBalance[a] == totalMintedByAddr[a]
// ─────────────────────────────────────────────────────────────────────────────

interface IERC20Min {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
}

contract KarmaBilateral {

    // ═══════════════════════════ Errors ══════════════════════════════════════

    // Core
    error ZeroAmount();
    error ZeroAddress();
    error TokenNotAllowed();
    error NotBillOwner(uint256 billId);
    error WrongBillState(uint256 billId, BillState expected, BillState actual);
    error WrongBindingState(uint256 bindingId, BindingState expected, BindingState actual);
    error BillNotMinted(uint256 billId);
    error BindingNotFound(uint256 bindingId);
    error BuyerAgentSameAddress();
    error TransferFailed();
    error InvariantBroken(address token, uint256 supply, uint256 locked);
    error PerAddressInvariantBroken(address addr, uint256 free, uint256 bound, uint256 minted);
    error Reentrancy();
    error Unauthorized();
    error InvalidAddress();
    error InvalidSplit();
    error AttestationRequired(uint256 bindingId);
    error GatewayNotSet();
    // Layer 1 — Optimistic settlement
    error SettleDelayActive(uint256 endsAt);         // too early to call settle()
    error FinalizeWindowOpen(uint256 endsAt);        // dispute window not yet closed
    error DisputeWindowClosed(uint256 closedAt);     // too late to dispute
    error NoDisputeAccess(uint256 bindingId);        // caller not buyer/agent
    error DisputeNotExpired(uint256 bindingId);      // timeout not reached yet
    error EvidenceWindowClosed(uint256 bindingId);   // evidence window expired
    error EvidenceAlreadySubmitted(uint256 bindingId, address submitter);
    error ArbitrationNotStarted(uint256 bindingId);
    error ArbitrationAlreadyResolved(uint256 bindingId);
    error LargeDisputeRequiresAdmin(uint256 bindingId, uint256 totalPool);
    // Layer 2 — TEE (future)
    error TEENotImplemented();
    error TEEInvalidAttestation();
    // Layer 3 — ZK (future)
    error ZKNotImplemented();
    error ZKInvalidProof();
    // SCP
    error InsufficientFreeBalance(address addr, uint256 available, uint256 requested);
    error AuthorizationNotFound(uint256 authId);
    error AuthorizationAlreadyAccepted(uint256 authId);
    error AuthorizationExpired(uint256 authId);
    error NotAuthorizationRecipient(uint256 authId);
    // KarmaIdentity
    error IdentityAlreadyRegistered(address addr);
    error IdentityNotFound(address addr);
    error SubAgentLimitReached(address master);

    // IntentPackage errors
    error IntentPartyMismatch(string party);
    error IntentAmountMismatch(uint256 intent, uint256 buyer, uint256 agent);
    error IntentExpired(uint256 expiredAt);
    error SubAgentAlreadyAdded(address sub);
    error AllowanceExceedsFreeBalance(uint256 total, uint256 free);
    error SubAgentNotFound(address sub);
    error SubAgentHasBoundBalance(address sub, uint256 bound);

    // ═══════════════════════════ State Machines ══════════════════════════════

    enum BillState {
        MINTED,    // locked, available to bind
        BOUND,     // in active responsibility — frozen
        BURNED     // settled or refunded — terminal
    }

    enum BindingState {
        ACTIVE,       // both bills BOUND, task executing
        PENDING,      // batch threshold reached, awaiting settle()
        FINALIZING,   // Layer 1: settle() submitted, dispute window open
        SETTLED,      // finalized — terminal
        DISPUTED,     // dispute raised, awaiting arbitration
        REFUNDED      // cancelled / refunded — terminal
    }

    enum SubAgentStatus { ACTIVE, INACTIVE }

    // ═══════════════════════════ Data Structures ═════════════════════════════

    struct BillToken {
        uint256 billId;
        address owner;
        address token;
        uint256 amount;
        BillState state;
        uint256 mintedAt;
    }

    struct Binding {
        uint256 bindingId;
        uint256 buyerBillId;
        uint256 agentBillId;
        bytes32 scopeHash;
        BindingState state;
        uint256 createdAt;
        uint256 settleAfter;        // min time after bind before settle() (settle delay)
        bytes32 proofHash;          // stored when settle() is called
        uint256 settleSubmittedAt;  // Layer 1: timestamp when settle() was submitted
        uint256 disputedAt;         // timestamp when dispute() was called
        address disputeInitiator;
    }

    /// @notice Arbitration record — created when dispute() is called.
    struct ArbitrationRecord {
        bytes32 buyerEvidenceHash;   // submitted by buyer (with dispute() call)
        bytes32 agentEvidenceHash;   // submitted by agent (via submitArbitrationEvidence)
        uint256 buyerSubmittedAt;    // 0 if not yet submitted
        uint256 agentSubmittedAt;    // 0 if not yet submitted
        uint256 startedAt;           // when dispute() was called
        bool    resolved;
    }

    struct Authorization {
        uint256 authId;
        address from;
        address to;
        address token;
        uint256 amount;
        bool    accepted;
        uint256 createdAt;
        uint256 expiresAt;
    }

    struct SubAgent {
        address    subWallet;
        bytes32    subAgentId;
        address    master;
        uint256    allowance;
        SubAgentStatus status;
        uint256    addedAt;
        uint256    removedAt;
    }

    struct KarmaIdentity {
        address masterWallet;
        bytes32 masterAgentId;
        bool    registered;
    }

    // ═══════════════════════════ Storage ═════════════════════════════════════

    address public immutable admin;

    uint256 private _billCounter;
    uint256 private _bindingCounter;

    mapping(uint256 => BillToken) public bills;
    mapping(uint256 => Binding)   public bindings;
    mapping(uint256 => Types.IntentPackage) public intentPackages; // intent per binding

    mapping(address => uint256[]) private _ownerBills;
    mapping(address => bool)      public tokenAllowed;

    // ── Global invariant tracking ────────────────────────────────────────────
    mapping(address => uint256) public totalBillSupply;
    mapping(address => uint256) public totalLocked;

    // ── Batch threshold engine ───────────────────────────────────────────────
    mapping(address => uint256) public pendingBatchAmount;
    mapping(address => uint256) public batchThreshold;

    // ── Settlement timing ────────────────────────────────────────────────────

    /// @notice Minimum time after bind() before settle() can be called.
    uint256 public disputeWindowSeconds = 30 minutes;

    /// @notice Time after settle() during which buyer can dispute (Layer 1).
    uint256 public disputeWindow = 24 hours;

    /// @notice Time from dispute() during which both parties submit evidence.
    uint256 public evidenceWindow = 72 hours;

    /// @notice Disputes below this total pool value auto-resolve; above requires admin.
    ///         Default: 100 USDC (6 decimals).
    uint256 public autoArbitrationThreshold = 100_000_000;

    /// @notice Hard timeout — buyer may refund if settle never called.
    uint256 public settleTimeoutSeconds = 7 days;

    // ── Arbitration ──────────────────────────────────────────────────────────
    mapping(uint256 => ArbitrationRecord) public arbitrations;

    // ── Attestation gate ─────────────────────────────────────────────────────
    address public attestationGateway;
    mapping(uint256 => bytes32) public bindingTaskId;
    mapping(uint256 => bool)    public requiresAttestation;

    // ── SCP per-address balances ─────────────────────────────────────────────
    mapping(address => uint256) public freeBalance;
    mapping(address => uint256) public boundBalance;
    mapping(address => uint256) public totalMintedByAddr;
    mapping(address => uint256) public totalLockedByAddr;

    // ── Authorization ────────────────────────────────────────────────────────
    uint256 private _authCounter;
    mapping(uint256 => Authorization) public authorizations;
    mapping(address => uint256[])     private _pendingAuths;

    // ── KarmaIdentity ────────────────────────────────────────────────────────
    mapping(address => KarmaIdentity) public identities;
    mapping(address => bytes32[])     private _masterSubAgentIds;
    mapping(bytes32 => SubAgent)      public subAgentById;
    mapping(address => address)       public subAgentMaster;
    mapping(address => uint8)         public activeSubAgents;

    // ── Reentrancy guard ─────────────────────────────────────────────────────
    uint256 private _status = 1;

    // ═══════════════════════════ Events ══════════════════════════════════════

    event BillMinted(uint256 indexed billId, address indexed owner, address token, uint256 amount);
    event BillBurned(uint256 indexed billId, address indexed owner, uint256 amount, string reason);
    event BillsBound(uint256 indexed bindingId, uint256 buyerBillId, uint256 agentBillId, bytes32 scopeHash);
    event BindingSettled(uint256 indexed bindingId, bytes32 proofHash, uint256 buyerAmount, uint256 agentAmount);
    event BindingRefunded(uint256 indexed bindingId, uint256 buyerAmount, uint256 agentAmount);
    event DisputeResolved(uint256 indexed bindingId, uint256 buyerShareBps);
    event BatchThresholdUpdated(address indexed token, uint256 threshold);
    event TokenAllowed(address indexed token, bool allowed);
    event InvariantChecked(address indexed token, uint256 supply, uint256 locked);
    event AttestationGatewayUpdated(address indexed gateway);
    event DisputeWindowUpdated(uint256 seconds_);
    event OptimisticDisputeWindowUpdated(uint256 seconds_);
    event EvidenceWindowUpdated(uint256 seconds_);
    event AutoArbitrationThresholdUpdated(uint256 amount);
    event SettleTimeoutUpdated(uint256 seconds_);
    event AttestationBindingRegistered(uint256 indexed bindingId, bytes32 indexed taskId);
    event IntentBound(uint256 indexed bindingId, uint256 buyerBillId, uint256 agentBillId, bytes32 intentHash);
    // Layer 1 events
    event SettleSubmitted(uint256 indexed bindingId, bytes32 proofHash, uint256 finalizeAfter);
    event SettleFinalized(uint256 indexed bindingId, bytes32 proofHash);
    event DisputeRaised(uint256 indexed bindingId, address indexed initiator, bytes32 evidenceHash);
    event ArbitrationEvidenceSubmitted(uint256 indexed bindingId, address indexed submitter, bytes32 evidenceHash);
    event ArbitrationAutoResolved(uint256 indexed bindingId, bool buyerWon, uint256 buyerShare);
    // SCP events
    event AuthorizationCreated(uint256 indexed authId, address indexed from, address indexed to, uint256 amount);
    event AuthorizationAccepted(uint256 indexed authId, address indexed from, address indexed to);
    event AuthorizationCancelled(uint256 indexed authId, address indexed from);
    // KarmaIdentity events
    event IdentityRegistered(address indexed masterWallet, bytes32 masterAgentId);
    event SubAgentAdded(address indexed masterWallet, address indexed subWallet, bytes32 subAgentId);
    event SubAgentDeactivated(address indexed masterWallet, address indexed subWallet, bytes32 subAgentId);
    event SubAgentAllowanceUpdated(address indexed masterWallet, address indexed subWallet, uint256 allowance);

    // ═══════════════════════════ Constructor ═════════════════════════════════

    constructor(address admin_) {
        if (admin_ == address(0)) revert ZeroAddress();
        admin = admin_;
    }

    // ═══════════════════════════ Modifiers ═══════════════════════════════════

    modifier nonReentrant() {
        if (_status == 2) revert Reentrancy();
        _status = 2;
        _;
        _status = 1;
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  CORE — lock / bind / bindWithAttestation
    // ─────────────────────────────────────────────────────────────────────────

    /// @notice Lock USDC and mint a Bill Token (SBT) to caller.
    function lock(address token, uint256 amount)
        external
        nonReentrant
        returns (uint256 billId)
    {
        if (!tokenAllowed[token]) revert TokenNotAllowed();
        if (amount == 0)          revert ZeroAmount();
        if (token == address(0))  revert ZeroAddress();

        bool ok = IERC20Min(token).transferFrom(msg.sender, address(this), amount);
        if (!ok) revert TransferFailed();

        unchecked { billId = ++_billCounter; }
        bills[billId] = BillToken({
            billId:   billId,
            owner:    msg.sender,
            token:    token,
            amount:   amount,
            state:    BillState.MINTED,
            mintedAt: block.timestamp
        });
        _ownerBills[msg.sender].push(billId);

        totalLocked[token]     += amount;
        totalBillSupply[token] += amount;

        freeBalance[msg.sender]       += amount;
        totalMintedByAddr[msg.sender] += amount;
        totalLockedByAddr[msg.sender] += amount;

        _checkInvariant(token);
        _checkPerAddressInvariant(msg.sender);

        emit BillMinted(billId, msg.sender, token, amount);
    }

    /// @notice Bilaterally bind buyer and agent Bill Tokens.
    function bind(uint256 buyerBillId, uint256 agentBillId, bytes32 scopeHash)
        external
        nonReentrant
        returns (uint256 bindingId)
    {
        BillToken storage buyerBill = _requireBill(buyerBillId);
        BillToken storage agentBill = _requireBill(agentBillId);

        if (buyerBill.owner != msg.sender) revert NotBillOwner(buyerBillId);
        _requireBillState(buyerBillId, buyerBill.state, BillState.MINTED);
        _requireBillState(agentBillId, agentBill.state, BillState.MINTED);
        if (buyerBill.token != agentBill.token) revert TokenNotAllowed();
        if (buyerBill.owner == agentBill.owner) revert BuyerAgentSameAddress();

        buyerBill.state = BillState.BOUND;
        agentBill.state = BillState.BOUND;

        unchecked { bindingId = ++_bindingCounter; }
        bindings[bindingId] = Binding({
            bindingId:        bindingId,
            buyerBillId:      buyerBillId,
            agentBillId:      agentBillId,
            scopeHash:        scopeHash,
            state:            BindingState.ACTIVE,
            createdAt:        block.timestamp,
            settleAfter:      block.timestamp + disputeWindowSeconds,
            proofHash:        bytes32(0),
            settleSubmittedAt: 0,
            disputedAt:       0,
            disputeInitiator: address(0)
        });

        address token    = buyerBill.token;
        uint256 buyerAmt = buyerBill.amount;
        uint256 agentAmt = agentBill.amount;
        pendingBatchAmount[token] += buyerAmt + agentAmt;

        _moveFreeTobound(buyerBill.owner, buyerAmt);
        _moveFreeTobound(agentBill.owner, agentAmt);

        if (batchThreshold[token] > 0 && pendingBatchAmount[token] >= batchThreshold[token]) {
            bindings[bindingId].state = BindingState.PENDING;
        }

        emit BillsBound(bindingId, buyerBillId, agentBillId, scopeHash);
    }

    /// @notice Bind with N-of-M attestation requirement.
    function bindWithAttestation(
        uint256 buyerBillId,
        uint256 agentBillId,
        bytes32 scopeHash,
        bytes32 taskId
    )
        external
        nonReentrant
        returns (uint256 bindingId)
    {
        if (attestationGateway == address(0)) revert GatewayNotSet();
        if (taskId == bytes32(0)) revert ZeroAmount();

        BillToken storage buyerBill = _requireBill(buyerBillId);
        BillToken storage agentBill = _requireBill(agentBillId);

        if (buyerBill.owner != msg.sender) revert NotBillOwner(buyerBillId);
        _requireBillState(buyerBillId, buyerBill.state, BillState.MINTED);
        _requireBillState(agentBillId, agentBill.state, BillState.MINTED);
        if (buyerBill.token != agentBill.token) revert TokenNotAllowed();
        if (buyerBill.owner == agentBill.owner) revert BuyerAgentSameAddress();

        buyerBill.state = BillState.BOUND;
        agentBill.state = BillState.BOUND;

        unchecked { bindingId = ++_bindingCounter; }
        bindings[bindingId] = Binding({
            bindingId:        bindingId,
            buyerBillId:      buyerBillId,
            agentBillId:      agentBillId,
            scopeHash:        scopeHash,
            state:            BindingState.ACTIVE,
            createdAt:        block.timestamp,
            settleAfter:      block.timestamp + disputeWindowSeconds,
            proofHash:        bytes32(0),
            settleSubmittedAt: 0,
            disputedAt:       0,
            disputeInitiator: address(0)
        });

        requiresAttestation[bindingId] = true;
        bindingTaskId[bindingId]       = taskId;

        address token    = buyerBill.token;
        uint256 buyerAmt = buyerBill.amount;
        uint256 agentAmt = agentBill.amount;
        pendingBatchAmount[token] += buyerAmt + agentAmt;

        _moveFreeTobound(buyerBill.owner, buyerAmt);
        _moveFreeTobound(agentBill.owner, agentAmt);

        if (batchThreshold[token] > 0 && pendingBatchAmount[token] >= batchThreshold[token]) {
            bindings[bindingId].state = BindingState.PENDING;
        }

        emit BillsBound(bindingId, buyerBillId, agentBillId, scopeHash);
        emit AttestationBindingRegistered(bindingId, taskId);
    }

    /// @notice Bind using a structured IntentPackage instead of raw scopeHash.
    ///         The intent defines buyer, seller, service type, amount, deadline,
    ///         required proof fields, verifier, and dispute parameters.
    ///         This is the canonical bind for AI-agent commerce — the intent IS
    ///         the contract.
    function bindWithIntent(
        Types.IntentPackage calldata intent,
        uint256 buyerBillId,
        uint256 agentBillId
    )
        external
        nonReentrant
        returns (uint256 bindingId)
    {
        BillToken storage buyerBill = _requireBill(buyerBillId);
        BillToken storage agentBill = _requireBill(agentBillId);

        // ═══ Basic bill ownership/state checks ═══
        if (buyerBill.owner != msg.sender) revert NotBillOwner(buyerBillId);
        _requireBillState(buyerBillId, buyerBill.state, BillState.MINTED);
        _requireBillState(agentBillId, agentBill.state, BillState.MINTED);
        if (buyerBill.token != agentBill.token) revert TokenNotAllowed();
        if (buyerBill.owner == agentBill.owner) revert BuyerAgentSameAddress();

        // ═══ Intent validation ═══
        if (intent.buyer != buyerBill.owner) revert IntentPartyMismatch("buyer");
        if (intent.seller != agentBill.owner) revert IntentPartyMismatch("seller");
        if (intent.amount != buyerBill.amount || intent.amount != agentBill.amount)
            revert IntentAmountMismatch(intent.amount, buyerBill.amount, agentBill.amount);
        if (intent.expiresAt < block.timestamp) revert IntentExpired(intent.expiresAt);
        if (intent.serviceType == bytes32(0)) revert ZeroAmount();

        buyerBill.state = BillState.BOUND;
        agentBill.state = BillState.BOUND;

        bytes32 intentHash = keccak256(abi.encode(intent));

        unchecked { bindingId = ++_bindingCounter; }
        bindings[bindingId] = Binding({
            bindingId:        bindingId,
            buyerBillId:      buyerBillId,
            agentBillId:      agentBillId,
            scopeHash:        intentHash,
            state:            BindingState.ACTIVE,
            createdAt:        block.timestamp,
            settleAfter:      block.timestamp + disputeWindowSeconds,
            proofHash:        bytes32(0),
            settleSubmittedAt: 0,
            disputedAt:       0,
            disputeInitiator: address(0)
        });

        // Store the full intent on-chain for verification + audit
        intentPackages[bindingId] = intent;

        // If intent specifies a verifier, register attestation requirement
        if (intent.verifier != address(0)) {
            requiresAttestation[bindingId] = true;
            bindingTaskId[bindingId] = intentHash;
        }

        address token    = buyerBill.token;
        uint256 buyerAmt = buyerBill.amount;
        uint256 agentAmt = agentBill.amount;
        pendingBatchAmount[token] += buyerAmt + agentAmt;

        _moveFreeTobound(buyerBill.owner, buyerAmt);
        _moveFreeTobound(agentBill.owner, agentAmt);

        if (batchThreshold[token] > 0 && pendingBatchAmount[token] >= batchThreshold[token]) {
            bindings[bindingId].state = BindingState.PENDING;
        }

        emit BillsBound(bindingId, buyerBillId, agentBillId, intentHash);
        emit IntentBound(bindingId, buyerBillId, agentBillId, intentHash);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  LAYER 1 — Optimistic Settlement
    //  Flow: settle() -> FINALIZING -> [dispute?] -> finalizeSettle() / DISPUTED
    // ─────────────────────────────────────────────────────────────────────────

    /// @notice Submit settlement proof. Starts the dispute window (Layer 1).
    ///
    ///         Standard path (no attestation):
    ///           - Caller must be buyer or agent.
    ///           - If ACTIVE: block.timestamp must be >= settleAfter (settle delay).
    ///           - Binding transitions to FINALIZING; USDC is NOT released yet.
    ///           - Call finalizeSettle() after disputeWindow to complete settlement.
    ///
    ///         Attested path (via KarmaAttestationGateway):
    ///           - Only the gateway may call; N-of-M quorum already verified.
    ///           - Immediately finalizes — no dispute window.
    ///
    /// @param  bindingId  Binding to settle.
    /// @param  proofHash  keccak256 of execution proof / evidence bundle.
    function settle(uint256 bindingId, bytes32 proofHash)
        external
        nonReentrant
    {
        Binding storage b = _requireBinding(bindingId);

        if (b.state != BindingState.ACTIVE && b.state != BindingState.PENDING) {
            revert WrongBindingState(bindingId, BindingState.ACTIVE, b.state);
        }

        BillToken storage buyerBill = bills[b.buyerBillId];
        BillToken storage agentBill = bills[b.agentBillId];

        if (requiresAttestation[bindingId]) {
            // ── Attested path: gateway already enforced N-of-M quorum + challenge window.
            //    Bypass Layer 1 dispute window and settle immediately.
            if (msg.sender != attestationGateway) revert AttestationRequired(bindingId);
            _executeSettle(bindingId, b, buyerBill, agentBill, proofHash);
        } else {
            // ── Standard path: Layer 1 optimistic settlement.
            if (msg.sender != buyerBill.owner && msg.sender != agentBill.owner) {
                revert NoDisputeAccess(bindingId);
            }
            // Settle delay only applies to ACTIVE state (not PENDING/batch)
            if (b.state == BindingState.ACTIVE && block.timestamp < b.settleAfter) {
                revert SettleDelayActive(b.settleAfter);
            }

            b.state            = BindingState.FINALIZING;
            b.proofHash        = proofHash;
            b.settleSubmittedAt = block.timestamp;

            emit SettleSubmitted(bindingId, proofHash, block.timestamp + disputeWindow);
        }
    }

    /// @notice Finalize a FINALIZING binding after the dispute window closes.
    ///         Anyone may call — the window is the protection, not access control.
    ///         Burns both Bill Tokens and releases USDC to each party.
    function finalizeSettle(uint256 bindingId)
        external
        nonReentrant
    {
        Binding storage b = _requireBinding(bindingId);
        if (b.state != BindingState.FINALIZING) {
            revert WrongBindingState(bindingId, BindingState.FINALIZING, b.state);
        }

        uint256 windowEnd = b.settleSubmittedAt + disputeWindow;
        if (block.timestamp < windowEnd) {
            revert FinalizeWindowOpen(windowEnd);
        }

        BillToken storage buyerBill = bills[b.buyerBillId];
        BillToken storage agentBill = bills[b.agentBillId];

        _executeSettle(bindingId, b, buyerBill, agentBill, b.proofHash);
    }

    /// @notice Buyer challenges a FINALIZING settlement within the dispute window.
    ///         Both Bill Tokens remain frozen; the binding enters DISPUTED state.
    ///         The agent must submit counter-evidence via submitArbitrationEvidence().
    ///
    /// @param  bindingId     Binding to challenge.
    /// @param  evidenceHash  keccak256 of buyer's challenge evidence (IPFS CID hash etc.).
    function dispute(uint256 bindingId, bytes32 evidenceHash)
        external
        nonReentrant
    {
        Binding storage b = _requireBinding(bindingId);
        if (b.state != BindingState.FINALIZING) {
            revert WrongBindingState(bindingId, BindingState.FINALIZING, b.state);
        }

        // Dispute window: [settleSubmittedAt, settleSubmittedAt + disputeWindow)
        uint256 windowEnd = b.settleSubmittedAt + disputeWindow;
        if (block.timestamp >= windowEnd) {
            revert DisputeWindowClosed(windowEnd);
        }

        // Only the buyer may raise a settlement dispute
        BillToken storage buyerBill = bills[b.buyerBillId];
        if (msg.sender != buyerBill.owner) revert NoDisputeAccess(bindingId);

        b.state            = BindingState.DISPUTED;
        b.disputedAt       = block.timestamp;
        b.disputeInitiator = msg.sender;

        // Record buyer's initial evidence
        arbitrations[bindingId] = ArbitrationRecord({
            buyerEvidenceHash: evidenceHash,
            agentEvidenceHash: bytes32(0),
            buyerSubmittedAt:  block.timestamp,
            agentSubmittedAt:  0,
            startedAt:         block.timestamp,
            resolved:          false
        });

        emit DisputeRaised(bindingId, msg.sender, evidenceHash);
    }

    /// @notice Either party submits / updates evidence during the evidence window.
    ///         Evidence window: [disputedAt, disputedAt + evidenceWindow).
    ///         Buyer uses this to update evidence; agent uses it to counter.
    function submitArbitrationEvidence(uint256 bindingId, bytes32 evidenceHash)
        external
        nonReentrant
    {
        Binding storage b = _requireBinding(bindingId);
        if (b.state != BindingState.DISPUTED) {
            revert WrongBindingState(bindingId, BindingState.DISPUTED, b.state);
        }

        ArbitrationRecord storage arb = arbitrations[bindingId];
        if (arb.startedAt == 0) revert ArbitrationNotStarted(bindingId);
        if (arb.resolved)       revert ArbitrationAlreadyResolved(bindingId);

        uint256 windowEnd = arb.startedAt + evidenceWindow;
        if (block.timestamp >= windowEnd) revert EvidenceWindowClosed(bindingId);

        BillToken storage buyerBill = bills[b.buyerBillId];
        BillToken storage agentBill = bills[b.agentBillId];

        if (msg.sender == buyerBill.owner) {
            arb.buyerEvidenceHash = evidenceHash;
            arb.buyerSubmittedAt  = block.timestamp;
        } else if (msg.sender == agentBill.owner) {
            arb.agentEvidenceHash = evidenceHash;
            arb.agentSubmittedAt  = block.timestamp;
        } else {
            revert NoDisputeAccess(bindingId);
        }

        emit ArbitrationEvidenceSubmitted(bindingId, msg.sender, evidenceHash);
    }

    /// @notice Auto-resolve a dispute after the evidence window closes.
    ///
    ///         Auto-resolution rules (only for totalPool < autoArbitrationThreshold):
    ///           - Only agent submitted evidence  → agent wins  → settlement finalized
    ///           - Only buyer submitted evidence  → buyer wins  → full refund
    ///           - Neither submitted             → buyer wins  → full refund (conservative)
    ///           - Both submitted                → 50/50 split
    ///
    ///         If totalPool >= autoArbitrationThreshold, reverts with LargeDisputeRequiresAdmin.
    ///         In that case, admin must call resolveDispute(bindingId, buyerShareBps).
    ///
    ///         Anyone may trigger after the evidence window closes.
    function autoResolveArbitration(uint256 bindingId)
        external
        nonReentrant
    {
        Binding storage b = _requireBinding(bindingId);
        if (b.state != BindingState.DISPUTED) {
            revert WrongBindingState(bindingId, BindingState.DISPUTED, b.state);
        }

        ArbitrationRecord storage arb = arbitrations[bindingId];
        if (arb.startedAt == 0) revert ArbitrationNotStarted(bindingId);
        if (arb.resolved)       revert ArbitrationAlreadyResolved(bindingId);

        // Evidence window must have closed
        uint256 windowEnd = arb.startedAt + evidenceWindow;
        if (block.timestamp < windowEnd) revert FinalizeWindowOpen(windowEnd);

        BillToken storage buyerBill = bills[b.buyerBillId];
        BillToken storage agentBill = bills[b.agentBillId];
        uint256 totalPool = buyerBill.amount + agentBill.amount;

        // Large disputes require admin (DAO governance in future)
        if (totalPool >= autoArbitrationThreshold) {
            revert LargeDisputeRequiresAdmin(bindingId, totalPool);
        }

        arb.resolved = true;

        bool buyerSubmitted = arb.buyerSubmittedAt != 0;
        bool agentSubmitted = arb.agentSubmittedAt != 0;

        if (agentSubmitted && !buyerSubmitted) {
            // Agent wins: finalize the settlement
            emit ArbitrationAutoResolved(bindingId, false, 0);
            _executeSettle(bindingId, b, buyerBill, agentBill, b.proofHash);
        } else if (buyerSubmitted && !agentSubmitted) {
            // Buyer wins: full refund
            emit ArbitrationAutoResolved(bindingId, true, 10_000);
            _executeRefund(bindingId, b, buyerBill, agentBill);
        } else if (!buyerSubmitted && !agentSubmitted) {
            // Neither submitted: conservative refund
            emit ArbitrationAutoResolved(bindingId, true, 10_000);
            _executeRefund(bindingId, b, buyerBill, agentBill);
        } else {
            // Both submitted: 50/50 split
            emit ArbitrationAutoResolved(bindingId, false, 5_000);
            _executeSplit(bindingId, b, buyerBill, agentBill, 5_000);
        }
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  LAYER 2 — TEE Verification (interface reserved, not yet implemented)
    // ─────────────────────────────────────────────────────────────────────────

    /// @notice [LAYER 2 — NOT YET IMPLEMENTED]
    ///         Settle by verifying a TEE (Trusted Execution Environment) hardware
    ///         attestation report. Valid attestation skips the Layer 1 dispute window;
    ///         invalid attestation falls back to the optimistic flow.
    ///
    ///         Future implementation:
    ///           bytes teeAttestation = abi.encode(
    ///               reportData,    // bytes32: keccak256(bindingId || proofHash)
    ///               mrEnclave,     // bytes32: expected measurement of enclave
    ///               mrSigner,      // bytes32: signing authority
    ///               isvSvn,        // uint16:  security version number
    ///               signature      // bytes:   ECDSA over the report
    ///           );
    ///           Verification: ITEEVerifier(teeVerifier).verify(teeAttestation)
    ///           If valid  -> _executeSettle()  (immediate, no dispute window)
    ///           If invalid -> _beginOptimisticSettle() (fallback to Layer 1)
    ///
    /// @param  bindingId      Binding to settle.
    /// @param  proofHash      keccak256 of execution proof.
    /// @param  teeAttestation ABI-encoded TEE attestation report + signature.
    function settleWithTEE(
        uint256 bindingId,
        bytes32 proofHash,
        bytes calldata teeAttestation
    ) external nonReentrant {
        // Suppress unused variable warnings for stub
        bindingId;
        proofHash;
        teeAttestation;
        // TODO: Layer 2 implementation
        revert TEENotImplemented();
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  LAYER 3 — ZK Proof Verification (interface reserved, not yet implemented)
    // ─────────────────────────────────────────────────────────────────────────

    /// @notice [LAYER 3 — NOT YET IMPLEMENTED]
    ///         Settle by verifying a Zero-Knowledge proof of correct execution.
    ///         Valid proof settles immediately; invalid proof triggers an immediate
    ///         refund (no optimistic fallback — ZK proofs are deterministic).
    ///
    ///         Future implementation:
    ///           bytes zkProof = abi.encode(
    ///               proof_a,       // uint256[2]: G1 point
    ///               proof_b,       // uint256[2][2]: G2 point
    ///               proof_c,       // uint256[2]: G1 point
    ///               publicInputs   // uint256[]: [bindingId, proofHash, ...]
    ///           );
    ///           Verification: IZKVerifier(zkVerifier).verifyProof(proof_a, proof_b, proof_c, publicInputs)
    ///           If valid  -> _executeSettle()  (immediate)
    ///           If invalid -> _executeRefund() (immediate, no appeal)
    ///
    /// @param  bindingId  Binding to settle.
    /// @param  proofHash  keccak256 of execution proof (must match ZK public input).
    /// @param  zkProof    ABI-encoded Groth16/PLONK proof + public inputs.
    function settleWithZKProof(
        uint256 bindingId,
        bytes32 proofHash,
        bytes calldata zkProof
    ) external nonReentrant {
        bindingId;
        proofHash;
        zkProof;
        // TODO: Layer 3 implementation
        revert ZKNotImplemented();
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  ADMIN DISPUTE RESOLUTION (for large disputes / DAO override)
    // ─────────────────────────────────────────────────────────────────────────

    /// @notice Admin resolves a DISPUTED binding by specifying buyer's BPS share.
    ///         Used for large disputes (totalPool >= autoArbitrationThreshold)
    ///         or as an override for any dispute.
    ///         Future: replace admin with DAO governance contract.
    /// @param  buyerShareBps  Buyer's fraction of combined pool (10000 = 100%).
    function resolveDispute(uint256 bindingId, uint16 buyerShareBps)
        external
        nonReentrant
        onlyAdmin
    {
        if (buyerShareBps > 10_000) revert InvalidSplit();
        Binding storage b = _requireBinding(bindingId);
        if (b.state != BindingState.DISPUTED) {
            revert WrongBindingState(bindingId, BindingState.DISPUTED, b.state);
        }

        // Mark arbitration resolved if it exists
        ArbitrationRecord storage arb = arbitrations[bindingId];
        if (arb.startedAt != 0) arb.resolved = true;

        BillToken storage buyerBill = bills[b.buyerBillId];
        BillToken storage agentBill = bills[b.agentBillId];

        emit DisputeResolved(bindingId, buyerShareBps);
        _executeSplit(bindingId, b, buyerBill, agentBill, buyerShareBps);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  TIMEOUT REFUND
    // ─────────────────────────────────────────────────────────────────────────

    /// @notice Buyer recovers funds if settle() is never called within settleTimeoutSeconds.
    function refundOnTimeout(uint256 bindingId) external nonReentrant {
        Binding storage b = _requireBinding(bindingId);
        if (b.state != BindingState.ACTIVE && b.state != BindingState.PENDING) {
            revert WrongBindingState(bindingId, BindingState.ACTIVE, b.state);
        }
        if (block.timestamp < b.createdAt + settleTimeoutSeconds) {
            revert DisputeNotExpired(bindingId);
        }

        BillToken storage buyerBill = bills[b.buyerBillId];
        if (msg.sender != buyerBill.owner) revert NotBillOwner(b.buyerBillId);

        BillToken storage agentBill = bills[b.agentBillId];

        _executeRefund(bindingId, b, buyerBill, agentBill);
        emit BindingRefunded(bindingId, buyerBill.amount, agentBill.amount);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  UNLOCK — withdraw MINTED (unbound) bill
    // ─────────────────────────────────────────────────────────────────────────

    /// @notice Withdraw a MINTED (unbound) Bill Token (SCP: freeBalance only).
    function unlock(uint256 billId) external nonReentrant {
        BillToken storage bill = _requireBill(billId);
        if (bill.owner != msg.sender) revert NotBillOwner(billId);
        _requireBillState(billId, bill.state, BillState.MINTED);

        address token  = bill.token;
        uint256 amount = bill.amount;

        if (freeBalance[msg.sender] < amount) {
            revert InsufficientFreeBalance(msg.sender, freeBalance[msg.sender], amount);
        }

        freeBalance[msg.sender]       -= amount;
        totalLockedByAddr[msg.sender] -= amount;
        totalMintedByAddr[msg.sender] -= amount;

        _burnBill(billId, bill, "unlocked");
        _transfer(token, msg.sender, amount);

        _checkInvariant(token);
        _checkPerAddressInvariant(msg.sender);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  SCP — authorize / accept / cancelAuthorization
    // ─────────────────────────────────────────────────────────────────────────

    function authorize(
        address token,
        uint256 amount,
        address to,
        uint256 expiresAt
    ) external nonReentrant returns (uint256 authId) {
        if (!tokenAllowed[token]) revert TokenNotAllowed();
        if (amount == 0)          revert ZeroAmount();
        if (to == address(0))     revert ZeroAddress();
        if (freeBalance[msg.sender] < amount) {
            revert InsufficientFreeBalance(msg.sender, freeBalance[msg.sender], amount);
        }

        freeBalance[msg.sender] -= amount;

        unchecked { authId = ++_authCounter; }
        authorizations[authId] = Authorization({
            authId:    authId,
            from:      msg.sender,
            to:        to,
            token:     token,
            amount:    amount,
            accepted:  false,
            createdAt: block.timestamp,
            expiresAt: expiresAt
        });
        _pendingAuths[msg.sender].push(authId);

        _checkPerAddressInvariant(msg.sender);
        emit AuthorizationCreated(authId, msg.sender, to, amount);
    }

    function accept(uint256 authId) external nonReentrant {
        Authorization storage auth = _requireAuth(authId);
        if (auth.to != msg.sender) revert NotAuthorizationRecipient(authId);
        if (auth.accepted)         revert AuthorizationAlreadyAccepted(authId);
        if (auth.expiresAt != 0 && block.timestamp > auth.expiresAt) {
            revert AuthorizationExpired(authId);
        }

        auth.accepted = true;

        boundBalance[auth.from]    += auth.amount;
        freeBalance[auth.to]       += auth.amount;
        totalMintedByAddr[auth.to] += auth.amount;
        totalLockedByAddr[auth.to] += auth.amount;

        _checkPerAddressInvariant(auth.from);
        _checkPerAddressInvariant(auth.to);
        emit AuthorizationAccepted(authId, auth.from, auth.to);
    }

    function cancelAuthorization(uint256 authId) external nonReentrant {
        Authorization storage auth = _requireAuth(authId);
        if (auth.from != msg.sender) revert Unauthorized();
        if (auth.accepted)           revert AuthorizationAlreadyAccepted(authId);

        auth.accepted = true;
        freeBalance[msg.sender] += auth.amount;

        _checkPerAddressInvariant(msg.sender);
        emit AuthorizationCancelled(authId, msg.sender);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  KARMA IDENTITY — master + max 3 active sub-agents
    // ─────────────────────────────────────────────────────────────────────────

    function registerIdentity(bytes32 masterAgentId) external {
        if (identities[msg.sender].registered) revert IdentityAlreadyRegistered(msg.sender);
        identities[msg.sender] = KarmaIdentity({
            masterWallet:  msg.sender,
            masterAgentId: masterAgentId,
            registered:    true
        });
        emit IdentityRegistered(msg.sender, masterAgentId);
    }

    function addSubAgent(address subWallet, bytes32 subAgentId) external {
        _requireIdentity(msg.sender);
        if (subWallet == address(0))                 revert ZeroAddress();
        if (subAgentId == bytes32(0))                revert ZeroAmount();
        if (activeSubAgents[msg.sender] >= 3)        revert SubAgentLimitReached(msg.sender);
        if (subAgentMaster[subWallet] != address(0)) revert SubAgentAlreadyAdded(subWallet);
        if (subAgentById[subAgentId].addedAt != 0)   revert SubAgentAlreadyAdded(subWallet);

        subAgentById[subAgentId] = SubAgent({
            subWallet:  subWallet,
            subAgentId: subAgentId,
            master:     msg.sender,
            allowance:  0,
            status:     SubAgentStatus.ACTIVE,
            addedAt:    block.timestamp,
            removedAt:  0
        });

        _masterSubAgentIds[msg.sender].push(subAgentId);
        subAgentMaster[subWallet] = msg.sender;
        activeSubAgents[msg.sender] += 1;

        emit SubAgentAdded(msg.sender, subWallet, subAgentId);
    }

    function removeSubAgent(address subWallet) external {
        _requireIdentity(msg.sender);
        bytes32 subAgentId = _findActiveSubAgentId(msg.sender, subWallet);
        SubAgent storage sa = subAgentById[subAgentId];

        if (boundBalance[subWallet] != 0) {
            revert SubAgentHasBoundBalance(subWallet, boundBalance[subWallet]);
        }

        sa.status    = SubAgentStatus.INACTIVE;
        sa.allowance = 0;
        sa.removedAt = block.timestamp;
        activeSubAgents[msg.sender] -= 1;

        emit SubAgentDeactivated(msg.sender, subWallet, subAgentId);
    }

    function setSubAgentAllowance(address subWallet, uint256 allowance) external {
        _requireIdentity(msg.sender);
        bytes32 subAgentId = _findActiveSubAgentId(msg.sender, subWallet);
        subAgentById[subAgentId].allowance = allowance;

        uint256 totalAllowance = 0;
        bytes32[] storage ids = _masterSubAgentIds[msg.sender];
        uint256 len = ids.length;
        for (uint256 i = 0; i < len; i++) {
            SubAgent storage sa = subAgentById[ids[i]];
            if (sa.status == SubAgentStatus.ACTIVE) totalAllowance += sa.allowance;
        }
        if (totalAllowance > freeBalance[msg.sender]) {
            revert AllowanceExceedsFreeBalance(totalAllowance, freeBalance[msg.sender]);
        }
        emit SubAgentAllowanceUpdated(msg.sender, subWallet, allowance);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  VIEW FUNCTIONS
    // ─────────────────────────────────────────────────────────────────────────

    function getBill(uint256 billId) external view returns (BillToken memory) {
        return bills[billId];
    }

    function getBinding(uint256 bindingId) external view returns (Binding memory) {
        return bindings[bindingId];
    }

    function getIntentPackage(uint256 bindingId) external view returns (Types.IntentPackage memory) {
        return intentPackages[bindingId];
    }

    function getArbitration(uint256 bindingId) external view returns (ArbitrationRecord memory) {
        return arbitrations[bindingId];
    }

    function ownerBills(address owner) external view returns (uint256[] memory) {
        return _ownerBills[owner];
    }

    function checkInvariant(address token) external view returns (bool) {
        return totalBillSupply[token] == totalLocked[token];
    }

    function checkPerAddressInvariant(address addr) external view returns (bool) {
        return (freeBalance[addr] + boundBalance[addr]) == totalMintedByAddr[addr];
    }

    function getBalance(address addr) external view returns (
        uint256 free,
        uint256 bound,
        uint256 totalMinted,
        uint256 totalLocked_
    ) {
        return (freeBalance[addr], boundBalance[addr], totalMintedByAddr[addr], totalLockedByAddr[addr]);
    }

    function getAuthorization(uint256 authId) external view returns (Authorization memory) {
        return authorizations[authId];
    }

    function getIdentity(address master) external view returns (KarmaIdentity memory) {
        return identities[master];
    }

    function getSubAgents(address master) external view returns (SubAgent[] memory active) {
        bytes32[] storage ids = _masterSubAgentIds[master];
        uint256 len = ids.length;
        uint256 count = 0;
        for (uint256 i = 0; i < len; i++) {
            if (subAgentById[ids[i]].status == SubAgentStatus.ACTIVE) count++;
        }
        active = new SubAgent[](count);
        uint256 j = 0;
        for (uint256 i = 0; i < len; i++) {
            if (subAgentById[ids[i]].status == SubAgentStatus.ACTIVE) {
                active[j++] = subAgentById[ids[i]];
            }
        }
    }

    function getSubAgentHistory(address master) external view returns (SubAgent[] memory history) {
        bytes32[] storage ids = _masterSubAgentIds[master];
        uint256 len = ids.length;
        history = new SubAgent[](len);
        for (uint256 i = 0; i < len; i++) history[i] = subAgentById[ids[i]];
    }

    function getMaster(bytes32 subAgentId) external view returns (address) {
        return subAgentById[subAgentId].master;
    }

    function getMasterOf(address subWallet) external view returns (address) {
        return subAgentMaster[subWallet];
    }

    /// @notice Return the timestamp when finalizeSettle() becomes callable.
    ///         Returns 0 if the binding is not in FINALIZING state.
    function finalizeAfter(uint256 bindingId) external view returns (uint256) {
        Binding storage b = bindings[bindingId];
        if (b.state != BindingState.FINALIZING) return 0;
        return b.settleSubmittedAt + disputeWindow;
    }

    /// @notice Return the timestamp when the evidence window closes for a DISPUTED binding.
    function evidenceDeadline(uint256 bindingId) external view returns (uint256) {
        ArbitrationRecord storage arb = arbitrations[bindingId];
        if (arb.startedAt == 0) return 0;
        return arb.startedAt + evidenceWindow;
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  ADMIN
    // ─────────────────────────────────────────────────────────────────────────

    function setTokenAllowed(address token, bool allowed) external onlyAdmin {
        if (token == address(0)) revert ZeroAddress();
        tokenAllowed[token] = allowed;
        emit TokenAllowed(token, allowed);
    }

    function setBatchThreshold(address token, uint256 threshold) external onlyAdmin {
        batchThreshold[token] = threshold;
        emit BatchThresholdUpdated(token, threshold);
    }

    /// @notice Set minimum time after bind() before settle() can be called.
    function setDisputeWindow(uint256 seconds_) external onlyAdmin {
        disputeWindowSeconds = seconds_;
        emit DisputeWindowUpdated(seconds_);
    }

    /// @notice Set Layer 1 dispute window duration (after settle() submission).
    function setOptimisticDisputeWindow(uint256 seconds_) external onlyAdmin {
        disputeWindow = seconds_;
        emit OptimisticDisputeWindowUpdated(seconds_);
    }

    /// @notice Set arbitration evidence window duration.
    function setEvidenceWindow(uint256 seconds_) external onlyAdmin {
        evidenceWindow = seconds_;
        emit EvidenceWindowUpdated(seconds_);
    }

    /// @notice Set auto-arbitration threshold (pool value below which auto-resolve applies).
    function setAutoArbitrationThreshold(uint256 amount) external onlyAdmin {
        autoArbitrationThreshold = amount;
        emit AutoArbitrationThresholdUpdated(amount);
    }

    function setSettleTimeout(uint256 seconds_) external onlyAdmin {
        settleTimeoutSeconds = seconds_;
        emit SettleTimeoutUpdated(seconds_);
    }

    function setAttestationGateway(address gateway) external onlyAdmin {
        if (gateway == address(0)) revert InvalidAddress();
        attestationGateway = gateway;
        emit AttestationGatewayUpdated(gateway);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  INTERNAL — settlement execution helpers
    // ─────────────────────────────────────────────────────────────────────────

    /// @dev Finalize settlement: burn both bills, release USDC to each owner.
    function _executeSettle(
        uint256 bindingId,
        Binding storage b,
        BillToken storage buyerBill,
        BillToken storage agentBill,
        bytes32 proofHash
    ) internal {
        address token       = buyerBill.token;
        address buyerOwner  = buyerBill.owner;
        address agentOwner  = agentBill.owner;
        uint256 buyerAmount = buyerBill.amount;
        uint256 agentAmount = agentBill.amount;

        b.state     = BindingState.SETTLED;
        b.proofHash = proofHash;

        _decrementBound(buyerOwner, buyerAmount);
        _decrementBound(agentOwner, agentAmount);
        _burnBill(b.buyerBillId, buyerBill, "settled");
        _burnBill(b.agentBillId, agentBill, "settled");

        pendingBatchAmount[token] -= (buyerAmount + agentAmount);

        _transfer(token, buyerOwner, buyerAmount);
        _transfer(token, agentOwner, agentAmount);

        _checkInvariant(token);
        _checkPerAddressInvariant(buyerOwner);
        _checkPerAddressInvariant(agentOwner);

        emit SettleFinalized(bindingId, proofHash);
        emit BindingSettled(bindingId, proofHash, buyerAmount, agentAmount);
    }

    /// @dev Execute refund: burn both bills, return USDC to respective owners.
    function _executeRefund(
        uint256 bindingId,
        Binding storage b,
        BillToken storage buyerBill,
        BillToken storage agentBill
    ) internal {
        address token       = buyerBill.token;
        address buyerOwner  = buyerBill.owner;
        address agentOwner  = agentBill.owner;
        uint256 buyerAmount = buyerBill.amount;
        uint256 agentAmount = agentBill.amount;

        b.state = BindingState.REFUNDED;

        _decrementBound(buyerOwner, buyerAmount);
        _decrementBound(agentOwner, agentAmount);
        _burnBill(b.buyerBillId, buyerBill, "refunded");
        _burnBill(b.agentBillId, agentBill, "refunded");

        pendingBatchAmount[token] -= (buyerAmount + agentAmount);

        _transfer(token, buyerOwner, buyerAmount);
        _transfer(token, agentOwner, agentAmount);

        _checkInvariant(token);
        _checkPerAddressInvariant(buyerOwner);
        _checkPerAddressInvariant(agentOwner);
    }

    /// @dev Execute split: burn both bills, distribute combined pool by BPS.
    function _executeSplit(
        uint256 bindingId,
        Binding storage b,
        BillToken storage buyerBill,
        BillToken storage agentBill,
        uint256 buyerShareBps
    ) internal {
        address token       = buyerBill.token;
        address buyerOwner  = buyerBill.owner;
        address agentOwner  = agentBill.owner;
        uint256 totalPool   = buyerBill.amount + agentBill.amount;
        uint256 buyerPayout = (totalPool * buyerShareBps) / 10_000;
        uint256 agentPayout = totalPool - buyerPayout;

        b.state = BindingState.SETTLED;

        _decrementBound(buyerOwner, buyerBill.amount);
        _decrementBound(agentOwner, agentBill.amount);
        _burnBill(b.buyerBillId, buyerBill, "dispute-resolved");
        _burnBill(b.agentBillId, agentBill, "dispute-resolved");

        pendingBatchAmount[token] -= totalPool;

        if (buyerPayout > 0) _transfer(token, buyerOwner, buyerPayout);
        if (agentPayout > 0) _transfer(token, agentOwner, agentPayout);

        _checkInvariant(token);
        _checkPerAddressInvariant(buyerOwner);
        _checkPerAddressInvariant(agentOwner);

        emit DisputeResolved(bindingId, buyerShareBps);
        emit BindingSettled(bindingId, bytes32(0), buyerPayout, agentPayout);
    }

    // ─────────────────────────────────────────────────────────────────────────
    //  INTERNAL — invariant helpers
    // ─────────────────────────────────────────────────────────────────────────

    function _burnBill(uint256 billId, BillToken storage bill, string memory reason) internal {
        address token  = bill.token;
        uint256 amount = bill.amount;
        bill.state = BillState.BURNED;
        totalBillSupply[token] -= amount;
        totalLocked[token]     -= amount;
        emit BillBurned(billId, bill.owner, amount, reason);
    }

    function _transfer(address token, address to, uint256 amount) internal {
        bool ok = IERC20Min(token).transfer(to, amount);
        if (!ok) revert TransferFailed();
    }

    function _checkInvariant(address token) internal {
        uint256 supply = totalBillSupply[token];
        uint256 locked = totalLocked[token];
        if (supply != locked) revert InvariantBroken(token, supply, locked);
        emit InvariantChecked(token, supply, locked);
    }

    function _checkPerAddressInvariant(address addr) internal view {
        uint256 free   = freeBalance[addr];
        uint256 bound  = boundBalance[addr];
        uint256 minted = totalMintedByAddr[addr];
        if (free + bound != minted) revert PerAddressInvariantBroken(addr, free, bound, minted);
    }

    function _moveFreeTobound(address addr, uint256 amount) internal {
        if (freeBalance[addr] < amount) {
            revert InsufficientFreeBalance(addr, freeBalance[addr], amount);
        }
        freeBalance[addr]  -= amount;
        boundBalance[addr] += amount;
    }

    function _decrementBound(address addr, uint256 amount) internal {
        boundBalance[addr]      -= amount;
        totalMintedByAddr[addr] -= amount;
        totalLockedByAddr[addr] -= amount;
    }

    function _requireBill(uint256 billId) internal view returns (BillToken storage) {
        BillToken storage bill = bills[billId];
        if (bill.mintedAt == 0) revert BillNotMinted(billId);
        return bill;
    }

    function _requireBinding(uint256 bindingId) internal view returns (Binding storage) {
        Binding storage b = bindings[bindingId];
        if (b.createdAt == 0) revert BindingNotFound(bindingId);
        return b;
    }

    function _requireBillState(uint256 billId, BillState actual, BillState expected) internal pure {
        if (actual != expected) revert WrongBillState(billId, expected, actual);
    }

    function _requireAuth(uint256 authId) internal view returns (Authorization storage) {
        Authorization storage auth = authorizations[authId];
        if (auth.createdAt == 0) revert AuthorizationNotFound(authId);
        return auth;
    }

    function _requireIdentity(address addr) internal view returns (KarmaIdentity storage) {
        KarmaIdentity storage id = identities[addr];
        if (!id.registered) revert IdentityNotFound(addr);
        return id;
    }

    function _findActiveSubAgentId(address master, address subWallet)
        internal
        view
        returns (bytes32)
    {
        bytes32[] storage ids = _masterSubAgentIds[master];
        uint256 len = ids.length;
        for (uint256 i = 0; i < len; i++) {
            SubAgent storage sa = subAgentById[ids[i]];
            if (sa.subWallet == subWallet && sa.status == SubAgentStatus.ACTIVE) {
                return ids[i];
            }
        }
        revert SubAgentNotFound(subWallet);
    }
}
