// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ICircuitBreaker} from "../interfaces/ICircuitBreaker.sol";
import {Errors} from "../libraries/Errors.sol";
import {Events} from "../libraries/Events.sol";

contract CircuitBreaker is ICircuitBreaker {
    address public immutable admin;
    bool public globalPaused;

    mapping(address owner => uint256 threshold) public humanApprovalThreshold;
    mapping(address agent => bool paused) public agentPaused;

    constructor(address admin_) {
        if (admin_ == address(0)) revert Errors.InvalidAddress();
        admin = admin_;
    }

    function setHumanApprovalThreshold(uint256 amount) external override {
        if (amount == 0) revert Errors.InvalidAmount();
        humanApprovalThreshold[msg.sender] = amount;
        emit Events.HumanApprovalThresholdUpdated(msg.sender, amount);
    }

    function pauseAgent(address agent, string calldata reason) external override onlyAdmin {
        if (agent == address(0)) revert Errors.InvalidAddress();

        agentPaused[agent] = true;
        emit Events.AgentPaused(agent, reason);
    }

    function resumeAgent(address agent) external override onlyAdmin {
        if (agent == address(0)) revert Errors.InvalidAddress();

        agentPaused[agent] = false;
        emit Events.AgentResumed(agent);
    }

    function emergencyPause(string calldata reason) external override onlyAdmin {
        globalPaused = true;
        emit Events.GlobalCircuitBreakerTriggered(msg.sender, reason);
    }

    function emergencyResume() external override onlyAdmin {
        globalPaused = false;
        emit Events.GlobalCircuitBreakerResumed(msg.sender);
    }

    function isGlobalPaused() external view override returns (bool) {
        return globalPaused;
    }

    function isAgentPaused(address agent) external view override returns (bool) {
        return agentPaused[agent];
    }

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Errors.Unauthorized();
        _;
    }
}
