// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaBilateral}           from "../core/KarmaBilateral.sol";
import {KarmaAttestationGateway}  from "../core/KarmaAttestationGateway.sol";
import {VerifierRegistry}         from "../core/VerifierRegistry.sol";
import {AdminTimelock}            from "../core/AdminTimelock.sol";
import {MockERC20}                from "./mocks/MockERC20.sol";

/// @notice Proves dispute arbitration is multisig-governed: a single EOA cannot
///         resolve a dispute or configure the challenge stake; only an
///         AdminTimelock action (N-of-M approvals + delay) can.
contract KarmaMultisigArbitrationTest is Test {
    AdminTimelock           internal tl;
    KarmaBilateral          internal karma;
    KarmaAttestationGateway internal gateway;
    VerifierRegistry        internal registry;
    MockERC20               internal usdc;

    address internal owner1 = makeAddr("owner1");
    address internal owner2 = makeAddr("owner2");
    address internal owner3 = makeAddr("owner3");
    address internal buyer  = makeAddr("buyer");
    address internal agent  = makeAddr("agent");

    uint256 internal constant BUYER_LOCK = 100_000_000; // 100 USDC
    uint256 internal constant AGENT_LOCK =  50_000_000; //  50 USDC
    bytes32 internal constant SCOPE = keccak256("scope");
    bytes32 internal constant PROOF = keccak256("proof");

    function setUp() public {
        address[] memory owners = new address[](3);
        owners[0] = owner1;
        owners[1] = owner2;
        owners[2] = owner3;
        tl = new AdminTimelock(owners, 2, 1 days); // 2-of-3, 1-day delay

        usdc = new MockERC20();

        // Every privileged contract is owned by the timelock, not an EOA.
        karma    = new KarmaBilateral(address(tl));
        registry = new VerifierRegistry(address(tl));
        gateway  = new KarmaAttestationGateway(address(registry), address(karma), address(tl), 1 hours);

        // Wire through the multisig timelock (exercises the full governance path).
        _govern(address(karma),    abi.encodeCall(KarmaBilateral.setTokenAllowed, (address(usdc), true)));
        _govern(address(karma),    abi.encodeCall(KarmaBilateral.setAttestationGateway, (address(gateway))));
        _govern(address(registry), abi.encodeCall(VerifierRegistry.setAuthorizedCaller, (address(gateway), true)));

        usdc.mint(buyer, 1_000_000_000);
        usdc.mint(agent, 1_000_000_000);
        vm.prank(buyer); usdc.approve(address(karma), type(uint256).max);
        vm.prank(agent); usdc.approve(address(karma), type(uint256).max);
    }

    // ── Helpers ──────────────────────────────────────────────────────────────

    /// @dev schedule by owner1 → approve by owner2 → wait delay → permissionless execute.
    function _govern(address target, bytes memory data) internal returns (bytes32 id) {
        vm.prank(owner1);
        id = tl.schedule(target, 0, data);
        vm.prank(owner2);
        tl.approve(id);
        vm.warp(block.timestamp + tl.minDelay() + 1);
        tl.execute(id);
    }

    function _disputedBinding() internal returns (uint256 bindingId) {
        vm.prank(buyer); uint256 buyerBill = karma.lock(address(usdc), BUYER_LOCK);
        vm.prank(agent); uint256 agentBill = karma.lock(address(usdc), AGENT_LOCK);
        vm.prank(buyer); bindingId = karma.bind(buyerBill, agentBill, SCOPE);

        vm.warp(block.timestamp + karma.settleDelaySeconds() + 1);
        vm.prank(buyer); karma.settle(bindingId, PROOF);
        vm.prank(buyer); karma.dispute(bindingId, PROOF);

        vm.warp(block.timestamp + karma.evidenceWindow() + 1);
    }

    // ── Tests ────────────────────────────────────────────────────────────────

    function test_wiring_timelockOwnsPrivilegedContracts() public view {
        assertEq(karma.admin(), address(tl));
        assertEq(gateway.arbitrator(), address(tl));
        assertEq(registry.admin(), address(tl));
        assertEq(tl.threshold(), 2);
        assertTrue(tl.minDelay() > 0);
    }

    function test_resolveDispute_revertsForSingleEOA() public {
        uint256 bindingId = _disputedBinding();

        // Even a timelock owner is not the contract admin — direct call must revert.
        vm.prank(owner1);
        vm.expectRevert(KarmaBilateral.Unauthorized.selector);
        karma.resolveDispute(bindingId, 10_000);
    }

    function test_resolveDispute_viaTimelockMultisig() public {
        uint256 bindingId = _disputedBinding();

        uint256 buyerBefore = usdc.balanceOf(buyer);
        uint256 agentBefore = usdc.balanceOf(agent);

        // N-of-M approvals + delay, executed by the timelock as contract admin.
        _govern(address(karma), abi.encodeCall(KarmaBilateral.resolveDispute, (bindingId, uint16(10_000))));

        assertEq(usdc.balanceOf(buyer), buyerBefore + BUYER_LOCK + AGENT_LOCK);
        assertEq(usdc.balanceOf(agent), agentBefore);
        assertTrue(karma.checkInvariant(address(usdc)));
    }

    function test_gatewayChallengeStake_requiresTimelock() public {
        // A single EOA cannot configure the challenge stake.
        vm.prank(owner1);
        vm.expectRevert(KarmaAttestationGateway.NotArbitrator.selector);
        gateway.setChallengeStake(address(usdc), 1_000_000);

        // Only the timelock (as arbitrator) can.
        _govern(address(gateway), abi.encodeCall(KarmaAttestationGateway.setChallengeStake, (address(usdc), 1_000_000)));
        assertEq(gateway.challengeStakeToken(), address(usdc));
        assertEq(gateway.challengeStakeAmount(), 1_000_000);
    }
}
