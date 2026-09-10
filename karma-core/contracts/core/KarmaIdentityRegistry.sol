// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @notice Master identity + up to 3 active on-chain SubAgents.
///         Split out of KarmaBilateral to keep the settlement core under EIP-170.
interface IKarmaBilateralBalances {
    function boundBalance(address addr) external view returns (uint256);
    function freeBalance(address addr) external view returns (uint256);
}

contract KarmaIdentityRegistry {
    error IdentityAlreadyRegistered(address addr);
    error IdentityNotFound(address addr);
    error SubAgentLimitReached(address master);
    error SubAgentAlreadyAdded(address sub);
    error AllowanceExceedsFreeBalance(uint256 total, uint256 free);
    error SubAgentNotFound(address sub);
    error SubAgentHasBoundBalance(address sub, uint256 bound);
    error ZeroAddress();
    error ZeroAmount();

    /// @dev Settlement core queried for bound/free balances during sub-agent checks.
    address public immutable bilateral;

    enum SubAgentStatus { ACTIVE, INACTIVE }

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

    mapping(address => KarmaIdentity) public identities;
    mapping(address => bytes32[])     private _masterSubAgentIds;
    mapping(bytes32 => SubAgent)      public subAgentById;
    mapping(address => address)       public subAgentMaster;
    mapping(address => uint8)         public activeSubAgents;

    event IdentityRegistered(address indexed masterWallet, bytes32 masterAgentId);
    event SubAgentAdded(address indexed masterWallet, address indexed subWallet, bytes32 subAgentId);
    event SubAgentDeactivated(address indexed masterWallet, address indexed subWallet, bytes32 subAgentId);
    event SubAgentAllowanceUpdated(address indexed masterWallet, address indexed subWallet, uint256 allowance);

    constructor(address bilateral_) {
        bilateral = bilateral_;
    }

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

        uint256 bound = IKarmaBilateralBalances(bilateral).boundBalance(subWallet);
        if (bound != 0) {
            revert SubAgentHasBoundBalance(subWallet, bound);
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
        uint256 free = IKarmaBilateralBalances(bilateral).freeBalance(msg.sender);
        if (totalAllowance > free) {
            revert AllowanceExceedsFreeBalance(totalAllowance, free);
        }
        emit SubAgentAllowanceUpdated(msg.sender, subWallet, allowance);
    }

    // ── View getters ────────────────────────────────────────────────────────

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

    // ── Internal helpers ────────────────────────────────────────────────────

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
