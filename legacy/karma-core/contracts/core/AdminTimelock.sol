// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title  AdminTimelock
/// @notice Multisig-governed timelock that acts as the `admin` of Karma core
///         contracts. N-of-M owners propose and approve actions; an approved
///         action becomes executable only after `minDelay`. This replaces the
///         single-EOA admin so no one key can alter protocol parameters without
///         multisig consent and a mandatory delay.
contract AdminTimelock {
    struct Action {
        address target;
        uint256 value;
        bytes   data;
        uint256 eta;        // executable after this timestamp; 0 = never scheduled
        uint256 approvals;  // current approval count
        bool    executed;
    }

    address[] public owners;
    mapping(address => bool) public isOwner;
    uint256 public threshold;
    uint256 public minDelay;

    uint256 public constant MAX_DELAY = 30 days;

    uint256 public nonce;
    bytes32[] public actionIds;
    mapping(bytes32 => Action) public actions;
    mapping(bytes32 => mapping(address => bool)) public approvedBy;

    error NotOwner();
    error ZeroAddress();
    error InvalidConfig();
    error UnknownAction();
    error NotReady(uint256 eta);
    error AlreadyExecuted();
    error AlreadyApproved();
    error NotApproved(uint256 required, uint256 have);
    error DelayTooLarge(uint256 delay);
    error CallFailed(bytes reason);

    event OwnerSetUpdated(address[] owners, uint256 threshold);
    event MinDelayUpdated(uint256 minDelay);
    event Scheduled(bytes32 indexed id, address indexed target, uint256 value, uint256 eta, bytes data);
    event Approved(bytes32 indexed id, address indexed owner);
    event Executed(bytes32 indexed id, address indexed target);
    event Cancelled(bytes32 indexed id);

    constructor(address[] memory owners_, uint256 threshold_, uint256 minDelay_) {
        _setOwnerSet(owners_, threshold_);
        _setMinDelay(minDelay_);
    }

    modifier onlyOwner() {
        if (!isOwner[msg.sender]) revert NotOwner();
        _;
    }

    modifier onlySelf() {
        if (msg.sender != address(this)) revert NotOwner();
        _;
    }

    // ── Propose / approve / execute / cancel ─────────────────────────────────

    /// @notice Schedule an action and self-approve it. Only an owner may propose.
    function schedule(address target, uint256 value, bytes calldata data)
        external
        onlyOwner
        returns (bytes32 id)
    {
        if (target == address(0)) revert ZeroAddress();

        uint256 n = nonce++;
        id = keccak256(abi.encode(target, value, data, block.chainid, address(this), n));

        Action storage a = actions[id];
        a.target = target;
        a.value = value;
        a.data = data;
        a.eta = block.timestamp + minDelay;
        a.approvals = 1;
        approvedBy[id][msg.sender] = true;
        actionIds.push(id);

        emit Scheduled(id, target, value, a.eta, data);
    }

    /// @notice Add an owner approval to a pending action.
    function approve(bytes32 id) external onlyOwner {
        Action storage a = actions[id];
        if (a.eta == 0) revert UnknownAction();
        if (a.executed) revert AlreadyExecuted();
        if (approvedBy[id][msg.sender]) revert AlreadyApproved();

        approvedBy[id][msg.sender] = true;
        a.approvals += 1;

        emit Approved(id, msg.sender);
    }

    /// @notice Execute a ready, threshold-approved action. Permissionless.
    function execute(bytes32 id) external returns (bytes memory result) {
        Action storage a = actions[id];
        if (a.eta == 0) revert UnknownAction();
        if (a.executed) revert AlreadyExecuted();
        if (block.timestamp < a.eta) revert NotReady(a.eta);
        if (a.approvals < threshold) revert NotApproved(threshold, a.approvals);

        a.executed = true;

        (bool ok, bytes memory ret) = a.target.call{value: a.value}(a.data);
        if (!ok) revert CallFailed(ret);

        emit Executed(id, a.target);
        return ret;
    }

    /// @notice Cancel a pending action. Requires a threshold of owners.
    function cancel(bytes32 id) external onlyOwner {
        Action storage a = actions[id];
        if (a.eta == 0) revert UnknownAction();
        if (a.executed) revert AlreadyExecuted();
        if (a.approvals < threshold) revert NotApproved(threshold, a.approvals);

        delete actions[id];
        emit Cancelled(id);
    }

    // ── Self-governance (callable only by the timelock itself) ──────────────

    /// @notice Replace the owner set and threshold. Must go through the timelock.
    function setOwners(address[] calldata newOwners, uint256 newThreshold) external onlySelf {
        address[] memory m = newOwners;
        _setOwnerSet(m, newThreshold);
    }

    /// @notice Change the minimum delay. Must go through the timelock.
    function setMinDelay(uint256 newMinDelay) external onlySelf {
        _setMinDelay(newMinDelay);
    }

    /// @notice Atomically reconfigure owners, threshold and delay (deploy helper).
    function reconfigure(
        address[] calldata newOwners,
        uint256 newThreshold,
        uint256 newMinDelay
    ) external onlySelf {
        _setMinDelay(newMinDelay);
        address[] memory m = newOwners;
        _setOwnerSet(m, newThreshold);
    }

    // ── Internal ─────────────────────────────────────────────────────────────

    function _setOwnerSet(address[] memory newOwners, uint256 newThreshold) internal {
        uint256 n = newOwners.length;
        if (n == 0 || newThreshold == 0 || newThreshold > n) revert InvalidConfig();

        for (uint256 i = 0; i < owners.length; i++) {
            isOwner[owners[i]] = false;
        }
        delete owners;

        for (uint256 i = 0; i < n; i++) {
            address o = newOwners[i];
            if (o == address(0) || isOwner[o]) revert InvalidConfig();
            isOwner[o] = true;
            owners.push(o);
        }
        threshold = newThreshold;

        emit OwnerSetUpdated(newOwners, newThreshold);
    }

    function _setMinDelay(uint256 newMinDelay) internal {
        if (newMinDelay > MAX_DELAY) revert DelayTooLarge(newMinDelay);
        minDelay = newMinDelay;
        emit MinDelayUpdated(newMinDelay);
    }

    /// @notice Convenience view: current owner count.
    function ownerCount() external view returns (uint256) {
        return owners.length;
    }
}
