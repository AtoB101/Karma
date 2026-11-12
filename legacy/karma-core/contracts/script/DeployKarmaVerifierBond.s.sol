// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {KarmaVerifierBond} from "../core/KarmaVerifierBond.sol";

/// @notice 部署验证者质押金库（G12）。
///
/// 为什么单独一份脚本
/// ------------------
/// 金库是**主网硬前置**：没有它，「去中心化验证」就没有经济安全 —— 节点作恶
/// 没有钱被划走。所以它必须能在测试网**独立部署、独立验证**，跑稳了再谈主网。
///
/// 权限守卫
/// --------
/// 测试网（Base Sepolia / Ethereum Sepolia / OP Sepolia / Arbitrum Sepolia /
/// Polygon Amoy / BSC Testnet / 本地 31337）：``admin`` 可以是部署者 EOA。
/// 非测试网：**admin 与 slasher 必须是合约钱包**（Safe / 多签 / 时间锁）——
/// admin 能改 ``minBond`` / 罚没分账 / 分池，slasher 能划走任何节点的保证金，
/// 单个 EOA 私钥泄露 = 整个验证网络的经济安全归零。
///
/// 用法：
///   export DEPLOYER_PRIVATE_KEY=0x...
///   export ADMIN_ADDRESS=0x...              # 生产：多签
///   export BOND_TOKEN_ADDRESS=0x...         # USDC（测试网可用 MockERC20）
///   export VERIFIER_MIN_BOND=100000000      # 100 USDC（6 位小数）
///   export VERIFIER_BOND_SLASHER=0x...      # 省略 = admin
///   export VERIFIER_UNBOND_COOLDOWN=259200  # 3 天
///   export VERIFIER_MIN_POOL_PAYOUT=50000000 # 50 USDC 起奖线
///   forge script karma-core/contracts/script/DeployKarmaVerifierBond.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC --broadcast --verify
contract DeployKarmaVerifierBond is Script {
    /// @dev 已知测试网链 ID。未知链按主网处理（fail-safe），免得手滑绕过守卫。
    function _isTestnet(uint256 chainId) internal pure returns (bool) {
        return chainId == 84532      // Base Sepolia
            || chainId == 11155111   // Ethereum Sepolia
            || chainId == 11155420   // OP Sepolia
            || chainId == 421614     // Arbitrum Sepolia
            || chainId == 80002      // Polygon Amoy
            || chainId == 97         // BSC Testnet
            || chainId == 31337;     // local foundry
    }

    function run() external {
        uint256 deployerKey = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address admin = vm.envOr("ADMIN_ADDRESS", vm.addr(deployerKey));
        address token = vm.envAddress("BOND_TOKEN_ADDRESS");
        address slasher = vm.envOr("VERIFIER_BOND_SLASHER", admin);
        uint256 minBond = vm.envOr("VERIFIER_MIN_BOND", uint256(0));
        uint256 cooldown = vm.envOr("VERIFIER_UNBOND_COOLDOWN", uint256(3 days));
        uint256 minPoolPayout = vm.envOr("VERIFIER_MIN_POOL_PAYOUT", uint256(0));

        if (!_isTestnet(block.chainid)) {
            require(
                admin.code.length > 0,
                "MAINNET GUARD: ADMIN_ADDRESS must be a multisig contract (e.g. Safe), not an EOA"
            );
            require(
                slasher.code.length > 0,
                "MAINNET GUARD: VERIFIER_BOND_SLASHER must be a multisig contract, not an EOA"
            );
            require(
                minBond > 0,
                "MAINNET GUARD: VERIFIER_MIN_BOND must be > 0 (a zero floor makes the bond meaningless)"
            );
            console.log("[MAINNET GUARD] admin + slasher verified as contract wallets");
        }

        console.log("=== KarmaVerifierBond (G12) ===");
        console.log("chainId        ", block.chainid);
        console.log("admin          ", admin);
        console.log("slasher        ", slasher);
        console.log("token          ", token);
        console.log("minBond        ", minBond);
        console.log("unbondCooldown ", cooldown);
        console.log("minPoolPayout  ", minPoolPayout);

        vm.startBroadcast(deployerKey);
        KarmaVerifierBond vault = new KarmaVerifierBond(admin, token, minBond);
        // 只有 admin 就是部署者时才能顺手把参数配掉；生产里 admin 是多签，
        // 这一步必须由多签自己发交易 —— 所以这里显式提示，不假装配好了。
        if (admin == vm.addr(deployerKey)) {
            vault.setStakeConfig(minBond, cooldown, minPoolPayout);
            vault.setSlasher(slasher);
        }
        vm.stopBroadcast();

        console.log("KarmaVerifierBond", address(vault));
        if (admin != vm.addr(deployerKey)) {
            console.log(
                "ACTION REQUIRED: admin must call setStakeConfig(minBond, unbondCooldown, minPoolPayout) and setSlasher(slasher)"
            );
        }
    }
}