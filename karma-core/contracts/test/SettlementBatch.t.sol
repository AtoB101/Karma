// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test, console} from "forge-std/Test.sol";
import {KarmaBilateral} from "../core/KarmaBilateral.sol";
import {SettlementBatch} from "../core/SettlementBatch.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

contract SettlementBatchTest is Test {
    KarmaBilateral internal karma;
    SettlementBatch internal batch;
    MockERC20      internal usdc;

    address internal admin    = makeAddr("admin");
    address internal operator = makeAddr("operator");
    address internal buyer    = makeAddr("buyer");
    address internal agent    = makeAddr("agent");
    address internal stranger = makeAddr("stranger");

    uint256 internal constant BUYER_LOCK = 100_000_000; // 100 USDC
    uint256 internal constant AGENT_LOCK =  50_000_000; //  50 USDC
    bytes32 internal constant SCOPE      = keccak256("search:latest-pricing");
    bytes32 internal constant PROOF      = keccak256("ipfs://Qm...");

    function setUp() public {
        usdc = new MockERC20();
        vm.startPrank(admin);
        karma = new KarmaBilateral(admin);
        karma.setTokenAllowed(address(usdc), true);
        batch = new SettlementBatch(admin, address(karma));
        batch.setOperator(operator);
        karma.setSettleOperator(address(batch));
        vm.stopPrank();

        usdc.mint(buyer,   1_000_000_000);
        usdc.mint(agent,   1_000_000_000);
        usdc.mint(stranger, 500_000_000);

        vm.prank(buyer);    usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent);    usdc.approve(address(karma), type(uint256).max);
        vm.prank(stranger); usdc.approve(address(karma), type(uint256).max);
    }

    function _setupBinding() internal returns (uint256 bindingId) {
        vm.prank(buyer); uint256 buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 agentBill = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer); bindingId = karma.bind(buyerBill, agentBill, SCOPE);
    }

    function _items(uint256[] memory ids, bytes32 proofHash)
        internal pure returns (SettlementBatch.Settlement[] memory)
    {
        SettlementBatch.Settlement[] memory items = new SettlementBatch.Settlement[](ids.length);
        for (uint256 i = 0; i < ids.length; i++) {
            items[i] = SettlementBatch.Settlement({bindingId: ids[i], proofHash: proofHash});
        }
        return items;
    }

    function test_constructor_zeroAdmin() public {
        vm.expectRevert(SettlementBatch.ZeroAddress.selector);
        new SettlementBatch(address(0), address(karma));
    }

    function test_constructor_zeroCore() public {
        vm.expectRevert(SettlementBatch.ZeroAddress.selector);
        new SettlementBatch(admin, address(0));
    }

    function test_setOperator_zeroReverts() public {
        vm.prank(admin);
        vm.expectRevert(SettlementBatch.ZeroAddress.selector);
        batch.setOperator(address(0));
    }

    function test_batchSettle_operatorSettlesMany() public {
        uint256[] memory ids = new uint256[](3);
        ids[0] = _setupBinding();
        ids[1] = _setupBinding();
        ids[2] = _setupBinding();

        vm.warp(block.timestamp + karma.settleDelaySeconds() + 1);
        vm.prank(operator);
        batch.batchSettle(_items(ids, PROOF));

        for (uint256 i = 0; i < ids.length; i++) {
            assertEq(uint8(karma.getBinding(ids[i]).state), uint8(KarmaBilateral.BindingState.FINALIZING));
            assertEq(karma.getBinding(ids[i]).proofHash, PROOF);
        }
    }

    function test_batchSettle_nonOperatorReverts() public {
        uint256[] memory ids = new uint256[](1);
        ids[0] = _setupBinding();

        vm.warp(block.timestamp + karma.settleDelaySeconds() + 1);
        vm.prank(stranger);
        vm.expectRevert(SettlementBatch.Unauthorized.selector);
        batch.batchSettle(_items(ids, PROOF));
    }

    function test_batchSettle_emptyReverts() public {
        vm.prank(operator);
        vm.expectRevert(SettlementBatch.EmptyBatch.selector);
        batch.batchSettle(new SettlementBatch.Settlement[](0));
    }

    function test_batchFinalize_completesMany() public {
        uint256[] memory ids = new uint256[](2);
        ids[0] = _setupBinding();
        ids[1] = _setupBinding();

        vm.warp(block.timestamp + karma.settleDelaySeconds() + 1);
        vm.prank(operator);
        batch.batchSettle(_items(ids, PROOF));

        vm.warp(block.timestamp + karma.optimisticDisputeWindow() + 1);
        vm.prank(operator);
        batch.batchFinalize(ids);

        for (uint256 i = 0; i < ids.length; i++) {
            assertEq(uint8(karma.getBinding(ids[i]).state), uint8(KarmaBilateral.BindingState.SETTLED));
        }
    }

    function test_batchFinalize_emptyReverts() public {
        vm.prank(operator);
        vm.expectRevert(SettlementBatch.EmptyBatch.selector);
        batch.batchFinalize(new uint256[](0));
    }

    function test_coreRejectsNonOperatorSettle() public {
        uint256 bindingId = _setupBinding();
        vm.warp(block.timestamp + karma.settleDelaySeconds() + 1);

        // settleOperator == address(batch); a direct stranger settle is rejected
        vm.prank(stranger);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.NoDisputeAccess.selector, bindingId));
        karma.settle(bindingId, PROOF);
    }

    function test_coreAcceptsOperatorRoleAfterRevoke() public {
        // Sanity: without the operator grant the batch cannot settle.
        vm.prank(admin);
        karma.setSettleOperator(address(0));

        uint256 bindingId = _setupBinding();
        vm.warp(block.timestamp + karma.settleDelaySeconds() + 1);

        uint256[] memory ids = new uint256[](1);
        ids[0] = bindingId;
        vm.prank(operator);
        vm.expectRevert(abi.encodeWithSelector(KarmaBilateral.NoDisputeAccess.selector, bindingId));
        batch.batchSettle(_items(ids, PROOF));
    }
}
