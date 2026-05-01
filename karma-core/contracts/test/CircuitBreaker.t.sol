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

        vm.prank(admin);
        breaker.emergencyResume();
        assertFalse(breaker.isGlobalPaused(), "global should be resumed");
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
}
