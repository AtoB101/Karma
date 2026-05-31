// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {NonCustodialAgentPayment} from "../core/NonCustodialAgentPayment.sol";

contract ReentrantToken {
    string public name = "Reentrant";
    string public symbol = "RNT";
    uint8 public decimals = 6;

    mapping(address => uint256) public balanceOf;
    mapping(address => mapping(address => uint256)) public allowance;

    NonCustodialAgentPayment public target;
    bool public shouldAttack;
    uint256 public attackBillId;
    uint16 public attackBuyerShareBps;

    function mint(address to, uint256 amount) external {
        balanceOf[to] += amount;
    }

    function approve(address spender, uint256 amount) external returns (bool) {
        allowance[msg.sender][spender] = amount;
        return true;
    }

    function configureAttack(address _target, uint256 _billId, uint16 _bps) external {
        target = NonCustodialAgentPayment(_target);
        attackBillId = _billId;
        attackBuyerShareBps = _bps;
        shouldAttack = true;
    }

    function transferFrom(address from, address to, uint256 amount) external returns (bool) {
        if (balanceOf[from] < amount) return false;
        if (allowance[from][msg.sender] < amount) return false;
        allowance[from][msg.sender] -= amount;
        balanceOf[from] -= amount;
        balanceOf[to] += amount;
        if (shouldAttack && address(target) != address(0)) {
            shouldAttack = false;
            target.resolveDisputeSplit(attackBillId, attackBuyerShareBps);
        }
        return true;
    }
}

contract NonCustodialAgentPaymentReentrancyTest is Test {
    NonCustodialAgentPayment internal protocol;
    ReentrantToken internal token;

    uint256 internal buyerPk = 0xB0B;
    uint256 internal sellerPk = 0xCAFE;
    uint256 internal arbitratorPk = 0xA11CE;

    address internal buyer;
    address internal seller;
    address internal arbitrator;

    function setUp() public {
        buyer = vm.addr(buyerPk);
        seller = vm.addr(sellerPk);
        arbitrator = vm.addr(arbitratorPk);

        token = new ReentrantToken();
        protocol = new NonCustodialAgentPayment(arbitrator, 3000, 1 days);

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
    }

    function testReentrancyAttackOnResolveDisputeSplit() public {
        vm.prank(buyer);
        uint256 billId = protocol.createBill(
            seller, address(token), 10_000, keccak256("scope"), "ipfs://reentrant-proof", block.timestamp + 1 days
        );
        vm.prank(buyer);
        protocol.confirmBill(billId);
        vm.prank(seller);
        protocol.disputeBill(billId);

        token.configureAttack(address(protocol), billId, 2000);

        vm.prank(arbitrator);
        vm.expectRevert(NonCustodialAgentPayment.Reentrancy.selector);
        protocol.resolveDisputeSplit(billId, 5000);

        assertTrue(protocol.isAccountConsistent(buyer, address(token)));
        assertTrue(protocol.isAccountConsistent(seller, address(token)));
    }
}
