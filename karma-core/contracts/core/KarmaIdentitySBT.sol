// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

/// @title KarmaIdentitySBT — P0 non-transferable identity anchor (FINAL V1.0 KarmaIdentitySBT mapping).
/// @notice Soulbound by construction: no transfer API; one soul id per owner wallet.
contract KarmaIdentitySBT {
    address public immutable admin;

    mapping(address owner => uint256 soulId) public soulByOwner;
    mapping(uint256 soulId => address owner) public ownerBySoul;
    uint256 public nextSoulId = 1;

    error Unauthorized();

    event SoulMinted(address indexed owner, uint256 indexed soulId);

    constructor() {
        admin = msg.sender;
    }

    /// @notice Mint the first soul for `owner`, or return the existing id. Callable by admin or `owner`.
    function mintOrGet(address owner) external returns (uint256 soulId) {
        if (msg.sender != admin && msg.sender != owner) revert Unauthorized();
        soulId = soulByOwner[owner];
        if (soulId != 0) return soulId;
        soulId = nextSoulId++;
        soulByOwner[owner] = soulId;
        ownerBySoul[soulId] = owner;
        emit SoulMinted(owner, soulId);
    }

    function ownerOf(uint256 soulId) external view returns (address) {
        return ownerBySoul[soulId];
    }
}
