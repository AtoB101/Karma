// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {AdminTimelock} from "../core/AdminTimelock.sol";

contract MockTarget {
    uint256 public value;

    event Poked(uint256 value);

    function poke(uint256 v) external {
        value = v;
        emit Poked(v);
    }

    receive() external payable {}
}

contract AdminTimelockTest is Test {
    address internal owner1 = address(0x1);
    address internal owner2 = address(0x2);
    address internal owner3 = address(0x3);
    address internal stranger = address(0x99);

    function _owners2() internal view returns (address[] memory a) {
        a = new address[](2);
        a[0] = owner1;
        a[1] = owner2;
    }

    function _owners3() internal view returns (address[] memory a) {
        a = new address[](3);
        a[0] = owner1;
        a[1] = owner2;
        a[2] = owner3;
    }

    function _newTimelock(uint256 threshold, uint256 delay)
        internal
        returns (AdminTimelock tl)
    {
        tl = new AdminTimelock(_owners3(), threshold, delay);
    }

    function testConstructorState() public {
        AdminTimelock tl = _newTimelock(2, 1 days);
        assertEq(tl.threshold(), 2);
        assertEq(tl.minDelay(), 1 days);
        assertEq(tl.ownerCount(), 3);
        assertTrue(tl.isOwner(owner1));
        assertTrue(tl.isOwner(owner2));
        assertTrue(tl.isOwner(owner3));
    }

    function testConstructorRejectsZeroOwners() public {
        address[] memory none = new address[](0);
        vm.expectRevert(AdminTimelock.InvalidConfig.selector);
        new AdminTimelock(none, 1, 0);
    }

    function testConstructorRejectsZeroThreshold() public {
        vm.expectRevert(AdminTimelock.InvalidConfig.selector);
        new AdminTimelock(_owners3(), 0, 0);
    }

    function testConstructorRejectsThresholdOverOwners() public {
        vm.expectRevert(AdminTimelock.InvalidConfig.selector);
        new AdminTimelock(_owners3(), 4, 0);
    }

    function testConstructorRejectsDuplicateOwner() public {
        address[] memory dup = new address[](2);
        dup[0] = owner1;
        dup[1] = owner1;
        vm.expectRevert(AdminTimelock.InvalidConfig.selector);
        new AdminTimelock(dup, 1, 0);
    }

    function testScheduleExecuteSingleOwner() public {
        AdminTimelock tl = new AdminTimelock(_owners3(), 1, 0);
        MockTarget target = new MockTarget();

        vm.prank(owner1);
        bytes32 id = tl.schedule(address(target), 0, abi.encodeCall(MockTarget.poke, (42)));

        tl.execute(id);

        assertEq(target.value(), 42);
        (address t, uint256 v, bytes memory d, uint256 eta, uint256 appr, bool ex) = tl.actions(id);
        assertEq(t, address(target));
        assertEq(v, 0);
        assertGt(d.length, 0);
        assertEq(eta, block.timestamp);
        assertEq(appr, 1);
        assertTrue(ex);
        assertEq(tl.actionIds(0), id);
    }

    function testNonOwnerCannotSchedule() public {
        AdminTimelock tl = _newTimelock(1, 0);
        vm.prank(stranger);
        vm.expectRevert(AdminTimelock.NotOwner.selector);
        tl.schedule(address(0xdead), 0, "");
    }

    function testDelayEnforced() public {
        AdminTimelock tl = _newTimelock(1, 1 hours);
        MockTarget target = new MockTarget();

        vm.prank(owner1);
        bytes32 id = tl.schedule(address(target), 0, abi.encodeCall(MockTarget.poke, (7)));

        vm.expectRevert(abi.encodeWithSelector(AdminTimelock.NotReady.selector, block.timestamp + 1 hours));
        tl.execute(id);

        vm.warp(block.timestamp + 1 hours);
        tl.execute(id);
        assertEq(target.value(), 7);
    }

    function testThresholdEnforced() public {
        AdminTimelock tl = _newTimelock(2, 0);
        MockTarget target = new MockTarget();

        vm.prank(owner1);
        bytes32 id = tl.schedule(address(target), 0, abi.encodeCall(MockTarget.poke, (1)));

        vm.expectRevert(abi.encodeWithSelector(AdminTimelock.NotApproved.selector, 2, 1));
        tl.execute(id);

        vm.prank(owner2);
        tl.approve(id);

        tl.execute(id);
        assertEq(target.value(), 1);
    }

    function testDuplicateApproveReverts() public {
        AdminTimelock tl = _newTimelock(2, 0);
        vm.prank(owner1);
        bytes32 id = tl.schedule(address(0xdead), 0, "");

        vm.prank(owner1);
        vm.expectRevert(AdminTimelock.AlreadyApproved.selector);
        tl.approve(id);
    }

    function testCannotExecuteTwice() public {
        AdminTimelock tl = _newTimelock(1, 0);
        vm.prank(owner1);
        bytes32 id = tl.schedule(address(0xdead), 0, "");

        tl.execute(id);

        vm.expectRevert(AdminTimelock.AlreadyExecuted.selector);
        tl.execute(id);
    }

    function testCancelRequiresThreshold() public {
        AdminTimelock tl = _newTimelock(2, 0);
        vm.prank(owner1);
        bytes32 id = tl.schedule(address(0xdead), 0, "");

        // one owner cannot cancel a threshold-2 action
        vm.prank(owner1);
        vm.expectRevert(abi.encodeWithSelector(AdminTimelock.NotApproved.selector, 2, 1));
        tl.cancel(id);

        vm.prank(owner2);
        tl.approve(id);

        vm.prank(owner1);
        tl.cancel(id);

        (address t, uint256 v, bytes memory d, uint256 eta, uint256 appr, bool ex) = tl.actions(id);
        assertEq(t, address(0));
        assertEq(v, 0);
        assertEq(d.length, 0);
        assertEq(eta, 0);
        assertEq(appr, 0);
        assertFalse(ex);
    }

    function testSelfGovernanceReconfigure() public {
        AdminTimelock tl = _newTimelock(1, 0);

        // propose the reconfigure as owner1 (the sole approver, threshold 1)
        vm.prank(owner1);
        bytes32 id = tl.schedule(
            address(tl),
            0,
            abi.encodeCall(AdminTimelock.reconfigure, (_owners2(), 2, 1 days))
        );

        tl.execute(id);

        assertEq(tl.ownerCount(), 2);
        assertTrue(tl.isOwner(owner1));
        assertTrue(tl.isOwner(owner2));
        assertFalse(tl.isOwner(owner3));
        assertEq(tl.threshold(), 2);
        assertEq(tl.minDelay(), 1 days);
    }

    function testReconfigureOnlySelf() public {
        AdminTimelock tl = _newTimelock(1, 0);
        vm.prank(owner1);
        vm.expectRevert(AdminTimelock.NotOwner.selector);
        tl.setMinDelay(100);
    }

    function testScheduleIdsAreUnique() public {
        AdminTimelock tl = _newTimelock(1, 0);
        vm.startPrank(owner1);
        bytes32 a = tl.schedule(address(0xdead), 0, "");
        bytes32 b = tl.schedule(address(0xdead), 0, "");
        vm.stopPrank();
        assertTrue(a != b);
    }
}
