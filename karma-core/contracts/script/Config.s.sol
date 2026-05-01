// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

contract Config {
    address public admin;

    constructor(address admin_) {
        admin = admin_;
    }
}
