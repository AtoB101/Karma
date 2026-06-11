// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {KarmaBilateral}          from "../core/KarmaBilateral.sol";
import {KarmaAttestationGateway} from "../core/KarmaAttestationGateway.sol";
import {VerifierRegistry}        from "../core/VerifierRegistry.sol";
import {ScoringEngine}           from "../core/ScoringEngine.sol";
import {EvidenceChain}           from "../core/EvidenceChain.sol";
import {MockERC20}               from "../test/mocks/MockERC20.sol";

/// @notice Deploy the full Karma protocol stack to Base Sepolia (or any EVM chain).
///
/// Two modes:
///   A) USE_MOCK_TOKEN=true  -> deploys MockERC20, mints 1M tokens to test accounts
///   B) USE_MOCK_TOKEN=false -> uses USDC on target chain (default: Base Sepolia)
///
/// Usage:
///   # Mode A: Mock token (fast test, no faucet needed)
///   export USE_MOCK_TOKEN=true
///   export TEST_PROVIDER=0x...
///   export TEST_BUYER=0x...
///
///   # Mode B: Real USDC
///   export USDC_ADDRESS=0x036CbD53842c5426634e7929541eC2318f3dCF7e
///
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
///
/// Optional env vars:
///   USE_MOCK_TOKEN          set to "true" to deploy MockERC20 instead of USDC
///   USDC_ADDRESS            USDC token address (default: Base Sepolia)
///   TEST_PROVIDER           provider address for mock token minting
///   TEST_BUYER              buyer address for mock token minting
///   BATCH_THRESHOLD         (default: 1_000_000_000 = 1000 USDC at 6 decimals)
///   DISPUTE_WINDOW          bilateral dispute window in seconds (default: 1800)
///   SETTLE_TIMEOUT          bilateral settle timeout in seconds (default: 604800)
///   CHALLENGE_WINDOW        gateway challenge window in seconds (default: 3600)
///   VERIFIER_THRESHOLD      N in N-of-M (default: 3)
///   VERIFIER_TOTAL          M in N-of-M (default: 5)
///
/// Base Sepolia USDC: 0x036CbD53842c5426634e7929541eC2318f3dCF7e
contract DeployKarmaBilateral is Script {

    address internal constant BASE_USDC        = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address internal constant BASE_SEPOLIA_USDC = 0x036CbD53842c5426634e7929541eC2318f3dCF7e;

    function run() external {
        uint256 deployerKey   = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address admin         = vm.envOr("ADMIN_ADDRESS",      vm.addr(deployerKey));
        address arbitrator    = vm.envOr("ARBITRATOR_ADDRESS", admin);
        bool    useMock       = vm.envOr("USE_MOCK_TOKEN",     false);
        address testProvider  = vm.envOr("TEST_PROVIDER",      address(0));
        address testBuyer     = vm.envOr("TEST_BUYER",         address(0));

        uint256 batchThreshold  = vm.envOr("BATCH_THRESHOLD",    uint256(1_000_000_000));
        uint256 disputeWindow   = vm.envOr("DISPUTE_WINDOW",     uint256(1_800));
        uint256 settleTimeout   = vm.envOr("SETTLE_TIMEOUT",     uint256(604_800));
        uint256 challengeWindow = vm.envOr("CHALLENGE_WINDOW",   uint256(3_600));
        uint256 verifierN       = vm.envOr("VERIFIER_THRESHOLD", uint256(3));
        uint256 verifierM       = vm.envOr("VERIFIER_TOTAL",     uint256(5));

        console.log("=== Karma Protocol Full Stack Deployment ===");
        console.log("Chain ID             ", block.chainid);
        console.log("Deployer             ", vm.addr(deployerKey));
        console.log("Admin                ", admin);
        console.log("Arbitrator           ", arbitrator);
        console.log("Attestation N-of-M   ", verifierN);
        console.log("Challenge window     ", challengeWindow);

        address paymentToken;

        vm.startBroadcast(deployerKey);

        // ── 0. Token (MockERC20 or USDC) ──────────────────────────────────────
        if (useMock) {
            console.log("--- MockERC20 Deployment ---");
            MockERC20 mockToken = new MockERC20();
            paymentToken = address(mockToken);

            // Mint 1M tokens (6 decimals -> 1_000_000_000_000 = 1M)
            uint256 mintAmount = 1_000_000_000_000_000;
            mockToken.mint(vm.addr(deployerKey), mintAmount);
            console.log("MockToken             ", paymentToken);
            console.log("Minted to deployer    ", mintAmount);

            if (testProvider != address(0)) {
                mockToken.mint(testProvider, mintAmount);
                console.log("Minted to provider    ", testProvider);
            }
            if (testBuyer != address(0)) {
                mockToken.mint(testBuyer, mintAmount);
                console.log("Minted to buyer       ", testBuyer);
            }
        } else {
            paymentToken = vm.envOr("USDC_ADDRESS", BASE_SEPOLIA_USDC);
            console.log("--- Real USDC ---");
            console.log("USDC                  ", paymentToken);
        }

        // ── 1. VerifierRegistry ───────────────────────────────────────────────
        VerifierRegistry registry = new VerifierRegistry(admin);
        registry.setThresholds(verifierN, verifierM);
        registry.setStakingConfig(paymentToken, 100_000_000, 10_000_000);

        // ── 2. EvidenceChain ──────────────────────────────────────────────────
        EvidenceChain evidence = new EvidenceChain(admin);

        // ── 3. ScoringEngine ──────────────────────────────────────────────────
        ScoringEngine scoring = new ScoringEngine(admin);

        // ── 4. KarmaBilateral ─────────────────────────────────────────────────
        KarmaBilateral karma = new KarmaBilateral(admin);
        karma.setTokenAllowed(paymentToken, true);
        karma.setBatchThreshold(paymentToken, batchThreshold);
        karma.setDisputeWindow(disputeWindow);
        karma.setSettleTimeout(settleTimeout);
        scoring.setAuthorizedSettler(address(karma));

        // ── 5. KarmaAttestationGateway ────────────────────────────────────────
        KarmaAttestationGateway gateway = new KarmaAttestationGateway(
            address(registry),
            address(karma),
            arbitrator,
            challengeWindow
        );

        // ── 6. Wire ───────────────────────────────────────────────────────────
        karma.setAttestationGateway(address(gateway));

        vm.stopBroadcast();

        // ── Post-deploy sanity checks ─────────────────────────────────────────
        require(karma.admin()                 == admin,           "karma admin mismatch");
        require(karma.tokenAllowed(paymentToken),                 "token not allowlisted");
        require(karma.attestationGateway()    == address(gateway), "gateway not wired");
        require(gateway.bilateralContract()   == address(karma),  "bilateral not wired");
        require(address(gateway.registry())   == address(registry), "registry not wired");
        require(registry.getRequiredThreshold() == verifierN,     "threshold mismatch");
        require(scoring.admin()               == admin,           "scoring admin");
        require(evidence.admin()              == admin,           "evidence admin");
        require(karma.checkInvariant(paymentToken),               "invariant broken at deploy");

        // ── Output ────────────────────────────────────────────────────────────
        console.log("");
        console.log("=== Deployed Addresses ===");
        console.log("TOKEN     ", paymentToken);
        console.log("REGISTRY  ", address(registry));
        console.log("EVIDENCE  ", address(evidence));
        console.log("SCORING   ", address(scoring));
        console.log("KARMA     ", address(karma));
        console.log("GATEWAY   ", address(gateway));
        console.log("");
        console.log("=== Env Vars for SDK ===");
        console.log("PAYMENT_TOKEN=");
        console.log(paymentToken);
        console.log("REGISTRY=");
        console.log(address(registry));
        console.log("EVIDENCE=");
        console.log(address(evidence));
        console.log("SCORING=");
        console.log(address(scoring));
        console.log("KARMA=");
        console.log(address(karma));
        console.log("GATEWAY=");
        console.log(address(gateway));
        console.log("");
        console.log("=== Verify on Basescan ===");
        console.log("chain 84532 --etherscan-api-key $BASESCAN_API_KEY");
        console.log(address(registry));
        console.log(address(evidence));
        console.log(address(scoring));
        console.log(address(karma));
        console.log(address(gateway));
        if (useMock) {
            console.log(paymentToken);
        }
    }
}
