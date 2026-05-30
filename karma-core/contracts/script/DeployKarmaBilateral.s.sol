// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {KarmaBilateral}          from "../core/KarmaBilateral.sol";
import {KarmaAttestationGateway} from "../core/KarmaAttestationGateway.sol";
import {VerifierRegistry}        from "../core/VerifierRegistry.sol";

/// @notice Deploy the full Karma protocol stack to Base Sepolia (or any EVM chain).
///
///  Deploys (in order):
///    1. VerifierRegistry
///    2. KarmaBilateral
///    3. KarmaAttestationGateway  (wired to Bilateral + Registry)
///    4. Wires KarmaBilateral → attestationGateway = address(Gateway)
///
/// Usage:
///   forge script karma-core/contracts/script/DeployKarmaBilateral.s.sol \
///     --rpc-url $BASE_SEPOLIA_RPC \
///     --broadcast \
///     --verify \
///     --etherscan-api-key $BASESCAN_API_KEY \
///     -vvvv
///
/// Required env vars:
///   DEPLOYER_PRIVATE_KEY   hex private key of deployer
///   ADMIN_ADDRESS          contract admin / owner (can be multisig)
///   ARBITRATOR_ADDRESS     address authorized to resolve attestation challenges
///   USDC_ADDRESS           USDC token address on target network
///
/// Optional env vars:
///   BATCH_THRESHOLD        (default: 1_000_000_000 = 1000 USDC at 6 decimals)
///   DISPUTE_WINDOW         bilateral dispute window in seconds (default: 1800)
///   SETTLE_TIMEOUT         bilateral settle timeout in seconds (default: 604800)
///   CHALLENGE_WINDOW       gateway challenge window in seconds (default: 3600)
///   VERIFIER_THRESHOLD     N in N-of-M (default: 3)
///   VERIFIER_TOTAL         M in N-of-M (default: 5)
///
/// Base Sepolia USDC: 0x036CbD53842c5426634e7929541eC2318f3dCF7e
contract DeployKarmaBilateral is Script {

    address internal constant BASE_USDC        = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address internal constant BASE_SEPOLIA_USDC = 0x036CbD53842c5426634e7929541eC2318f3dCF7e;

    function run() external {
        uint256 deployerKey   = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address admin         = vm.envOr("ADMIN_ADDRESS",      vm.addr(deployerKey));
        address arbitrator    = vm.envOr("ARBITRATOR_ADDRESS", admin);
        address usdc          = vm.envOr("USDC_ADDRESS",       BASE_SEPOLIA_USDC);

        uint256 batchThreshold  = vm.envOr("BATCH_THRESHOLD",    uint256(1_000_000_000));
        uint256 disputeWindow   = vm.envOr("DISPUTE_WINDOW",     uint256(1_800));
        uint256 settleTimeout   = vm.envOr("SETTLE_TIMEOUT",     uint256(604_800));
        uint256 challengeWindow = vm.envOr("CHALLENGE_WINDOW",   uint256(3_600));
        uint256 verifierN       = vm.envOr("VERIFIER_THRESHOLD", uint256(3));
        uint256 verifierM       = vm.envOr("VERIFIER_TOTAL",     uint256(5));

        console.log("=== Karma Protocol Full Stack Deployment ===");
        console.log("Chain ID:          ", block.chainid);
        console.log("Deployer:          ", vm.addr(deployerKey));
        console.log("Admin:             ", admin);
        console.log("Arbitrator:        ", arbitrator);
        console.log("USDC:              ", usdc);
        console.log("Attestation N-of-M:", verifierN, "of", verifierM);
        console.log("Challenge window:  ", challengeWindow, "seconds");

        vm.startBroadcast(deployerKey);

        // ── 1. VerifierRegistry ───────────────────────────────────────────────
        VerifierRegistry registry = new VerifierRegistry(admin);
        registry.setThresholds(verifierN, verifierM);

        // ── 2. KarmaBilateral ─────────────────────────────────────────────────
        KarmaBilateral karma = new KarmaBilateral(admin);
        karma.setTokenAllowed(usdc, true);
        karma.setBatchThreshold(usdc, batchThreshold);
        karma.setDisputeWindow(disputeWindow);
        karma.setSettleTimeout(settleTimeout);

        // ── 3. KarmaAttestationGateway ────────────────────────────────────────
        KarmaAttestationGateway gateway = new KarmaAttestationGateway(
            address(registry),
            address(karma),
            arbitrator,
            challengeWindow
        );

        // ── 4. Wire: KarmaBilateral accepts Gateway as trusted settler ─────────
        karma.setAttestationGateway(address(gateway));

        vm.stopBroadcast();

        // ── Post-deploy sanity checks ─────────────────────────────────────────
        require(karma.admin()                    == admin,              "karma admin mismatch");
        require(karma.tokenAllowed(usdc),                               "usdc not allowlisted");
        require(karma.attestationGateway()       == address(gateway),   "gateway not wired");
        require(gateway.bilateralContract()      == address(karma),     "bilateral not wired");
        require(address(gateway.registry())      == address(registry),  "registry not wired");
        require(registry.getRequiredThreshold()  == verifierN,          "threshold mismatch");
        require(karma.checkInvariant(usdc),                             "invariant broken at deploy");

        console.log("");
        console.log("=== Deployment successful ===");
        console.log("VerifierRegistry:        ", address(registry));
        console.log("KarmaBilateral:          ", address(karma));
        console.log("KarmaAttestationGateway: ", address(gateway));
        console.log("");
        console.log("Next steps:");
        console.log("  1. Set env: KARMA_CONTRACT=", address(karma));
        console.log("  2. Register verifier nodes via VerifierRegistry.registerVerifier()");
        console.log("  3. Update packages/karma-sdk and packages/karma-mcp with contract address");
        console.log("  4. Verify contracts on Basescan:");
        console.log("     forge verify-contract", address(registry),  "VerifierRegistry");
        console.log("     forge verify-contract", address(karma),     "KarmaBilateral");
        console.log("     forge verify-contract", address(gateway),   "KarmaAttestationGateway");
        console.log("");
        console.log("Protocol flows:");
        console.log("  Standard : lock -> bind -> settle (direct, dispute window applies)");
        console.log("  Attested : lock -> bindWithAttestation -> publishEvidence -> N*submitAttestation -> settleWithAttestation");
        console.log("  Invariant : PASS (totalBillSupply == totalLocked == 0)");
    }
}
