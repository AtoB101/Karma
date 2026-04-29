// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IKYARegistry {
    function registerDID(address agent, bytes32 permissionsHash, uint256 validityDays) external payable returns (bytes32 did);
    function revokeDID(address agent) external;
    function verifyDID(address agent) external view returns (bool isValid, address owner, uint256 validUntil);
    function updatePermissions(address agent, bytes32 newPermissionsHash) external;
    function withdrawStuckETH(address to, uint256 amount) external;
}
