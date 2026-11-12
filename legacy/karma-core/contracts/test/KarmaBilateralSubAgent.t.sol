// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaBilateral} from "../core/KarmaBilateral.sol";
import {KarmaIdentityRegistry} from "../core/KarmaIdentityRegistry.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

contract KarmaBilateralSubAgentTest is Test {
    KarmaBilateral internal karma;
    KarmaIdentityRegistry internal registry;
    MockERC20 internal usdc;

    address internal admin = makeAddr("admin");
    address internal master = makeAddr("master");
    address internal sub = makeAddr("sub");
    address internal stranger = makeAddr("stranger");
    address internal agent = makeAddr("agent");

    bytes32 internal constant MASTER_ID = keccak256("master-1");
    bytes32 internal constant SUB_ID = keccak256("sub-1");

    uint256 internal constant PRE_LOCK = 1_000_000_000; // 1000 USDC
    uint256 internal constant ALLOWANCE = 500_000_000;  //  500 USDC
    uint256 internal constant PER_TX = 100_000_000;     //  100 USDC

    function setUp() public {
        usdc = new MockERC20();
        vm.startPrank(admin);
        karma = new KarmaBilateral(admin);
        karma.setTokenAllowed(address(usdc), true);
        registry = new KarmaIdentityRegistry(address(karma));
        karma.setIdentityRegistry(address(registry));
        vm.stopPrank();

        usdc.mint(master, 2_000_000_000);
        usdc.mint(agent, 1_000_000_000);
        usdc.mint(stranger, 500_000_000);

        vm.prank(master);
        usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent);
        usdc.approve(address(karma), type(uint256).max);

        vm.startPrank(master);
        registry.registerIdentity(MASTER_ID);
        registry.addSubAgent(sub, SUB_ID);
        vm.stopPrank();
    }

    function _fundAndAuthorize() internal {
        vm.prank(master);
        karma.lock(address(usdc), PRE_LOCK);
        vm.prank(master);
        registry.setSubAgentBounds(sub, ALLOWANCE, PER_TX, block.timestamp + 1 days);
    }

    function testLockForMintsBillToMasterAndConsumesBudget() public {
        _fundAndAuthorize();

        vm.prank(sub);
        uint256 billId = karma.lockFor(address(usdc), 50_000_000, master);

        KarmaBilateral.BillToken memory bill = karma.getBill(billId);
        assertEq(bill.owner, master);
        assertEq(bill.token, address(usdc));
        assertEq(bill.amount, 50_000_000);
        assertEq(uint8(bill.state), uint8(KarmaBilateral.BillState.MINTED));

        // funds pulled from master wallet into escrow
        assertEq(usdc.balanceOf(address(karma)), PRE_LOCK + 50_000_000);
        assertEq(karma.freeBalance(master), PRE_LOCK + 50_000_000);

        // registry budget decremented
        KarmaIdentityRegistry.SubAgent[] memory subs = registry.getSubAgents(master);
        assertEq(subs.length, 1);
        assertEq(subs[0].allowance, ALLOWANCE - 50_000_000);
    }

    function testLockForRevertsWhenRegistryNotSet() public {
        vm.prank(admin);
        KarmaBilateral fresh = new KarmaBilateral(admin);
        vm.prank(admin);
        fresh.setTokenAllowed(address(usdc), true);
        vm.prank(master);
        usdc.approve(address(fresh), type(uint256).max);

        vm.prank(sub);
        vm.expectRevert(KarmaBilateral.IdentityRegistryNotSet.selector);
        fresh.lockFor(address(usdc), 50_000_000, master);
    }

    function testLockForRevertsUnauthorized() public {
        _fundAndAuthorize();

        vm.prank(stranger);
        vm.expectRevert(
            abi.encodeWithSelector(KarmaBilateral.SubAgentNotAuthorized.selector, stranger, 50_000_000)
        );
        karma.lockFor(address(usdc), 50_000_000, master);
    }

    function testLockForRevertsOverPerTxLimit() public {
        _fundAndAuthorize();

        vm.prank(sub);
        vm.expectRevert(
            abi.encodeWithSelector(KarmaBilateral.SubAgentNotAuthorized.selector, sub, PER_TX + 1)
        );
        karma.lockFor(address(usdc), PER_TX + 1, master);
    }

    function testLockForRevertsExpired() public {
        _fundAndAuthorize();

        vm.warp(block.timestamp + 1 days + 1);
        vm.prank(sub);
        vm.expectRevert(
            abi.encodeWithSelector(KarmaBilateral.SubAgentNotAuthorized.selector, sub, 50_000_000)
        );
        karma.lockFor(address(usdc), 50_000_000, master);
    }

    function testLockForExhaustsBudget() public {
        vm.prank(master);
        karma.lock(address(usdc), PRE_LOCK);
        vm.prank(master);
        registry.setSubAgentBounds(sub, 100_000_000, 50_000_000, block.timestamp + 1 days);

        vm.startPrank(sub);
        karma.lockFor(address(usdc), 50_000_000, master);
        karma.lockFor(address(usdc), 50_000_000, master);
        vm.stopPrank();

        KarmaIdentityRegistry.SubAgent[] memory subs = registry.getSubAgents(master);
        assertEq(subs[0].allowance, 0);

        vm.prank(sub);
        vm.expectRevert(
            abi.encodeWithSelector(KarmaBilateral.SubAgentNotAuthorized.selector, sub, 1)
        );
        karma.lockFor(address(usdc), 1, master);
    }

    function testLockForThenMasterBinds() public {
        _fundAndAuthorize();

        vm.prank(sub);
        uint256 buyerBill = karma.lockFor(address(usdc), 50_000_000, master);

        vm.prank(agent);
        uint256 agentBill = karma.lock(address(usdc), 50_000_000);

        vm.prank(master);
        uint256 bindingId = karma.bind(buyerBill, agentBill, keccak256("scope"));

        assertEq(uint8(karma.getBinding(bindingId).state), uint8(KarmaBilateral.BindingState.ACTIVE));
        assertEq(uint8(karma.getBill(buyerBill).state), uint8(KarmaBilateral.BillState.BOUND));
    }
}
