// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

interface ICircuitBreaker {
    function setHumanApprovalThreshold(uint256 amount) external;
    function pauseAgent(address agent, string calldata reason) external;
    function resumeAgent(address agent) external;
    function emergencyPause(string calldata reason) external;
    function emergencyResume() external;
    function isGlobalPaused() external view returns (bool);
    function isAgentPaused(address agent) external view returns (bool);
}
