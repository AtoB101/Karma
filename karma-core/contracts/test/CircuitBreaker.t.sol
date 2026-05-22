// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {CircuitBreaker} from "../core/CircuitBreaker.sol";
import {Errors} from "../libraries/Errors.sol";

contract CircuitBreakerTest is Test {
    CircuitBreaker internal breaker;
    address internal admin = address(0xA11CE);
    address internal nonAdmin = address(0xB0B);

    function setUp() public {
        breaker = new CircuitBreaker(admin);
    }

    function testAdminCanPauseAndResumeGlobal() public {
        vm.prank(admin);
        breaker.emergencyPause("incident");
        assertTrue(breaker.isGlobalPaused(), "global should be paused");

        // Emergency resume requires 24h timelock
        vm.prank(admin);
        breaker.requestEmergencyResume();
        assertEq(breaker.emergencyResumeRequestedAt(), block.timestamp);

        // Fast-forward 24 hours
        vm.warp(block.timestamp + 24 hours + 1);

        vm.prank(admin);
        breaker.emergencyResume();
        assertFalse(breaker.isGlobalPaused(), "global should be resumed");
    }

    function testEmergencyResumeFailsBeforeDelay() public {
        vm.prank(admin);
        breaker.emergencyPause("incident");

        vm.prank(admin);
        breaker.requestEmergencyResume();

        vm.expectRevert();
        vm.prank(admin);
        breaker.emergencyResume(); // too soon!
    }

    function testAdminCanPauseAndResumeAgent() public {
        address agent = address(0xA9E);
        vm.prank(admin);
        breaker.pauseAgent(agent, "abnormal tx");
        assertTrue(breaker.isAgentPaused(agent), "agent should be paused");

        vm.prank(admin);
        breaker.resumeAgent(agent);
        assertFalse(breaker.isAgentPaused(agent), "agent should be resumed");
    }

    function testNonAdminCannotPauseAgent() public {
        vm.prank(nonAdmin);
        vm.expectRevert(Errors.Unauthorized.selector);
        breaker.pauseAgent(address(0xBEEF), "test");
    }

    function testSetHumanApprovalThresholdRespectsCap() public {
        vm.prank(admin);
        breaker.setHumanApprovalThreshold(uint256(type(uint128).max));
        assertEq(breaker.humanApprovalThreshold(admin), uint256(type(uint128).max));

        vm.prank(admin);
        vm.expectRevert(Errors.InvalidAmount.selector);
        breaker.setHumanApprovalThreshold(uint256(type(uint128).max) + 1);
    }
}
