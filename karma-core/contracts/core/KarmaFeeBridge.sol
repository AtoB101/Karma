// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title KarmaFeeBridge
/// @notice Production fee collector for KarmaBilateral settlements.
/// @dev KarmaBilateral approves this contract for the quoted fee and calls
///      collectAndRecord(); this contract pulls the fee out of KarmaBilateral
///      and distributes it immediately. The settlement token is a single
///      configured asset (USDC), matching KarmaBilateral's per-binding flow.
///      Fee split is expressed in parts-per-ten (default 3/3/2/2):
///        treasury / verifier reward pool / token buyback / developer rewards.
interface IFeeBridgeToken {
    function transferFrom(address from, address to, uint256 amount) external returns (bool);
    function transfer(address to, uint256 amount) external returns (bool);
}

/// @notice Verifier reward pool (VerifierRegistry) reward-accounting hook.
interface IVerifierRewardPool {
    function creditRewards(uint256 amount) external;
}

contract KarmaFeeBridge {
    // Errors

    error Unauthorized();
    error InvalidAddress();
    error InvalidBps();
    error InvalidSplit();
    error TransferFailed();
    error FeeMismatch(uint256 expected, uint256 got);

    // Constants

    uint256 public constant BPS_DENOMINATOR = 10_000;

    /// @dev Hard cap on the fee rate (10%). Mirrors KarmaBilateral.MAX_FEE_BPS.
    uint256 public constant MAX_FEE_BPS = 1_000;

    // Immutables

    address public immutable admin;

    // Storage

    /// @notice Only this contract (KarmaBilateral) may call collectAndRecord.
    address public core;

    /// @notice Settlement token the fee is pulled in.
    address public token;

    /// @notice Fee rate in basis points. 50 == 0.5%.
    uint256 public feeBps = 50;

    /// @notice Split in parts-per-ten. Default 3/3/2/2 == 30/30/20/20%.
    uint256 public treasuryShare = 3;
    uint256 public verifierShare = 3;
    uint256 public buybackShare = 2;
    uint256 public developerShare = 2;

    /// @notice Destination addresses.
    address public treasury;
    address public verifierPool;
    address public buybackSink;
    address public developerDestination;

    /// @notice Cumulative accounting.
    uint256 public totalFeesCollected;
    uint256 public totalGmvRecorded;

    // Events

    event CoreUpdated(address indexed core);
    event TokenUpdated(address indexed token);
    event FeeBpsUpdated(uint256 feeBps);
    event SplitUpdated(uint256 treasuryShare, uint256 verifierShare, uint256 buybackShare, uint256 developerShare);
    event DestinationsUpdated(address treasury, address verifierPool, address buybackSink, address developerDestination);
    event FeeCollected(
        bytes32 indexed orderId,
        address indexed buyer,
        address indexed seller,
        address developer,
        uint256 amountUsdc,
        uint256 feeUsdc
    );

    // Constructor

    constructor(address admin_) {
        if (admin_ == address(0)) revert InvalidAddress();
        admin = admin_;
    }

    // Admin Wiring

    function setCore(address core_) external onlyAdmin {
        if (core_ == address(0)) revert InvalidAddress();
        core = core_;
        emit CoreUpdated(core_);
    }

    function setToken(address token_) external onlyAdmin {
        if (token_ == address(0)) revert InvalidAddress();
        token = token_;
        emit TokenUpdated(token_);
    }

    function setFeeBps(uint256 feeBps_) external onlyAdmin {
        if (feeBps_ > MAX_FEE_BPS) revert InvalidBps();
        feeBps = feeBps_;
        emit FeeBpsUpdated(feeBps_);
    }

    /// @notice Set the 3/3/2/2-style split. Parts must sum to exactly 10.
    function setSplit(uint256 treasury_, uint256 verifier_, uint256 buyback_, uint256 developer_)
        external
        onlyAdmin
    {
        if (treasury_ + verifier_ + buyback_ + developer_ != 10) revert InvalidSplit();
        treasuryShare = treasury_;
        verifierShare = verifier_;
        buybackShare = buyback_;
        developerShare = developer_;
        emit SplitUpdated(treasury_, verifier_, buyback_, developer_);
    }

    /// @notice Set all four destinations. None may be zero.
    function setDestinations(address treasury_, address verifierPool_, address buybackSink_, address developer_)
        external
        onlyAdmin
    {
        if (treasury_ == address(0) || verifierPool_ == address(0) ||
            buybackSink_ == address(0) || developer_ == address(0)) revert InvalidAddress();
        treasury = treasury_;
        verifierPool = verifierPool_;
        buybackSink = buybackSink_;
        developerDestination = developer_;
        emit DestinationsUpdated(treasury_, verifierPool_, buybackSink_, developer_);
    }

    /// @notice Rescue tokens accidentally sent directly to the bridge.
    function rescueTokens(address token_, address to, uint256 amount) external onlyAdmin {
        if (token_ == address(0) || to == address(0)) revert InvalidAddress();
        if (!IFeeBridgeToken(token_).transfer(to, amount)) revert TransferFailed();
    }

    // Fee Collection

    /// @notice Quote the fee for a settlement amount, in the settlement token.
    function quoteFee(address, uint256 amountUsdc) external view returns (uint256) {
        return (amountUsdc * feeBps) / BPS_DENOMINATOR;
    }

    /// @notice Called by KarmaBilateral to collect the fee and record GMV.
    function collectAndRecord(
        bytes32 orderId,
        address buyer,
        address seller,
        address developer,
        uint256 amountUsdc,
        uint256 feeUsdc
    ) external {
        if (msg.sender != core) revert Unauthorized();

        uint256 expected = (amountUsdc * feeBps) / BPS_DENOMINATOR;
        if (feeUsdc != expected) revert FeeMismatch(expected, feeUsdc);

        if (feeUsdc > 0) {
            if (!IFeeBridgeToken(token).transferFrom(core, address(this), feeUsdc)) revert TransferFailed();
            _distribute(feeUsdc);
        }

        totalGmvRecorded += amountUsdc;
        totalFeesCollected += feeUsdc;
        emit FeeCollected(orderId, buyer, seller, developer, amountUsdc, feeUsdc);
    }

    // Internal

    function _distribute(uint256 fee) internal {
        uint256 totalParts = treasuryShare + verifierShare + buybackShare + developerShare;
        if (totalParts == 0 || fee == 0) return;

        uint256 treasuryAmt  = (fee * treasuryShare) / totalParts;
        uint256 verifierAmt  = (fee * verifierShare) / totalParts;
        uint256 buybackAmt   = (fee * buybackShare) / totalParts;
        uint256 developerAmt = fee - treasuryAmt - verifierAmt - buybackAmt;

        if (treasuryAmt > 0) _transferOut(treasury, treasuryAmt);
        if (verifierAmt > 0) {
            _transferOut(verifierPool, verifierAmt);
            _creditVerifierRewards(verifierPool, verifierAmt);
        }
        if (buybackAmt > 0) _transferOut(buybackSink, buybackAmt);
        if (developerAmt > 0) _transferOut(developerDestination, developerAmt);
    }

    /// @dev Best-effort reward accounting: the VerifierRegistry exposes
    ///      creditRewards() so verifier payouts draw from a dedicated pool.
    ///      A non-registry verifierPool simply receives the tokens without
    ///      reward accounting (call failure is ignored).
    function _creditVerifierRewards(address pool, uint256 amount) internal {
        (bool ok, ) = pool.call(abi.encodeWithSelector(IVerifierRewardPool.creditRewards.selector, amount));
        if (!ok) {
            // verifierPool does not implement reward accounting.
        }
    }

    function _transferOut(address to, uint256 amount) internal {
        if (to == address(0)) revert InvalidAddress();
        if (!IFeeBridgeToken(token).transfer(to, amount)) revert TransferFailed();
    }

    // Modifiers

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }
}
