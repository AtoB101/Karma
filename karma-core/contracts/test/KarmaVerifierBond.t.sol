// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaVerifierBond} from "../core/KarmaVerifierBond.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

/// @notice 质押金库（G12）：真托管、罚没 80/20、不足即停用、冷却退出、池子平分。
contract KarmaVerifierBondTest is Test {
    KarmaVerifierBond internal vault;
    MockERC20 internal token;

    address internal admin;
    address internal slasher;
    address internal victim;
    address internal v1;
    address internal v2;
    address internal v3;
    address internal v4;
    address internal stranger;

    uint256 internal constant MIN_BOND = 100e6;
    uint256 internal constant COOLDOWN = 3 days;
    uint256 internal constant POOL_THRESHOLD = 50e6;
    uint256 internal constant FUNDED = 1_000e6;

    event BondStaked(address indexed verifier, uint256 amount, uint256 total);
    event VerifierDeactivated(address indexed verifier, uint256 remainingBond);
    event PoolDistributed(address[] winners, uint256 amount, uint256 perWinner);

    function setUp() public {
        admin = makeAddr("admin");
        slasher = makeAddr("slasher");
        victim = makeAddr("victim");
        v1 = makeAddr("v1");
        v2 = makeAddr("v2");
        v3 = makeAddr("v3");
        v4 = makeAddr("v4");
        stranger = makeAddr("stranger");

        token = new MockERC20();
        vault = new KarmaVerifierBond(admin, address(token), MIN_BOND);

        vm.startPrank(admin);
        vault.setSlasher(slasher);
        vault.setStakeConfig(MIN_BOND, COOLDOWN, POOL_THRESHOLD);
        vm.stopPrank();

        token.mint(v1, FUNDED);
        token.mint(v2, FUNDED);
        token.mint(v3, FUNDED);
        token.mint(v4, FUNDED);
    }

    // ───────────────────────────────────────────────────────────── helpers

    function _stake(address who, uint256 amount) internal {
        vm.startPrank(who);
        token.approve(address(vault), amount);
        vault.stake(amount);
        vm.stopPrank();
    }

    // ──────────────────────────────────────────────────────── staking path

    function testStakeCustodiesTokensAndActivates() public {
        _stake(v1, MIN_BOND);

        assertEq(token.balanceOf(address(vault)), MIN_BOND, "vault must really custody the bond");
        assertEq(token.balanceOf(v1), FUNDED - MIN_BOND);
        assertEq(vault.totalBonded(), MIN_BOND);
        assertEq(vault.bondAmount(v1), MIN_BOND);
        assertTrue(vault.isRegistered(v1));
        assertTrue(vault.isActive(v1));
        assertEq(vault.memberCount(), 1);
        assertEq(vault.solvencyGap(), 0);
    }

    function testStakeEmitsEvent() public {
        vm.startPrank(v1);
        token.approve(address(vault), MIN_BOND);
        vm.expectEmit(true, false, false, true, address(vault));
        emit BondStaked(v1, MIN_BOND, MIN_BOND);
        vault.stake(MIN_BOND);
        vm.stopPrank();
    }

    function testStakeBelowMinStaysInactiveThenActivatesOnTopUp() public {
        _stake(v1, MIN_BOND - 1);
        assertTrue(vault.isRegistered(v1));
        assertFalse(vault.isActive(v1), "below minBond must not be active");

        _stake(v1, 1);
        assertTrue(vault.isActive(v1), "crossing minBond activates");
        assertEq(vault.bondAmount(v1), MIN_BOND);
    }

    function testStakeZeroReverts() public {
        vm.prank(v1);
        vm.expectRevert(KarmaVerifierBond.InvalidAmount.selector);
        vault.stake(0);
    }

    function testStakeWithoutApprovalReverts() public {
        vm.prank(v1);
        vm.expectRevert(KarmaVerifierBond.TransferFailed.selector);
        vault.stake(MIN_BOND);
    }

    function testRestakingReactivatesAfterSlashDeactivation() public {
        _stake(v1, MIN_BOND);
        vm.prank(slasher);
        vault.slash(v1, victim, 50e6, keccak256("bad"));
        assertFalse(vault.isActive(v1), "dropped below minBond");

        _stake(v1, 60e6);
        assertTrue(vault.isActive(v1), "topping back above minBond reactivates");
    }

    // ──────────────────────────────────────────────────────── slashing 80/20

    function testSlashSplitsEightyTwenty() public {
        _stake(v1, FUNDED);

        uint256 victimBefore = token.balanceOf(victim);
        vm.prank(slasher);
        (uint256 toVictim, uint256 toPool) = vault.slash(v1, victim, 100e6, keccak256("false"));

        assertEq(toVictim, 80e6, "80% to the victim");
        assertEq(toPool, 20e6, "20% to the pool");
        assertEq(token.balanceOf(victim) - victimBefore, 80e6);
        assertEq(vault.slashPool(), 20e6);
        assertEq(vault.bondAmount(v1), 900e6);
        assertEq(vault.totalBonded(), 900e6);
        assertEq(token.balanceOf(address(vault)), 920e6, "900 bond + 20 pool");
        assertEq(vault.solvencyGap(), 0);
        assertTrue(vault.isActive(v1), "still above minBond");
    }

    function testSlashBelowMinBondDeactivates() public {
        _stake(v1, 120e6);
        vm.prank(slasher);
        vault.slash(v1, victim, 30e6, keccak256("bad"));

        assertEq(vault.bondAmount(v1), 90e6);
        assertFalse(vault.isActive(v1), "below minBond must deactivate");
        assertTrue(vault.isRegistered(v1), "still registered, can re-stake");
    }

    function testSlashDeactivationEmitsEvent() public {
        _stake(v1, 120e6);
        vm.prank(slasher);
        vm.expectEmit(true, false, false, true, address(vault));
        emit VerifierDeactivated(v1, 90e6);
        vault.slash(v1, victim, 30e6, keccak256("bad"));
    }

    function testSlashCapsAtBondAndDrainsToZero() public {
        _stake(v1, 150e6);
        vm.prank(slasher);
        (uint256 toVictim, uint256 toPool) = vault.slash(v1, victim, 999e6, keccak256("bad"));

        assertEq(toVictim, 120e6);
        assertEq(toPool, 30e6);
        assertEq(vault.bondAmount(v1), 0);
        assertEq(vault.totalBonded(), 0);
        assertFalse(vault.isActive(v1));
    }

    function testSlashOnEmptyBondReverts() public {
        _stake(v1, 150e6);
        vm.prank(slasher);
        vault.slash(v1, victim, 150e6, keccak256("bad"));
        vm.prank(slasher);
        vm.expectRevert(KarmaVerifierBond.InsufficientBond.selector);
        vault.slash(v1, victim, 1, keccak256("bad"));
    }

    function testSlashZeroAmountReverts() public {
        _stake(v1, MIN_BOND);
        vm.prank(slasher);
        vm.expectRevert(KarmaVerifierBond.InvalidAmount.selector);
        vault.slash(v1, victim, 0, keccak256("bad"));
    }

    function testSlashUnknownVerifierReverts() public {
        vm.prank(slasher);
        vm.expectRevert(KarmaVerifierBond.NotRegistered.selector);
        vault.slash(stranger, victim, 1e6, keccak256("bad"));
    }

    function testOnlySlasherCanSlash() public {
        _stake(v1, FUNDED);
        vm.prank(stranger);
        vm.expectRevert(KarmaVerifierBond.Unauthorized.selector);
        vault.slash(v1, victim, 1e6, keccak256("bad"));
    }

    function testZeroVictimRoutesEverythingToPool() public {
        _stake(v1, FUNDED);
        vm.prank(slasher);
        (uint256 toVictim, uint256 toPool) = vault.slash(v1, address(0), 100e6, keccak256("bad"));
        assertEq(toVictim, 0);
        assertEq(toPool, 100e6);
        assertEq(vault.slashPool(), 100e6);
    }

    function testCustomSplitRespected() public {
        vm.prank(admin);
        vault.setSlashSplit(5_000);

        _stake(v1, FUNDED);
        vm.prank(slasher);
        (uint256 toVictim, uint256 toPool) = vault.slash(v1, victim, 100e6, keccak256("bad"));
        assertEq(toVictim, 50e6);
        assertEq(toPool, 50e6);
    }

    function testSetSlashSplitBoundsAndAuth() public {
        vm.prank(admin);
        vault.setSlashSplit(10_000);
        assertEq(vault.victimShareBps(), 10_000);

        vm.prank(admin);
        vm.expectRevert(KarmaVerifierBond.InvalidConfig.selector);
        vault.setSlashSplit(10_001);

        vm.prank(stranger);
        vm.expectRevert(KarmaVerifierBond.Unauthorized.selector);
        vault.setSlashSplit(1_000);
    }

    // ────────────────────────────────────────────────────── cooldown exit

    function testUnstakeCooldownGatesWithdrawal() public {
        _stake(v1, 300e6);

        vm.prank(v1);
        vault.requestUnstake(300e6);

        vm.prank(v1);
        vm.expectRevert(
            abi.encodeWithSelector(KarmaVerifierBond.CooldownActive.selector, block.timestamp + COOLDOWN)
        );
        vault.withdrawUnstake();

        vm.warp(block.timestamp + COOLDOWN);
        vm.prank(v1);
        vault.withdrawUnstake();

        assertEq(token.balanceOf(v1), FUNDED, "full bond returned after cooldown");
        assertEq(vault.totalBonded(), 0);
        assertFalse(vault.isActive(v1), "full exit deactivates");
    }

    function testPendingUnbondIsStillSlashableDuringCooldown() public {
        _stake(v1, 500e6);

        vm.prank(v1);
        vault.requestUnstake(500e6);

        vm.prank(slasher);
        vault.slash(v1, victim, 200e6, keccak256("bad"));
        assertEq(vault.bondAmount(v1), 300e6);

        vm.warp(block.timestamp + COOLDOWN);
        uint256 before = token.balanceOf(v1);
        vm.prank(v1);
        vault.withdrawUnstake();

        assertEq(token.balanceOf(v1) - before, 300e6, "withdraw is clamped to the remaining bond");
        assertEq(vault.totalBonded(), 0);
        assertEq(vault.solvencyGap(), 0);
    }

    function testWithdrawWithoutRequestReverts() public {
        _stake(v1, MIN_BOND);
        vm.prank(v1);
        vm.expectRevert(KarmaVerifierBond.UnstakingNotRequested.selector);
        vault.withdrawUnstake();
    }

    function testRequestUnstakeRejectsOverBond() public {
        _stake(v1, MIN_BOND);
        vm.prank(v1);
        vm.expectRevert(KarmaVerifierBond.InvalidAmount.selector);
        vault.requestUnstake(MIN_BOND + 1);
    }

    function testPartialExitKeepsActiveWhenAboveMinBond() public {
        _stake(v1, 300e6);
        vm.prank(v1);
        vault.requestUnstake(150e6);
        vm.warp(block.timestamp + COOLDOWN);
        vm.prank(v1);
        vault.withdrawUnstake();

        assertEq(vault.bondAmount(v1), 150e6);
        assertTrue(vault.isActive(v1), "still above minBond");
    }

    // ─────────────────────────────────────────────────────── pool payout

    function _fundPool(uint256 slashAmount) internal {
        _stake(v1, FUNDED);
        vm.prank(slasher);
        vault.slash(v1, victim, slashAmount, keccak256("bad"));
    }

    function _winners3() internal view returns (address[] memory w) {
        w = new address[](3);
        w[0] = v2;
        w[1] = v3;
        w[2] = v4;
    }

    function testDistributePoolSplitsEquallyAndDrains() public {
        _fundPool(300e6); // pool = 60e6
        assertEq(vault.slashPool(), 60e6);
        assertTrue(vault.poolReady());

        vm.prank(admin);
        vault.distributePool(_winners3(), 60e6);

        assertEq(token.balanceOf(v2), FUNDED + 20e6);
        assertEq(token.balanceOf(v3), FUNDED + 20e6);
        assertEq(token.balanceOf(v4), FUNDED + 20e6);
        assertEq(vault.slashPool(), 0);
        assertEq(vault.solvencyGap(), 0);
        assertEq(token.balanceOf(address(vault)), 700e6, "only the remaining bond stays");
    }

    function testDistributePoolGivesRemainderToLastWinner() public {
        _fundPool(500e6); // pool = 100e6
        vm.prank(admin);
        vault.distributePool(_winners3(), 100e6);

        // 100e6 / 3 = 33_333_333 each, remainder 1 to the last winner.
        assertEq(token.balanceOf(v2), FUNDED + 33_333_333);
        assertEq(token.balanceOf(v3), FUNDED + 33_333_333);
        assertEq(token.balanceOf(v4), FUNDED + 33_333_334, "remainder goes to the last winner");
        assertEq(vault.slashPool(), 0);
    }

    function testDistributePoolBlockedBelowThreshold() public {
        _fundPool(100e6); // pool = 20e6 < 50e6
        assertFalse(vault.poolReady());
        vm.prank(admin);
        vm.expectRevert(
            abi.encodeWithSelector(KarmaVerifierBond.PoolUnderThreshold.selector, 20e6, POOL_THRESHOLD)
        );
        vault.distributePool(_winners3(), 20e6);
    }

    function testDistributePoolCannotExceedPool() public {
        _fundPool(300e6); // pool = 60e6
        vm.prank(admin);
        vm.expectRevert(
            abi.encodeWithSelector(KarmaVerifierBond.PoolInsolvent.selector, 100e6, 60e6)
        );
        vault.distributePool(_winners3(), 100e6);
    }

    function testDistributePoolOnlyAdmin() public {
        _fundPool(300e6);
        vm.prank(stranger);
        vm.expectRevert(KarmaVerifierBond.Unauthorized.selector);
        vault.distributePool(_winners3(), 60e6);
    }

    function testDistributePoolNoWinnersReverts() public {
        _fundPool(300e6);
        address[] memory none = new address[](0);
        vm.prank(admin);
        vm.expectRevert(KarmaVerifierBond.NoWinners.selector);
        vault.distributePool(none, 60e6);
    }

    function testDistributePoolNeverTouchesBonds() public {
        _fundPool(500e6); // bond 500e6, pool 100e6
        vm.prank(admin);
        vault.distributePool(_winners3(), 100e6);

        assertEq(vault.totalBonded(), 500e6, "bonds are untouched by pool payout");
        assertEq(vault.bondAmount(v1), 500e6);
        assertEq(token.balanceOf(address(vault)), 500e6);
    }

    // ───────────────────────────────────────────────────── config / views

    function testSetTokenBlockedOnceFunded() public {
        _stake(v1, MIN_BOND);
        MockERC20 other = new MockERC20();
        vm.prank(admin);
        vm.expectRevert(KarmaVerifierBond.InvalidConfig.selector);
        vault.setToken(address(other));
    }

    function testConfigSettersRequireAdmin() public {
        vm.startPrank(stranger);
        vm.expectRevert(KarmaVerifierBond.Unauthorized.selector);
        vault.setSlasher(stranger);
        vm.expectRevert(KarmaVerifierBond.Unauthorized.selector);
        vault.setStakeConfig(1, 1, 1);
        vm.expectRevert(KarmaVerifierBond.Unauthorized.selector);
        vault.setToken(address(token));
        vm.stopPrank();
    }

    function testConstructorRejectsZeroAdmin() public {
        vm.expectRevert(KarmaVerifierBond.InvalidAddress.selector);
        new KarmaVerifierBond(address(0), address(token), 1);
    }

    // ───────────────────────────────────────────────────────── fuzz / invariant

    function testFuzz_slashNeverExceedsBondOrVictimShare(uint96 raw) public {
        uint256 stakeAmount = 300e6;
        _stake(v1, stakeAmount);
        uint256 amount = (uint256(raw) % (stakeAmount * 2)) + 1;

        uint256 victimBefore = token.balanceOf(victim);
        vm.prank(slasher);
        vault.slash(v1, victim, amount, keccak256("fuzz"));

        uint256 paid = token.balanceOf(victim) - victimBefore;
        assertLe(paid, amount, "victim never receives more than the slash");
        assertLe(vault.slashPool(), amount, "pool never exceeds the slash");
        assertLe(vault.bondAmount(v1), stakeAmount, "bond never increases");
        assertEq(vault.solvencyGap(), 0, "vault must stay solvent");
        assertLe(vault.totalBonded() + vault.slashPool(), token.balanceOf(address(vault)));
    }

    function testFuzz_poolPayoutNeverPaysMoreThanPool(uint96 raw) public {
        _fundPool(500e6); // pool = 100e6
        uint256 amount = (uint256(raw) % 100e6) + 1;

        vm.prank(admin);
        vault.distributePool(_winners3(), amount);

        assertEq(vault.solvencyGap(), 0);
        assertEq(vault.totalBonded(), 500e6);
    }
}