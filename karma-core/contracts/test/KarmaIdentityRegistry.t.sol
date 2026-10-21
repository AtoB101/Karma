// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaIdentityRegistry} from "../core/KarmaIdentityRegistry.sol";

contract MockBilateral {
    mapping(address => uint256) public freeBalance;
    mapping(address => uint256) public boundBalance;

    function setFree(address a, uint256 v) external {
        freeBalance[a] = v;
    }

    function setBound(address a, uint256 v) external {
        boundBalance[a] = v;
    }
}

contract KarmaIdentityRegistryTest is Test {
    KarmaIdentityRegistry internal registry;
    MockBilateral internal bilateral;

    address internal master = address(0xA100);
    address internal sub = address(0xB200);
    address internal sub2 = address(0xB201);
    address internal stranger = address(0xC300);

    bytes32 internal constant SUB_ID = keccak256("sub-1");
    bytes32 internal constant SUB2_ID = keccak256("sub-2");
    bytes32 internal constant MASTER_ID = keccak256("master-1");

    function setUp() public {
        bilateral = new MockBilateral();
        registry = new KarmaIdentityRegistry(address(bilateral));
        vm.prank(master);
        registry.registerIdentity(MASTER_ID);
    }

    function _addSub(address wallet, bytes32 id) internal {
        vm.prank(master);
        registry.addSubAgent(wallet, id);
    }

    function testSetSubAgentBounds() public {
        _addSub(sub, SUB_ID);
        bilateral.setFree(master, 1000);

        vm.prank(master);
        registry.setSubAgentBounds(sub, 100, 50, block.timestamp + 1 days);

        KarmaIdentityRegistry.SubAgent[] memory subs = registry.getSubAgents(master);
        assertEq(subs.length, 1);
        assertEq(subs[0].subWallet, sub);
        assertEq(subs[0].master, master);
        assertEq(subs[0].allowance, 100);
        assertEq(subs[0].perTxLimit, 50);
        assertEq(subs[0].expiresAt, block.timestamp + 1 days);
    }

    function testSetSubAgentBoundsEmitsEvent() public {
        _addSub(sub, SUB_ID);
        bilateral.setFree(master, 1000);

        vm.expectEmit(true, true, true, true);
        emit KarmaIdentityRegistry.SubAgentBoundsUpdated(master, sub, 100, 50, block.timestamp + 1 days);
        vm.prank(master);
        registry.setSubAgentBounds(sub, 100, 50, block.timestamp + 1 days);
    }

    function testSetSubAgentBoundsRevertsPerTxOverAllowance() public {
        _addSub(sub, SUB_ID);
        bilateral.setFree(master, 1000);

        vm.prank(master);
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaIdentityRegistry.PerTxLimitExceedsAllowance.selector,
                uint256(60),
                uint256(50)
            )
        );
        registry.setSubAgentBounds(sub, 50, 60, 0);
    }

    function testSetSubAgentBoundsRevertsExpiryInPast() public {
        _addSub(sub, SUB_ID);
        bilateral.setFree(master, 1000);

        vm.prank(master);
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaIdentityRegistry.ExpiryInPast.selector,
                uint256(block.timestamp)
            )
        );
        registry.setSubAgentBounds(sub, 50, 0, block.timestamp);
    }

    function testSetSubAgentBoundsRevertsTotalOverFree() public {
        _addSub(sub, SUB_ID);
        _addSub(sub2, SUB2_ID);
        bilateral.setFree(master, 100);

        vm.prank(master);
        registry.setSubAgentBounds(sub, 80, 0, 0);

        vm.prank(master);
        vm.expectRevert(
            abi.encodeWithSelector(
                KarmaIdentityRegistry.AllowanceExceedsFreeBalance.selector,
                uint256(130),
                uint256(100)
            )
        );
        registry.setSubAgentBounds(sub2, 50, 0, 0);
    }

    function testIsAuthorizedWithinBounds() public {
        _addSub(sub, SUB_ID);
        bilateral.setFree(master, 1000);
        vm.prank(master);
        registry.setSubAgentBounds(sub, 100, 50, block.timestamp + 1 days);

        assertTrue(registry.isAuthorized(sub, 1));
        assertTrue(registry.isAuthorized(sub, 50));
        assertFalse(registry.isAuthorized(sub, 51));
        assertFalse(registry.isAuthorized(sub, 101));
    }

    function testIsAuthorizedNoPerTxCap() public {
        _addSub(sub, SUB_ID);
        bilateral.setFree(master, 1000);
        vm.prank(master);
        registry.setSubAgentBounds(sub, 100, 0, 0);

        assertTrue(registry.isAuthorized(sub, 100));
        assertFalse(registry.isAuthorized(sub, 101));
    }

    function testIsAuthorizedExpired() public {
        _addSub(sub, SUB_ID);
        bilateral.setFree(master, 1000);
        vm.prank(master);
        registry.setSubAgentBounds(sub, 100, 50, block.timestamp + 1 days);

        vm.warp(block.timestamp + 1 days + 1);
        assertFalse(registry.isAuthorized(sub, 1));
    }

    function testIsAuthorizedUnknownSub() public view {
        assertFalse(registry.isAuthorized(stranger, 1));
    }

    function testRemoveSubAgentClearsAuthorization() public {
        _addSub(sub, SUB_ID);
        bilateral.setFree(master, 1000);
        vm.prank(master);
        registry.setSubAgentBounds(sub, 100, 50, block.timestamp + 1 days);

        vm.prank(master);
        registry.removeSubAgent(sub);

        assertFalse(registry.isAuthorized(sub, 1));
    }
}
