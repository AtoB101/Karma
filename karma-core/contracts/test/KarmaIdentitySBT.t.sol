// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaIdentitySBT} from "../core/KarmaIdentitySBT.sol";

contract KarmaIdentitySBTTest is Test {
    KarmaIdentitySBT internal sbt;
    address internal user = address(0xBEEF);
    address internal other = address(0xCAFE);

    function setUp() public {
        sbt = new KarmaIdentitySBT();
    }

    function testUserSelfMint() public {
        vm.prank(user);
        uint256 id = sbt.mintOrGet(user);
        assertEq(sbt.soulByOwner(user), id);
        assertEq(sbt.ownerOf(id), user);

        vm.prank(user);
        uint256 id2 = sbt.mintOrGet(user);
        assertEq(id, id2);
    }

    function testAdminMintForUser() public {
        uint256 id = sbt.mintOrGet(user);
        assertEq(sbt.ownerOf(id), user);
    }

    function testThirdPartyCannotMintForOther() public {
        vm.prank(other);
        vm.expectRevert(KarmaIdentitySBT.Unauthorized.selector);
        sbt.mintOrGet(user);
    }
}
