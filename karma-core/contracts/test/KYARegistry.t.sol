// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KYARegistry} from "../core/KYARegistry.sol";
import {Errors} from "../libraries/Errors.sol";

contract KYARegistryTest is Test {
    KYARegistry internal registry;
    address internal owner = address(0xABCD);
    address internal attacker = address(0xDEAD);
    address internal agent = address(0xA11CE);

    function setUp() public {
        registry = new KYARegistry();
        vm.deal(owner, 1 ether);
        vm.deal(attacker, 1 ether);
    }

    function testRegisterAndVerifyDID() public {
        bytes32 permissionsHash = keccak256("perm-v1");
        vm.prank(owner);
        bytes32 did = registry.registerDID{value: 0.01 ether}(agent, permissionsHash, 30);
        assertTrue(did != bytes32(0), "did should be non-zero");

        (bool ok, address ownerAddr, uint256 validUntil) = registry.verifyDID(agent);
        assertTrue(ok, "did should be valid");
        assertEq(ownerAddr, address(0xABCD), "owner mismatch");
        assertGt(validUntil, block.timestamp, "validUntil should be future");
    }

    function testRevokeDID() public {
        vm.prank(owner);
        registry.registerDID{value: 0.01 ether}(agent, keccak256("perm"), 7);
        vm.prank(owner);
        registry.revokeDID(agent);

        (bool ok,,) = registry.verifyDID(agent);
        assertFalse(ok, "did should be revoked");
    }

    function testRegisterDIDRevertsForLowStake() public {
        vm.prank(owner);
        vm.expectRevert(Errors.InvalidAmount.selector);
        registry.registerDID{value: 0.001 ether}(address(0x1), bytes32("p"), 1);
    }

    function testRegisterDIDRevertsWhenActiveOwnerDiffers() public {
        vm.prank(owner);
        registry.registerDID{value: 0.01 ether}(agent, keccak256("perm"), 30);

        vm.prank(attacker);
        vm.expectRevert(Errors.Unauthorized.selector);
        registry.registerDID{value: 0.01 ether}(agent, keccak256("perm-attacker"), 30);
    }

    function testRegisterDIDAllowsRenewByOwner() public {
        vm.prank(owner);
        registry.registerDID{value: 0.01 ether}(agent, keccak256("perm"), 1);
        vm.warp(block.timestamp + 1 hours);

        vm.prank(owner);
        registry.registerDID{value: 0.01 ether}(agent, keccak256("perm"), 30);

        (bool ok, address ownerAddr, uint256 validUntil) = registry.verifyDID(agent);
        assertTrue(ok);
        assertEq(ownerAddr, owner);
        assertGt(validUntil, block.timestamp + 25 days);
    }
}
