// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ICircuitBreaker} from "../interfaces/ICircuitBreaker.sol";
import {Errors} from "../libraries/Errors.sol";
import {Events} from "../libraries/Events.sol";

contract CircuitBreaker is ICircuitBreaker {
    /// @notice Maximum per-owner threshold; aligns with Karma2 hardened deployment.
    uint256 public constant MAX_THRESHOLD = uint256(type(uint128).max);

    /// @notice Minimum delay between requesting and executing an emergency resume.
    uint256 public constant EMERGENCY_RESUME_DELAY = 24 hours;

    address public immutable admin;
    bool public globalPaused;
    /// @notice Timestamp when emergency resume was requested (0 = not requested).
    uint256 public emergencyResumeRequestedAt;

    mapping(address owner => uint256 threshold) public humanApprovalThreshold;
    mapping(address agent => bool paused) public agentPaused;

    constructor(address admin_) {
        if (admin_ == address(0)) revert Errors.InvalidAddress();
        admin = admin_;
    }

    function setHumanApprovalThreshold(uint256 amount) external override {
        if (amount == 0) revert Errors.InvalidAmount();
        if (amount > MAX_THRESHOLD) revert Errors.InvalidAmount();
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
        emergencyResumeRequestedAt = 0; // reset any pending resume request
        emit Events.GlobalCircuitBreakerTriggered(msg.sender, reason);
    }

    /// @notice Request emergency resume. Must wait EMERGENCY_RESUME_DELAY before executing.
    function requestEmergencyResume() external override onlyAdmin {
        if (!globalPaused) revert Errors.InvalidState();
        emergencyResumeRequestedAt = block.timestamp;
        uint256 availableAt = block.timestamp + EMERGENCY_RESUME_DELAY;
        emit Events.EmergencyResumeRequested(msg.sender, block.timestamp, availableAt);
    }

    function emergencyResume() external override onlyAdmin {
        if (emergencyResumeRequestedAt == 0) revert Errors.InvalidState();
        if (block.timestamp < emergencyResumeRequestedAt + EMERGENCY_RESUME_DELAY) {
            revert Errors.EmergencyResumeTooSoon(
                emergencyResumeRequestedAt,
                emergencyResumeRequestedAt + EMERGENCY_RESUME_DELAY
            );
        }
        emergencyResumeRequestedAt = 0;
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
