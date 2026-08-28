// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface IEmergencyFreeze {
    function payoutBlocked(
        uint256 bindingId,
        uint256 buyerBillId,
        uint256 agentBillId,
        address buyerOwner,
        address agentOwner
    ) external view returns (bool blocked, uint8 scope, uint256 until);

    function bindBlocked(
        address buyerOwner,
        address agentOwner,
        uint256 buyerBillId,
        uint256 agentBillId
    ) external view returns (bool blocked, uint8 scope, uint256 until);

    function isGlobalFrozen() external view returns (bool);
}
