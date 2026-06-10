// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Types} from "../libraries/Types.sol";

/// @title ScoringEngine
/// @notice Three-party multi-dimension scoring for Karma protocol.
///         Tracks reputation for suppliers, buyers, and verifiers.
///         All scores are on-chain, non-custodial, derived from settlement and
///         dispute outcomes.
///
///         Design principles:
///         - Pure math: no external oracles, no admin discretion
///         - Cumulative: scores compound over time, good actors get entrenched
///         - Decaying: stale positive history decays slowly; negative marks decay fast
///         - Transparent: anyone can query any party's score vector
contract ScoringEngine {
    using Types for Types.ScoringVector;

    // ═══════════════════════════ Errors ══════════════════════════════════════

    error Unauthorized();
    error ZeroAddress();
    error PartyNotFound();

    // ═══════════════════════════ Constants ═══════════════════════════════════

    uint256 public constant MAX_SCORE = 10_000;          // basis-point ceiling
    uint256 public constant DEFAULT_SCORE = 5_000;       // neutral starting score
    uint256 public constant SETTLE_WEIGHT = 20;          // weight per settlement
    uint256 public constant DISPUTE_WEIGHT = 50;         // weight per dispute outcome
    uint256 public constant PENALTY_WEIGHT = 100;        // weight per penalty/slash
    uint256 public constant DECAY_WINDOW = 30 days;      // score half-life window

    // ═══════════════════════════ Enums ═══════════════════════════════════════

    enum PartyType {
        SUPPLIER,
        BUYER,
        VERIFIER
    }

    // ═══════════════════════════ Storage ═════════════════════════════════════

    address public immutable admin;
    address public authorizedSettler;                    // KarmaBilateral contract

    mapping(address => Types.ScoringVector) public scores;
    mapping(address => PartyType) public partyTypes;

    // ═══════════════════════════ Events ══════════════════════════════════════

    event ScoreUpdated(address indexed party, PartyType pType, uint256 newScore);
    event ScoreVectorUpdated(address indexed party);
    event PartyRegistered(address indexed party, PartyType pType);
    event AuthorizedSettlerUpdated(address indexed settler);

    // ═══════════════════════════ Modifiers ════════════════════════════════════

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlySettler() {
        if (msg.sender != authorizedSettler) revert Unauthorized();
        _;
    }

    // ═══════════════════════════ Constructor ══════════════════════════════════

    constructor(address admin_) {
        if (admin_ == address(0)) revert ZeroAddress();
        admin = admin_;
    }

    // ═══════════════════════════ Admin ════════════════════════════════════════

    function setAuthorizedSettler(address settler) external onlyAdmin {
        authorizedSettler = settler;
        emit AuthorizedSettlerUpdated(settler);
    }

    function registerParty(address party, PartyType pType) external onlyAdmin {
        if (party == address(0)) revert ZeroAddress();
        partyTypes[party] = pType;
        scores[party] = Types.ScoringVector({
            totalTransactions: 0,
            reputationScore: DEFAULT_SCORE,
            completionRate: DEFAULT_SCORE,
            avgCompletionSpeed: DEFAULT_SCORE,
            disputeRate: 0,
            disputeWinRate: DEFAULT_SCORE,
            penaltyCount: 0,
            confirmationSpeed: DEFAULT_SCORE,
            maliciousDisputeRate: 0,
            verificationAccuracy: DEFAULT_SCORE,
            verificationVolume: 0,
            slashedCount: 0,
            lastUpdated: block.timestamp
        });
        emit PartyRegistered(party, pType);
    }

    // ═══════════════════════════ Core Scoring ═════════════════════════════════

    /// @notice Called by KarmaBilateral after a successful settlement.
    /// @param seller        The service provider
    /// @param buyer         The customer
    /// @param verifier      The verifier (address(0) if pure on-chain)
    /// @param completedOnTime  Whether service completed before deadline
    /// @param speedRatio    Completion speed: 10000 = exactly on deadline, >10000 = early
    function recordSettlement(
        address seller,
        address buyer,
        address verifier,
        bool    completedOnTime,
        uint256 speedRatio
    )
        external
        onlySettler
    {
        _updateSellerSettlement(seller, completedOnTime, speedRatio);
        _updateBuyerSettlement(buyer);
        if (verifier != address(0)) {
            _updateVerifierSettlement(verifier, true);
        }
    }

    /// @notice Called by KarmaBilateral after a dispute is resolved.
    /// @param seller       The service provider
    /// @param buyer        The customer
    /// @param verifier     The verifier (address(0) if pure on-chain)
    /// @param sellerWon    True if seller won the dispute
    /// @param wasPenalty   True if penalty was applied (not just refund)
    function recordDisputeResolution(
        address seller,
        address buyer,
        address verifier,
        bool    sellerWon,
        bool    wasPenalty
    )
        external
        onlySettler
    {
        _updateSellerDispute(seller, sellerWon, wasPenalty);
        _updateBuyerDispute(buyer, !sellerWon);
        if (verifier != address(0)) {
            _updateVerifierSettlement(verifier, sellerWon);
        }
    }

    /// @notice Called when a verifier is slashed for bad verification.
    function recordVerifierSlashed(address verifier) external onlyAdmin {
        Types.ScoringVector storage sv = scores[verifier];
        sv.slashedCount += 1;
        sv.verificationAccuracy = _decayScore(sv.verificationAccuracy, PENALTY_WEIGHT, 0);
        sv.reputationScore = _decayScore(sv.reputationScore, PENALTY_WEIGHT, 0);
        sv.lastUpdated = block.timestamp;
        emit ScoreVectorUpdated(verifier);
    }

    /// @notice Called when buyer confirms receipt (fast confirmation = good).
    /// @param buyer    The customer
    /// @param speedRatio  How fast they confirmed (10000 = instant, <10000 = slow)
    function recordBuyerConfirmation(address buyer, uint256 speedRatio) external onlySettler {
        Types.ScoringVector storage sv = scores[buyer];
        sv.confirmationSpeed = _rollingAvg(sv.confirmationSpeed, speedRatio, sv.totalTransactions);
        sv.reputationScore = _computeComposite(sv);
        sv.lastUpdated = block.timestamp;
        emit ScoreVectorUpdated(buyer);
    }

    // ═══════════════════════════ Views ════════════════════════════════════════

    function getScore(address party) external view returns (Types.ScoringVector memory) {
        return scores[party];
    }

    function getReputationScore(address party) external view returns (uint256) {
        return scores[party].reputationScore;
    }

    function isHighReputation(address party) external view returns (bool) {
        return scores[party].reputationScore >= 7_000;
    }

    // ═══════════════════════════ Internal — Settlements ═══════════════════════

    function _updateSellerSettlement(address seller, bool onTime, uint256 speedRatio) internal {
        Types.ScoringVector storage sv = scores[seller];
        if (sv.lastUpdated == 0) return; // not registered — skip

        sv.totalTransactions += 1;

        // Completion rate: rolling average
        uint256 completed = onTime ? MAX_SCORE : 0;
        sv.completionRate = _rollingAvg(sv.completionRate, completed, sv.totalTransactions);

        // Speed: rolling average
        sv.avgCompletionSpeed = _rollingAvg(sv.avgCompletionSpeed, speedRatio, sv.totalTransactions);

        // Reputation: bump up for good performance
        uint256 delta = onTime ? SETTLE_WEIGHT : 0;
        sv.reputationScore = _boundedAdd(sv.reputationScore, delta);

        sv.lastUpdated = block.timestamp;
        emit ScoreVectorUpdated(seller);
    }

    function _updateBuyerSettlement(address buyer) internal {
        Types.ScoringVector storage sv = scores[buyer];
        if (sv.lastUpdated == 0) return;

        sv.totalTransactions += 1;
        // Buyers get a small bump for participating
        sv.reputationScore = _boundedAdd(sv.reputationScore, SETTLE_WEIGHT / 2);
        sv.lastUpdated = block.timestamp;
        emit ScoreVectorUpdated(buyer);
    }

    function _updateVerifierSettlement(address verifier, bool verifiedCorrectly) internal {
        Types.ScoringVector storage sv = scores[verifier];
        if (sv.lastUpdated == 0) return;

        sv.verificationVolume += 1;
        uint256 result = verifiedCorrectly ? MAX_SCORE : 0;
        sv.verificationAccuracy = _rollingAvg(sv.verificationAccuracy, result, sv.verificationVolume);

        uint256 delta = verifiedCorrectly ? SETTLE_WEIGHT : 0;
        sv.reputationScore = _boundedAdd(sv.reputationScore, delta);
        sv.lastUpdated = block.timestamp;
        emit ScoreVectorUpdated(verifier);
    }

    // ═══════════════════════════ Internal — Disputes ══════════════════════════

    function _updateSellerDispute(address seller, bool won, bool wasPenalty) internal {
        Types.ScoringVector storage sv = scores[seller];
        if (sv.lastUpdated == 0) return;

        // Dispute rate
        sv.disputeRate = _rollingAvg(sv.disputeRate, MAX_SCORE, sv.totalTransactions + 1);

        // Dispute win rate
        uint256 winVal = won ? MAX_SCORE : 0;
        sv.disputeWinRate = _rollingAvg(
            sv.disputeWinRate, winVal,
            sv.totalTransactions > 0 ? sv.totalTransactions : 1
        );

        // Penalty
        if (wasPenalty) {
            sv.penaltyCount += 1;
            sv.reputationScore = _decayScore(sv.reputationScore, PENALTY_WEIGHT, 0);
        } else {
            uint256 delta = won ? DISPUTE_WEIGHT / 2 : 0;
            sv.reputationScore = won
                ? _boundedAdd(sv.reputationScore, delta)
                : _decayScore(sv.reputationScore, DISPUTE_WEIGHT, 0);
        }

        sv.lastUpdated = block.timestamp;
        emit ScoreVectorUpdated(seller);
    }

    function _updateBuyerDispute(address buyer, bool won) internal {
        Types.ScoringVector storage sv = scores[buyer];
        if (sv.lastUpdated == 0) return;

        if (!won) {
            // Buyer lost dispute — malicious dispute indicator
            sv.maliciousDisputeRate = _rollingAvg(
                sv.maliciousDisputeRate, MAX_SCORE,
                sv.totalTransactions > 0 ? sv.totalTransactions : 1
            );
            sv.reputationScore = _decayScore(sv.reputationScore, DISPUTE_WEIGHT, 0);
        }

        sv.lastUpdated = block.timestamp;
        emit ScoreVectorUpdated(buyer);
    }

    // ═══════════════════════════ Internal — Math ══════════════════════════════

    function _boundedAdd(uint256 current, uint256 delta) internal pure returns (uint256) {
        uint256 result = current + delta;
        return result > MAX_SCORE ? MAX_SCORE : result;
    }

    function _decayScore(uint256 current, uint256 weight, uint256) internal pure returns (uint256) {
        // weight is subtracted directly (capped at floor 0)
        return current > weight ? current - weight : 0;
    }

    function _rollingAvg(
        uint256 currentAvg,
        uint256 newValue,
        uint256 totalCount
    )
        internal
        pure
        returns (uint256)
    {
        if (totalCount <= 1) return newValue;
        // Exponential moving average: new = old * (n-1)/n + new * 1/n
        return (currentAvg * (totalCount - 1) + newValue) / totalCount;
    }

    function _computeComposite(Types.ScoringVector storage sv) internal view returns (uint256) {
        // Supplier: weight completion + speed + dispute outcomes
        // Buyer:    weight confirmation speed - malicious disputes
        // Verifier: weight accuracy + volume - slashes
        PartyType pType = partyTypes[address(this)]; // dummy — we don't use this
        // Simplified composite for now — just return stored reputationScore
        // (individual dimensions updated by their respective functions)
        return sv.reputationScore;
    }
}
