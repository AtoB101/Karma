// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console2} from "forge-std/Script.sol";
import {DemoToken} from "../core/DemoToken.sol";
import {KYARegistry} from "../core/KYARegistry.sol";
import {LockPoolManager} from "../core/LockPoolManager.sol";
import {AuthTokenManager} from "../core/AuthTokenManager.sol";
import {CircuitBreaker} from "../core/CircuitBreaker.sol";
import {BillManager} from "../core/BillManager.sol";

contract DeployDemo is Script {
    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_KEY");
        address deployer = vm.addr(deployerKey);
        vm.startBroadcast(deployerKey);

        DemoToken token = new DemoToken();
        KYARegistry kya = new KYARegistry();
        LockPoolManager lockPool = new LockPoolManager(address(kya));
        AuthTokenManager auth = new AuthTokenManager();
        CircuitBreaker breaker = new CircuitBreaker(deployer);
        BillManager bill = new BillManager(address(lockPool), address(kya), address(breaker), address(auth));
        lockPool.setBillManager(address(bill));

        vm.stopBroadcast();

        // Build JSON string manually
        string memory json = string(
            abi.encodePacked(
                '{"token":"', vm.toString(address(token)),
                '","kyaRegistry":"', vm.toString(address(kya)),
                '","lockPoolManager":"', vm.toString(address(lockPool)),
                '","authTokenManager":"', vm.toString(address(auth)),
                '","circuitBreaker":"', vm.toString(address(breaker)),
                '","billManager":"', vm.toString(address(bill)),
                '","deployer":"', vm.toString(deployer),
                '"}'
            )
        );

        console2.log("DEPLOY_JSON_START");
        console2.log(string(json));
        console2.log("DEPLOY_JSON_END");
    }
}
