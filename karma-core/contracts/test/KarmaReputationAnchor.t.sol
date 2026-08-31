// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {KarmaReputationAnchor} from "../core/KarmaReputationAnchor.sol";

contract KarmaReputationAnchorTest is Test {
    KarmaReputationAnchor internal anchor;
    address internal party = address(0xB0B);
    address internal other = address(0xA11);

    function setUp() public {
        anchor = new KarmaReputationAnchor(address(this));
    }

    function testPackBelowMinReverts() public {
        vm.expectRevert(KarmaReputationAnchor.ScoreTooLow.selector);
        anchor.pack(party, 19_999, 10, bytes32(uint256(1)));
    }

    function testPackAndDividend() public {
        anchor.pack(party, 30_000, 12, keccak256("snap"));
        (uint256 scoreE2,,,,,, uint256 weight, bool packed) = _tuple(party);
        assertTrue(packed);
        assertEq(scoreE2, 30_000);
        assertEq(weight, 300);
        assertTrue(anchor.isDividendEligible(party));
    }

    function testSlashFreezesDividendUntilRehab() public {
        anchor.pack(party, 40_000, 20, keccak256("a"));
        anchor.slash(party, 15_000, keccak256("fraud"));
        assertFalse(anchor.isDividendEligible(party));
        vm.warp(block.timestamp + 90 days);
        // still below dividend min until re-pack
        assertFalse(anchor.isDividendEligible(party));
        anchor.pack(party, 31_000, 25, keccak256("rehab"));
        assertTrue(anchor.isDividendEligible(party));
    }

    function testStrangerCannotPack() public {
        vm.prank(other);
        vm.expectRevert(KarmaReputationAnchor.Unauthorized.selector);
        anchor.pack(party, 25_000, 10, bytes32(0));
    }

    function _tuple(address a)
        internal
        view
        returns (
            uint256,
            uint256,
            uint256,
            bytes32,
            uint256,
            bytes32,
            uint256,
            bool
        )
    {
        return anchor.packedOf(a);
    }
}
