// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IKYARegistry} from "../interfaces/IKYARegistry.sol";
import {Types} from "../libraries/Types.sol";
import {Errors} from "../libraries/Errors.sol";
import {Events} from "../libraries/Events.sol";

contract KYARegistry is IKYARegistry {
    address public immutable admin;
    mapping(address agent => Types.AgentDID) public didByAgent;
    uint256 public constant MIN_STAKE = 0.01 ether;
    bytes32 public constant DID_RENEW_SCOPE = keccak256("kya:did:renew");

    constructor() {
        admin = msg.sender;
    }

    function registerDID(address agent, bytes32 permissionsHash, uint256 validityDays)
        external
        payable
        override
        returns (bytes32 did)
    {
        if (agent == address(0)) revert Errors.InvalidAddress();
        if (msg.value < MIN_STAKE) revert Errors.InvalidAmount();
        if (validityDays == 0) revert Errors.InvalidAmount();
        Types.AgentDID memory existing = didByAgent[agent];
        if (existing.isActive && existing.validUntil >= block.timestamp) {
            if (existing.owner != msg.sender) revert Errors.Unauthorized();
            if (permissionsHash != existing.permissionsHash && permissionsHash != DID_RENEW_SCOPE) revert Errors.InvalidState();
        }

        uint256 validUntil = block.timestamp + (validityDays * 1 days);
        did = keccak256(abi.encodePacked(msg.sender, agent, block.timestamp, permissionsHash));

        didByAgent[agent] = Types.AgentDID({
            owner: msg.sender,
            agent: agent,
            registeredAt: block.timestamp,
            validUntil: validUntil,
            permissionsHash: permissionsHash,
            isActive: true
        });

        emit Events.DIDRegistered(did, agent, msg.sender, validUntil);
    }

    function revokeDID(address agent) external override {
        Types.AgentDID storage did = didByAgent[agent];
        if (did.owner != msg.sender) revert Errors.Unauthorized();
        if (!did.isActive) revert Errors.InvalidState();

        did.isActive = false;
        emit Events.DIDRevoked(agent, msg.sender);
    }

    function verifyDID(address agent) external view override returns (bool isValid, address owner, uint256 validUntil) {
        Types.AgentDID memory did = didByAgent[agent];
        isValid = did.isActive && did.validUntil >= block.timestamp;
        owner = did.owner;
        validUntil = did.validUntil;
    }

    function updatePermissions(address agent, bytes32 newPermissionsHash) external override {
        Types.AgentDID storage did = didByAgent[agent];
        if (did.owner != msg.sender) revert Errors.Unauthorized();
        if (!did.isActive) revert Errors.DIDNotActive();

        did.permissionsHash = newPermissionsHash;
        emit Events.PermissionUpdated(agent, newPermissionsHash);
    }

    function withdrawStuckETH(address to, uint256 amount) external override {
        if (msg.sender != admin) revert Errors.Unauthorized();
        if (to == address(0)) revert Errors.InvalidAddress();
        if (amount == 0 || amount > address(this).balance) revert Errors.InvalidAmount();
        (bool ok,) = payable(to).call{value: amount}("");
        if (!ok) revert Errors.InvalidState();
    }
}
