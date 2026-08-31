// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title KarmaReputationAnchor
/// @notice Packs off-chain undisputed (or rehabilitated) reputation onto chain.
///         Non-transferable. Does not waive Bilateral fees. High packed scores
///         mint non-transferable reward weight for platform dividends.
contract KarmaReputationAnchor {
    error Unauthorized();
    error ZeroAddress();
    error ScoreTooLow();
    error AlreadyPackedNewer();
    error NotPacked();

    uint256 public constant REHAB_WINDOW = 90 days;
    /// @dev Off-chain score uses 0–1000. Packed as score * 100 (e.g. 200.00 → 20000).
    uint256 public constant PACK_MIN_SCORE_E2 = 20_000;
    uint256 public constant DIVIDEND_MIN_SCORE_E2 = 30_000;

    address public immutable admin;
    address public packer;

    struct Packed {
        uint256 scoreE2;
        uint256 packedAt;
        uint256 successCount;
        bytes32 evidenceHash;
        uint256 lastSlashAt;
        bytes32 lastSlashKind;
        uint256 rewardWeight;
        bool packed;
    }

    mapping(address => Packed) public packedOf;
    uint256 public totalRewardWeight;

    event PackerUpdated(address indexed packer);
    event ReputationPacked(
        address indexed party,
        uint256 scoreE2,
        uint256 successCount,
        bytes32 evidenceHash,
        uint256 rewardWeight
    );
    event ReputationSlashed(address indexed party, uint256 scoreE2, bytes32 kind);
    event RewardWeightFrozen(address indexed party, uint256 untilTs);

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyPacker() {
        if (msg.sender != packer && msg.sender != admin) revert Unauthorized();
        _;
    }

    constructor(address admin_) {
        if (admin_ == address(0)) revert ZeroAddress();
        admin = admin_;
        packer = admin_;
    }

    function setPacker(address packer_) external onlyAdmin {
        if (packer_ == address(0)) revert ZeroAddress();
        packer = packer_;
        emit PackerUpdated(packer_);
    }

    /// @notice Anchor an off-chain score. Caller (packer) must have enforced
    ///         undisputed-or-90-day-rehab eligibility off-chain.
    function pack(
        address party,
        uint256 scoreE2,
        uint256 successCount,
        bytes32 evidenceHash
    ) external onlyPacker {
        if (party == address(0)) revert ZeroAddress();
        if (scoreE2 < PACK_MIN_SCORE_E2) revert ScoreTooLow();

        Packed storage p = packedOf[party];
        if (p.packed && scoreE2 < p.scoreE2 && p.lastSlashAt == 0) {
            revert AlreadyPackedNewer();
        }

        uint256 minted;
        if (scoreE2 >= DIVIDEND_MIN_SCORE_E2) {
            uint256 add = scoreE2 / 100;
            if (p.lastSlashAt != 0 && block.timestamp < p.lastSlashAt + REHAB_WINDOW) {
                add = 0;
            } else {
                p.rewardWeight += add;
                totalRewardWeight += add;
                minted = add;
            }
        }

        p.scoreE2 = scoreE2;
        p.packedAt = block.timestamp;
        p.successCount = successCount;
        p.evidenceHash = evidenceHash;
        p.packed = true;

        emit ReputationPacked(party, scoreE2, successCount, evidenceHash, minted);
    }

    /// @notice On-chain mark for default/fraud. Score may still be re-packed after rehab.
    function slash(address party, uint256 newScoreE2, bytes32 kind) external onlyPacker {
        Packed storage p = packedOf[party];
        if (!p.packed) revert NotPacked();
        p.scoreE2 = newScoreE2;
        p.lastSlashAt = block.timestamp;
        p.lastSlashKind = kind;
        emit ReputationSlashed(party, newScoreE2, kind);
        emit RewardWeightFrozen(party, block.timestamp + REHAB_WINDOW);
    }

    function isPacked(address party) external view returns (bool) {
        return packedOf[party].packed;
    }

    /// @notice Dividend eligibility is independent of fee waivers (fees stay on FeeBridge).
    function isDividendEligible(address party) external view returns (bool) {
        Packed memory p = packedOf[party];
        if (!p.packed || p.scoreE2 < DIVIDEND_MIN_SCORE_E2) return false;
        if (p.lastSlashAt == 0) return true;
        return block.timestamp >= p.lastSlashAt + REHAB_WINDOW;
    }
}
