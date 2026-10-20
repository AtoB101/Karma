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
    address internal rewardAllocator = makeAddr("rewardAllocator");
    address internal stranger = makeAddr("stranger");
    address internal verifier = makeAddr("verifier");

    function setUp() public {
        vm.startPrank(admin);
        registry = new VerifierRegistry(admin);
        token = new MockERC20();
        registry.setStakingConfig(address(token), 1, 100);
        registry.registerVerifier(verifier, "https://v.example", 0);
        registry.setAuthorizedCaller(gateway, true);
        registry.setRewardAllocator(rewardAllocator);
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
        vm.prank(rewardAllocator);
        registry.creditRewards(100);

        vm.prank(gateway);
        registry.rewardVerifier(verifier, 100);
        assertEq(token.balanceOf(verifier), 100);
        assertEq(registry.rewardPool(), 0);
    }

    function test_rewardVerifier_revertsWhenPoolInsufficient() public {
        vm.prank(gateway);
        vm.expectRevert(VerifierRegistry.InsufficientRewardPool.selector);
        registry.rewardVerifier(verifier, 100);
    }

    function test_creditRewards_revertsForStranger() public {
        vm.prank(stranger);
        vm.expectRevert(VerifierRegistry.Unauthorized.selector);
        registry.creditRewards(100);
    }

    function test_creditRewards_okForAllocator() public {
        vm.prank(rewardAllocator);
        registry.creditRewards(100);
        assertEq(registry.rewardPool(), 100);
    }

    function test_adminCanCallPrivilegedWrites() public {
        vm.prank(rewardAllocator);
        registry.creditRewards(50);

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

    function test_register_isInactive_whenMinStakeSet() public {
        // setUp registers with minStake = 1, so the verifier must stake first.
        assertFalse(registry.isActiveVerifier(verifier));
    }

    function test_stake_activatesWhenMinStakeMet() public {
        token.mint(verifier, 10);

        vm.startPrank(verifier);
        token.approve(address(registry), type(uint256).max);
        registry.stake(1);
        vm.stopPrank();

        assertTrue(registry.isActiveVerifier(verifier));
        (, , , uint256 stakeAmt, , , , ) = registry.verifiers(verifier);
        assertEq(stakeAmt, 1);
    }

    function test_slash_transfersToSlashRecipient() public {
        token.mint(verifier, 10);

        vm.startPrank(verifier);
        token.approve(address(registry), type(uint256).max);
        registry.stake(10);
        vm.stopPrank();

        uint256 adminBefore = token.balanceOf(admin);
        vm.prank(admin);
        registry.slash(verifier, 10, "false_attestation");

        // Slashed stake is really transferred to the default slashRecipient.
        assertEq(token.balanceOf(admin), adminBefore + 10);
        (, , bool active, uint256 stakeAmt, , , , ) = registry.verifiers(verifier);
        assertEq(stakeAmt, 0);
        assertFalse(active);
    }
}
