// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {SettlementEngine} from "../core/SettlementEngine.sol";

contract DeployV01 {
    function run(address admin) external returns (address engine) {
        engine = address(new SettlementEngine(admin));
    }
}
