// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {VerifierRegistry} from "../core/VerifierRegistry.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

/// @notice Access-control coverage for privileged VerifierRegistry writes.
contract VerifierRegistryAccessControlTest is Test {
    VerifierRegistry internal registry;
    MockERC20 internal token;

    address internal admin = makeAddr("admin");
    address internal gateway = makeAddr("gateway");
    address internal stranger = makeAddr("stranger");
    address internal verifier = makeAddr("verifier");

    function setUp() public {
        vm.startPrank(admin);
        registry = new VerifierRegistry(admin);
        token = new MockERC20();
        registry.setStakingConfig(address(token), 1, 100);
        registry.registerVerifier(verifier, "https://v.example", 0);
        registry.setAuthorizedCaller(gateway, true);
        vm.stopPrank();

        token.mint(address(registry), 1_000_000);
    }

    function test_recordAttestation_revertsForStranger() public {
        vm.prank(stranger);
        vm.expectRevert(VerifierRegistry.Unauthorized.selector);
        registry.recordAttestation(verifier, true);
    }

    function test_rewardVerifier_revertsForStranger() public {
        vm.prank(stranger);
        vm.expectRevert(VerifierRegistry.Unauthorized.selector);
        registry.rewardVerifier(verifier, 100);
    }

    function test_recordAttestation_okForGateway() public {
        vm.prank(gateway);
        registry.recordAttestation(verifier, true);
        (, , , , uint256 successCount, , , ) = registry.verifiers(verifier);
        assertEq(successCount, 1);
    }

    function test_rewardVerifier_okForGateway() public {
        vm.prank(gateway);
        registry.rewardVerifier(verifier, 100);
        assertEq(token.balanceOf(verifier), 100);
    }

    function test_adminCanCallPrivilegedWrites() public {
        vm.startPrank(admin);
        registry.recordAttestation(verifier, false);
        registry.rewardVerifier(verifier, 50);
        vm.stopPrank();
        (, , , , , uint256 falseCount, , ) = registry.verifiers(verifier);
        assertEq(falseCount, 1);
        assertEq(token.balanceOf(verifier), 50);
    }

    function test_revokeAuthorizedCaller() public {
        vm.prank(admin);
        registry.setAuthorizedCaller(gateway, false);

        vm.prank(gateway);
        vm.expectRevert(VerifierRegistry.Unauthorized.selector);
        registry.recordAttestation(verifier, true);
    }
}
