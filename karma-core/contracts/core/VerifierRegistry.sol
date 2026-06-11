// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title VerifierRegistry
/// @notice Manages the set of authorized verifier nodes in the Karma
///         decentralized verification layer. Only the admin can register
///         or remove verifiers and adjust threshold parameters.
/// @dev This is the canonical on-chain registry referenced by the
///      KarmaAttestationGateway for attestation quorum validation.

interface IStakingToken {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
}

contract VerifierRegistry {
    // ──────────────────────────────────── Errors ──────────────────────────────

    error Unauthorized();
    error VerifierAlreadyRegistered();
    error VerifierNotFound();
    error InvalidAddress();
    error InvalidThreshold();
    error ThresholdExceedsTotal();
    error InsufficientStake();
    error TransferFailed();
    error StakingTokenNotSet();

    // ──────────────────────────────── Immutables ─────────────────────────────

    /// @notice Admin address — the only account allowed to manage verifiers.
    address public immutable admin;

    // ──────────────────────────────── Storage ────────────────────────────────

    /// @notice Default N (required valid attestations).
    uint256 public defaultThreshold = 3;

    /// @notice Default M (total registered verifiers expected).
    uint256 public defaultTotalVerifiers = 5;

    /// @notice Per-verifier metadata.
    struct VerifierInfo {
        address wallet;
        string  endpointUrl;
        bool    active;
        uint256 stakeAmount;
        uint256 successCount;
        uint256 falseAttestationCount;
        uint256 totalEarnings;                   // accumulated verification rewards
        uint256 slashedAmount;                   // total amount slashed
    }

    /// @notice wallet → VerifierInfo lookup.
    mapping(address => VerifierInfo) public verifiers;

    /// @notice Ordered list of registered verifier wallets for enumeration.
    address[] public verifierList;

    /// @notice Staking token (e.g. KARMA token).
    address public stakingToken;

    /// @notice Minimum stake required to be an active verifier.
    uint256 public minStake;

    /// @notice Base reward per verified binding (in staking token).
    uint256 public verificationReward;

    // ──────────────────────────────── Events ─────────────────────────────────

    event VerifierRegistered(
        address indexed wallet,
        string endpointUrl,
        uint256 stakeAmount
    );

    event VerifierRemoved(address indexed wallet);

    event ThresholdsUpdated(
        uint256 newThreshold,
        uint256 newTotalVerifiers
    );

    event VerifierSuspended(address indexed wallet);
    event VerifierActivated(address indexed wallet);

    event AttestationRecorded(
        address indexed verifier,
        bool success
    );

    event VerifierStaked(address indexed verifier, uint256 amount, uint256 total);
    event VerifierUnstaked(address indexed verifier, uint256 amount, uint256 remaining);
    event VerifierSlashed(address indexed verifier, uint256 amount, string reason);
    event VerifierRewarded(address indexed verifier, uint256 amount);
    event StakingConfigUpdated(uint256 minStake, uint256 reward);

    // ──────────────────────────────── Constructor ────────────────────────────

    /// @param admin_ Address that can manage verifiers and thresholds.
    constructor(address admin_) {
        if (admin_ == address(0)) revert InvalidAddress();
        admin = admin_;
    }

    // ────────────────────────────── Admin Functions ──────────────────────────

    /// @notice Register a new verifier node.
    /// @param wallet Verifier's Ethereum address.
    /// @param endpointUrl Verifier's API endpoint for off-chain attestation.
    /// @param stakeAmount Optional initial stake (may be zero for testnet).
    function registerVerifier(
        address wallet,
        string calldata endpointUrl,
        uint256 stakeAmount
    ) external onlyAdmin {
        if (wallet == address(0)) revert InvalidAddress();
        if (verifiers[wallet].wallet != address(0)) revert VerifierAlreadyRegistered();

        verifiers[wallet] = VerifierInfo({
            wallet: wallet,
            endpointUrl: endpointUrl,
            active: true,
            stakeAmount: stakeAmount,
            successCount: 0,
            falseAttestationCount: 0,
            totalEarnings: 0,
            slashedAmount: 0
        });
        verifierList.push(wallet);

        emit VerifierRegistered(wallet, endpointUrl, stakeAmount);

        // Auto-bump totalVerifiers if exceeding current config.
        uint256 activeCount = _activeCount();
        if (activeCount > defaultTotalVerifiers) {
            defaultTotalVerifiers = activeCount;
            emit ThresholdsUpdated(defaultThreshold, defaultTotalVerifiers);
        }
    }

    /// @notice Remove a verifier from the active set.
    /// @param wallet Verifier address to remove.
    function removeVerifier(address wallet) external onlyAdmin {
        if (verifiers[wallet].wallet == address(0)) revert VerifierNotFound();
        delete verifiers[wallet];
        emit VerifierRemoved(wallet);
    }

    /// @notice Suspend a verifier without fully removing.
    /// @param wallet Verifier address to suspend.
    function suspendVerifier(address wallet) external onlyAdmin {
        if (verifiers[wallet].wallet == address(0)) revert VerifierNotFound();
        verifiers[wallet].active = false;
        emit VerifierSuspended(wallet);
    }

    /// @notice Re-activate a previously suspended verifier.
    /// @param wallet Verifier address to activate.
    function activateVerifier(address wallet) external onlyAdmin {
        if (verifiers[wallet].wallet == address(0)) revert VerifierNotFound();
        verifiers[wallet].active = true;
        emit VerifierActivated(wallet);
    }

    /// @notice Update the N-of-M threshold parameters.
    /// @param threshold Required number of valid attestations (N).
    /// @param totalVerifiers Total verifiers expected (M).
    function setThresholds(uint256 threshold, uint256 totalVerifiers) external onlyAdmin {
        if (threshold == 0 || totalVerifiers == 0) revert InvalidThreshold();
        if (threshold > totalVerifiers) revert ThresholdExceedsTotal();
        defaultThreshold = threshold;
        defaultTotalVerifiers = totalVerifiers;
        emit ThresholdsUpdated(threshold, totalVerifiers);
    }

    /// @notice Record an attestation result for a verifier (called by Gateway).
    /// @param verifier Verifier wallet address.
    /// @param success Whether the attestation was valid.
    function recordAttestation(address verifier, bool success) external {
        VerifierInfo storage v = verifiers[verifier];
        if (v.wallet == address(0)) revert VerifierNotFound();
        // In production this would be callable only by the Gateway contract.
        if (success) {
            v.successCount += 1;
        } else {
            v.falseAttestationCount += 1;
        }
        emit AttestationRecorded(verifier, success);
    }

    // ────────────────────────────── Views ──────────────────────────────────

    /// @notice Check if a wallet is an active verifier.
    function isActiveVerifier(address wallet) external view returns (bool) {
        return verifiers[wallet].wallet != address(0) && verifiers[wallet].active;
    }

    /// @notice Return the count of currently active verifiers.
    function getActiveVerifierCount() external view returns (uint256) {
        return _activeCount();
    }

    /// @notice Return the required attestation threshold.
    function getRequiredThreshold() external view returns (uint256) {
        return defaultThreshold;
    }

    /// @notice Return total verifiers configuration.
    function getTotalVerifiers() external view returns (uint256) {
        return defaultTotalVerifiers;
    }

    /// @notice Batch-check whether a list of wallets are active verifiers.
    /// @param wallets Array of wallet addresses to check.
    /// @return results Boolean array aligned with wallets.
    function areActiveVerifiers(address[] calldata wallets)
        external
        view
        returns (bool[] memory results)
    {
        results = new bool[](wallets.length);
        for (uint256 i = 0; i < wallets.length; i++) {
            VerifierInfo storage v = verifiers[wallets[i]];
            results[i] = v.wallet != address(0) && v.active;
        }
    }

    // ────────────────────── Staking / Slashing / Rewards ────────────────────

    /// @notice Set the staking token, minimum stake, and verification reward.
    function setStakingConfig(address token, uint256 minStake_, uint256 reward) external onlyAdmin {
        stakingToken = token;
        minStake = minStake_;
        verificationReward = reward;
        emit StakingConfigUpdated(minStake_, reward);
    }

    /// @notice Verifier stakes tokens to meet minimum requirement.
    function stake(uint256 amount) external {
        if (stakingToken == address(0)) revert StakingTokenNotSet();
        VerifierInfo storage v = verifiers[msg.sender];
        if (v.wallet == address(0)) revert VerifierNotFound();

        IStakingToken(stakingToken).transferFrom(msg.sender, address(this), amount);
        v.stakeAmount += amount;
        emit VerifierStaked(msg.sender, amount, v.stakeAmount);
    }

    /// @notice Verifier withdraws excess stake (must keep minStake).
    function unstake(uint256 amount) external {
        VerifierInfo storage v = verifiers[msg.sender];
        if (v.wallet == address(0)) revert VerifierNotFound();
        if (v.stakeAmount < amount + minStake) revert InsufficientStake();

        v.stakeAmount -= amount;
        IStakingToken(stakingToken).transfer(msg.sender, amount);
        emit VerifierUnstaked(msg.sender, amount, v.stakeAmount);
    }

    /// @notice Admin slashes a verifier for false attestation.
    /// @param verifier Verifier to penalize.
    /// @param amount    Amount to slash (transferred to protocol treasury).
    /// @param reason    Human-readable reason for the slash.
    function slash(address verifier, uint256 amount, string calldata reason) external onlyAdmin {
        VerifierInfo storage v = verifiers[verifier];
        if (v.wallet == address(0)) revert VerifierNotFound();
        if (amount > v.stakeAmount) amount = v.stakeAmount;

        v.stakeAmount -= amount;
        v.slashedAmount += amount;

        // If stake falls below minimum, deactivate
        if (v.stakeAmount < minStake) {
            v.active = false;
        }

        emit VerifierSlashed(verifier, amount, reason);
    }

    /// @notice Pay verification reward to verifier after successful attestation.
    function rewardVerifier(address verifier, uint256 amount) external {
        // In production, callable only by Gateway or KarmaBilateral
        VerifierInfo storage v = verifiers[verifier];
        if (v.wallet == address(0)) revert VerifierNotFound();

        if (amount > 0 && stakingToken != address(0)) {
            IStakingToken(stakingToken).transfer(verifier, amount);
            v.totalEarnings += amount;
        }
        emit VerifierRewarded(verifier, amount);
    }

    // ────────────────────────────── Internal ─────────────────────────────────

    function _activeCount() internal view returns (uint256 count) {
        for (uint256 i = 0; i < verifierList.length; i++) {
            if (verifiers[verifierList[i]].active) {
                count++;
            }
        }
    }

    // ────────────────────────────── Modifiers ────────────────────────────────

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }
}
