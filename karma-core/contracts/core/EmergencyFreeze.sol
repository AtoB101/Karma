// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ICircuitBreaker} from "../interfaces/ICircuitBreaker.sol";
import {IEmergencyFreeze} from "../interfaces/IEmergencyFreeze.sol";

/// @notice Timed freeze overlay + CircuitBreaker. Lives outside KarmaBilateral to stay under EIP-170.
contract EmergencyFreeze is IEmergencyFreeze {
    error Unauthorized();
    error ZeroAddress();
    error FreezeDurationInvalid(uint256 duration);
    error FreezeOperatorZero();

    uint256 public constant MAX_FREEZE_DURATION = 7 days;

    address public immutable admin;
    address public freezeOperator;
    address public circuitBreaker;
    uint256 public globalFreezeUntil;
    mapping(address => uint256) public agentFreezeUntil;
    mapping(uint256 => uint256) public billFreezeUntil;
    mapping(uint256 => uint256) public bindingFreezeUntil;

    event CircuitBreakerUpdated(address indexed breaker);
    event FreezeOperatorUpdated(address indexed operator);
    event GlobalFrozen(address indexed actor, uint256 until, string reason);
    event GlobalUnfrozen(address indexed actor);
    event AgentFrozen(address indexed agent, uint256 until, string reason);
    event AgentUnfrozen(address indexed agent);
    event BillFrozen(uint256 indexed billId, uint256 until, string reason);
    event BillUnfrozen(uint256 indexed billId);
    event BindingFrozen(uint256 indexed bindingId, uint256 until, string reason);
    event BindingUnfrozen(uint256 indexed bindingId);

    modifier onlyAdmin() {
        if (msg.sender != admin) revert Unauthorized();
        _;
    }

    modifier onlyFreezeAuthority() {
        if (msg.sender != admin && msg.sender != freezeOperator) revert Unauthorized();
        _;
    }

    constructor(address admin_) {
        if (admin_ == address(0)) revert ZeroAddress();
        admin = admin_;
        freezeOperator = admin_;
    }

    function setCircuitBreaker(address breaker) external onlyAdmin {
        circuitBreaker = breaker;
        emit CircuitBreakerUpdated(breaker);
    }

    function setFreezeOperator(address operator) external onlyAdmin {
        if (operator == address(0)) revert FreezeOperatorZero();
        freezeOperator = operator;
        emit FreezeOperatorUpdated(operator);
    }

    function freezeGlobal(uint256 duration, string calldata reason) external onlyFreezeAuthority {
        uint256 until = _freezeUntil(duration);
        globalFreezeUntil = until;
        emit GlobalFrozen(msg.sender, until, reason);
    }

    function unfreezeGlobal() external onlyFreezeAuthority {
        globalFreezeUntil = 0;
        emit GlobalUnfrozen(msg.sender);
    }

    function freezeAgent(address agent_, uint256 duration, string calldata reason) external onlyFreezeAuthority {
        if (agent_ == address(0)) revert ZeroAddress();
        uint256 until = _freezeUntil(duration);
        agentFreezeUntil[agent_] = until;
        emit AgentFrozen(agent_, until, reason);
    }

    function unfreezeAgent(address agent_) external onlyFreezeAuthority {
        agentFreezeUntil[agent_] = 0;
        emit AgentUnfrozen(agent_);
    }

    function freezeBill(uint256 billId, uint256 duration, string calldata reason) external onlyFreezeAuthority {
        uint256 until = _freezeUntil(duration);
        billFreezeUntil[billId] = until;
        emit BillFrozen(billId, until, reason);
    }

    function unfreezeBill(uint256 billId) external onlyFreezeAuthority {
        billFreezeUntil[billId] = 0;
        emit BillUnfrozen(billId);
    }

    function freezeBinding(uint256 bindingId, uint256 duration, string calldata reason) external onlyFreezeAuthority {
        uint256 until = _freezeUntil(duration);
        bindingFreezeUntil[bindingId] = until;
        emit BindingFrozen(bindingId, until, reason);
    }

    function unfreezeBinding(uint256 bindingId) external onlyFreezeAuthority {
        bindingFreezeUntil[bindingId] = 0;
        emit BindingUnfrozen(bindingId);
    }

    function isGlobalFrozen() public view returns (bool) {
        return _untilActive(globalFreezeUntil) || _breakerGlobalPaused();
    }

    function payoutBlocked(
        uint256 bindingId,
        uint256 buyerBillId,
        uint256 agentBillId,
        address buyerOwner,
        address agentOwner
    ) external view returns (bool blocked, uint8 scope, uint256 until) {
        if (_untilActive(globalFreezeUntil)) return (true, 1, globalFreezeUntil);
        if (_breakerGlobalPaused()) return (true, 5, type(uint256).max);
        if (bindingId != 0 && _untilActive(bindingFreezeUntil[bindingId])) {
            return (true, 4, bindingFreezeUntil[bindingId]);
        }
        if (_untilActive(billFreezeUntil[buyerBillId])) return (true, 3, billFreezeUntil[buyerBillId]);
        if (_untilActive(billFreezeUntil[agentBillId])) return (true, 3, billFreezeUntil[agentBillId]);
        if (_untilActive(agentFreezeUntil[buyerOwner])) return (true, 2, agentFreezeUntil[buyerOwner]);
        if (_untilActive(agentFreezeUntil[agentOwner])) return (true, 2, agentFreezeUntil[agentOwner]);
        if (_breakerAgentPaused(buyerOwner) || _breakerAgentPaused(agentOwner)) {
            return (true, 5, type(uint256).max);
        }
        return (false, 0, 0);
    }

    function bindBlocked(
        address buyerOwner,
        address agentOwner,
        uint256 buyerBillId,
        uint256 agentBillId
    ) external view returns (bool blocked, uint8 scope, uint256 until) {
        if (_untilActive(globalFreezeUntil) || _breakerGlobalPaused()) {
            return (true, 1, globalFreezeUntil);
        }
        if (_untilActive(agentFreezeUntil[buyerOwner]) || _breakerAgentPaused(buyerOwner)) {
            return (true, 2, agentFreezeUntil[buyerOwner]);
        }
        if (_untilActive(agentFreezeUntil[agentOwner]) || _breakerAgentPaused(agentOwner)) {
            return (true, 2, agentFreezeUntil[agentOwner]);
        }
        if (_untilActive(billFreezeUntil[buyerBillId])) return (true, 3, billFreezeUntil[buyerBillId]);
        if (_untilActive(billFreezeUntil[agentBillId])) return (true, 3, billFreezeUntil[agentBillId]);
        return (false, 0, 0);
    }

    function _freezeUntil(uint256 duration) internal view returns (uint256) {
        if (duration == 0 || duration > MAX_FREEZE_DURATION) revert FreezeDurationInvalid(duration);
        return block.timestamp + duration;
    }

    function _untilActive(uint256 until_) internal view returns (bool) {
        return until_ != 0 && block.timestamp < until_;
    }

    function _breakerGlobalPaused() internal view returns (bool) {
        if (circuitBreaker == address(0)) return false;
        return ICircuitBreaker(circuitBreaker).isGlobalPaused();
    }

    function _breakerAgentPaused(address agent_) internal view returns (bool) {
        if (circuitBreaker == address(0) || agent_ == address(0)) return false;
        return ICircuitBreaker(circuitBreaker).isAgentPaused(agent_);
    }
}
