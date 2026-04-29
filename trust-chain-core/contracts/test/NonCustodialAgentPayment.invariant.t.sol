// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {StdInvariant} from "forge-std/StdInvariant.sol";
import {NonCustodialAgentPayment} from "../core/NonCustodialAgentPayment.sol";
import {MockERC20} from "./mocks/MockERC20.sol";

contract NonCustodialAgentPaymentHandler is Test {
    NonCustodialAgentPayment public protocol;
    MockERC20 public token;
    address public buyer;
    address public seller;
    uint256[] public billIds;

    constructor(NonCustodialAgentPayment _p, MockERC20 _t, address _b, address _s) {
        protocol = _p;
        token = _t;
        buyer = _b;
        seller = _s;
    }

    function lockFunds(uint256 amount) public {
        amount = bound(amount, 1, 50_000);
        vm.prank(buyer);
        try protocol.lockFunds(address(token), amount) {} catch {}
    }

    function createBill(uint256 amount) public returns (uint256) {
        amount = bound(amount, 1, 10_000);
        vm.prank(buyer);
        try
            protocol.createBill(
                seller,
                address(token),
                amount,
                keccak256("scope"),
                "ipfs://inv-proof",
                block.timestamp + 1 days
            )
        returns (uint256 id) {
            billIds.push(id);
            return id;
        } catch {}
        return 0;
    }

    function confirmBill(uint256 seed) public {
        if (billIds.length == 0) return;
        uint256 idx = seed % billIds.length;
        vm.prank(buyer);
        try protocol.confirmBill(billIds[idx]) {} catch {}
    }

    function cancelBill(uint256 seed) public {
        if (billIds.length == 0) return;
        uint256 idx = seed % billIds.length;
        vm.prank(buyer);
        try protocol.cancelBill(billIds[idx]) {} catch {}
    }

    function expireBill(uint256 seed) public {
        if (billIds.length == 0) return;
        uint256 idx = seed % billIds.length;
        vm.warp(block.timestamp + 2 days);
        try protocol.expireBill(billIds[idx]) {} catch {}
    }
}

contract NonCustodialAgentPaymentInvariantTest is StdInvariant, Test {
    NonCustodialAgentPayment internal protocol;
    MockERC20 internal token;
    address internal buyer;
    address internal seller;
    address internal arbitrator;

    function setUp() public {
        buyer = makeAddr("buyer");
        seller = makeAddr("seller");
        arbitrator = makeAddr("arbitrator");

        protocol = new NonCustodialAgentPayment(arbitrator, 3000, 1 days);
        token = new MockERC20();

        token.mint(buyer, 1_000_000);
        token.mint(seller, 1_000_000);
        vm.prank(buyer);
        token.approve(address(protocol), type(uint256).max);
        vm.prank(seller);
        token.approve(address(protocol), type(uint256).max);

        vm.prank(buyer);
        protocol.lockFunds(address(token), 100_000);
        vm.prank(seller);
        protocol.lockFunds(address(token), 100_000);

        NonCustodialAgentPaymentHandler handler = new NonCustodialAgentPaymentHandler(protocol, token, buyer, seller);
        targetContract(address(handler));
    }

    function invariant_active_plus_reserved_equals_locked() public {
        assertTrue(protocol.isAccountConsistent(buyer, address(token)));
        assertTrue(protocol.isAccountConsistent(seller, address(token)));
    }
}
