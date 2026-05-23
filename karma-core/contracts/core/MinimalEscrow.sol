// SPDX-License-Identifier: MIT
pragma solidity ^0.8.28;

/// @title MinimalEscrow — Karma testnet escrow with native ETH
/// @notice Simple immutable escrow for Sepolia E2E demo
contract MinimalEscrow {
    address public immutable admin;

    enum TaskState { NONE, FUNDED, RELEASED, REFUNDED }

    struct EscrowEntry {
        uint256 amount;
        address buyer;
        address seller;
        TaskState state;
        uint256 fundedAt;
    }

    mapping(bytes32 => EscrowEntry) public tasks;

    event Deposited(bytes32 indexed taskId, address buyer, address seller, uint256 amount);
    event Released(bytes32 indexed taskId, address seller, uint256 amount);
    event Refunded(bytes32 indexed taskId, address buyer, uint256 amount);

    constructor(address _admin) {
        admin = _admin;
    }

    function deposit(bytes32 taskId, address seller) external payable {
        require(tasks[taskId].state == TaskState.NONE, "already exists");
        require(msg.value > 0, "no ETH");
        require(seller != address(0), "invalid seller");

        tasks[taskId] = EscrowEntry({
            amount: msg.value,
            buyer: msg.sender,
            seller: seller,
            state: TaskState.FUNDED,
            fundedAt: block.timestamp
        });

        emit Deposited(taskId, msg.sender, seller, msg.value);
    }

    function release(bytes32 taskId) external {
        EscrowEntry storage entry = tasks[taskId];
        require(entry.state == TaskState.FUNDED, "not funded");
        require(msg.sender == entry.buyer, "only buyer");

        entry.state = TaskState.RELEASED;
        (bool ok, ) = entry.seller.call{value: entry.amount}("");
        require(ok, "transfer failed");

        emit Released(taskId, entry.seller, entry.amount);
    }

    function refund(bytes32 taskId) external {
        EscrowEntry storage entry = tasks[taskId];
        require(entry.state == TaskState.FUNDED, "not funded");
        require(msg.sender == entry.buyer, "only buyer");

        entry.state = TaskState.REFUNDED;
        (bool ok, ) = entry.buyer.call{value: entry.amount}("");
        require(ok, "transfer failed");

        emit Refunded(taskId, entry.buyer, entry.amount);
    }
}
