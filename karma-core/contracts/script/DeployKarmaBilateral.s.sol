// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Script, console} from "forge-std/Script.sol";
import {KarmaBilateral}          from "../core/KarmaBilateral.sol";
import {KarmaAttestationGateway} from "../core/KarmaAttestationGateway.sol";
import {VerifierRegistry}        from "../core/VerifierRegistry.sol";
import {ScoringEngine}           from "../core/ScoringEngine.sol";
import {EvidenceChain}           from "../core/EvidenceChain.sol";
import {CircuitBreaker}          from "../core/CircuitBreaker.sol";
import {EmergencyFreeze}         from "../core/EmergencyFreeze.sol";
import {KarmaReputationAnchor}   from "../core/KarmaReputationAnchor.sol";
import {KarmaIdentityRegistry}   from "../core/KarmaIdentityRegistry.sol";
import {KarmaFeeBridge}          from "../core/KarmaFeeBridge.sol";
import {AdminTimelock}           from "../core/AdminTimelock.sol";
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
///   ARBITRATOR_ADDRESS     address authorized to resolve attestation challenges
///
/// Admin is always a multisig-governed AdminTimelock (no single EOA).
///   TIMELOCK_OWNERS        JSON array of owner addresses, e.g. ["0x..","0x.."]
///   TIMELOCK_THRESHOLD     N in N-of-M owners (default: 1; >= 2 on mainnet)
///   TIMELOCK_DELAY         timelock delay in seconds (default: 0; > 0 on mainnet)
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
///   FEE_BPS                 fee rate in basis points (default: 50 = 0.5%)
///   SPLIT_TREASURY          treasury parts out of 10 (default: 3)
///   SPLIT_VERIFIER          verifier-pool parts out of 10 (default: 3)
///   SPLIT_BUYBACK           buyback parts out of 10 (default: 2)
///   SPLIT_DEVELOPER         developer parts out of 10 (default: 2)
///   TREASURY_ADDRESS        fee treasury / slash recipient (default: admin)
///   BUYBACK_ADDRESS         token buyback operator (default: admin)
///   DEVELOPER_ADDRESS       developer reward recipient (default: admin)
///
/// Base Sepolia USDC: 0x036CbD53842c5426634e7929541eC2318f3dCF7e
contract DeployKarmaBilateral is Script {

    address internal constant BASE_USDC        = 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913;
    address internal constant BASE_SEPOLIA_USDC = 0x036CbD53842c5426634e7929541eC2318f3dCF7e;

    /// @dev Known testnet chain IDs. Unknown chains are treated as mainnet
    ///      (fail-safe) so a typo cannot bypass the multisig guard.
    function _isTestnet(uint256 chainId) internal pure returns (bool) {
        return chainId == 84532      // Base Sepolia
            || chainId == 11155111   // Ethereum Sepolia
            || chainId == 11155420   // OP Sepolia
            || chainId == 421614     // Arbitrum Sepolia
            || chainId == 80002      // Polygon Amoy
            || chainId == 97         // BSC Testnet
            || chainId == 31337;     // local foundry
    }

    function _singleton(address a) internal pure returns (address[] memory out) {
        out = new address[](1);
        out[0] = a;
    }

    /// @dev Schedule + execute a timelock action. Valid while the timelock is in
    ///      its bootstrap state (single owner, threshold 1, zero delay).
    function _tl(AdminTimelock tl, address target, bytes memory data) internal {
        bytes32 id = tl.schedule(target, 0, data);
        tl.execute(id);
    }

    function run() external {
        uint256 deployerKey   = vm.envUint("DEPLOYER_PRIVATE_KEY");
        address arbitrator    = vm.envOr("ARBITRATOR_ADDRESS", vm.addr(deployerKey));

        // ── Admin: multisig-governed timelock (replaces single-EOA admin) ─
        // Bootstrap as deployer-only / threshold 1 / zero delay so this
        // script can wire the stack atomically; reconfigured to the final
        // multisig config at the end via self-governance.
        address[] memory tlOwners;
        if (vm.envExists("TIMELOCK_OWNERS")) {
            tlOwners = vm.parseJsonAddressArray(vm.envString("TIMELOCK_OWNERS"), "$");
        } else {
            tlOwners = _singleton(vm.addr(deployerKey));
        }
        uint256 tlThreshold = vm.envOr("TIMELOCK_THRESHOLD", uint256(1));
        uint256 tlDelay     = vm.envOr("TIMELOCK_DELAY",     uint256(0));
        uint256 gwDelay     = vm.envOr("GATEWAY_CHANGE_DELAY", uint256(0));

        // SECURITY: AdminTimelock is deployed AFTER startBroadcast below. Creating
        // it before startBroadcast leaves the on-chain admin as a dead, code-less
        // address, silently no-op'ing every _tl() wiring call.
        AdminTimelock tl;
        address admin;
        bool    useMock       = vm.envOr("USE_MOCK_TOKEN",     false);
        address testProvider  = vm.envOr("TEST_PROVIDER",      address(0));
        address testBuyer     = vm.envOr("TEST_BUYER",         address(0));

        // ── MAINNET GUARD ────────────────────────────────────────────────────
        // SECURITY: admin is the immutable AdminTimelock. On any non-testnet
        // chain the FINAL multisig config must be non-trivial: threshold >= 2
        // and a positive delay. A threshold-1 / zero-delay timelock would be
        // equivalent to a single EOA.
        if (!_isTestnet(block.chainid)) {
            require(tlThreshold >= 2,
                "MAINNET GUARD: TIMELOCK_THRESHOLD must be >= 2");
            require(tlDelay > 0,
                "MAINNET GUARD: TIMELOCK_DELAY must be > 0");
            require(tlOwners.length >= tlThreshold,
                "MAINNET GUARD: not enough TIMELOCK_OWNERS for threshold");
            require(arbitrator.code.length > 0,
                "MAINNET GUARD: ARBITRATOR_ADDRESS must be a multisig contract, not an EOA");
            require(gwDelay > 0,
                "MAINNET GUARD: GATEWAY_CHANGE_DELAY must be > 0");
            console.log("[MAINNET GUARD] timelock multisig + arbitrator + gateway delay verified");
        }

        uint256 batchThreshold  = vm.envOr("BATCH_THRESHOLD",    uint256(1_000_000_000));
        uint256 disputeWindow   = vm.envOr("DISPUTE_WINDOW",     uint256(1_800));
        uint256 settleTimeout   = vm.envOr("SETTLE_TIMEOUT",     uint256(604_800));
        uint256 challengeWindow = vm.envOr("CHALLENGE_WINDOW",   uint256(3_600));
        uint256 verifierN       = vm.envOr("VERIFIER_THRESHOLD", uint256(3));
        uint256 verifierM       = vm.envOr("VERIFIER_TOTAL",     uint256(5));

        address paymentToken;

        vm.startBroadcast(deployerKey);

        // ── AdminTimelock (deployed here so it is actually broadcast) ──────
        tl = new AdminTimelock(_singleton(vm.addr(deployerKey)), 1, 0);
        admin = address(tl);

        // Fee bridge: 0.5% fee split 3/3/2/2 (treasury / verifier / buyback / developer).
        address treasury   = vm.envOr("TREASURY_ADDRESS",   admin);
        address buyback    = vm.envOr("BUYBACK_ADDRESS",    admin);
        address developer  = vm.envOr("DEVELOPER_ADDRESS",  admin);
        uint256 feeBps     = vm.envOr("FEE_BPS",            uint256(50));
        uint256 splitT     = vm.envOr("SPLIT_TREASURY",     uint256(3));
        uint256 splitV     = vm.envOr("SPLIT_VERIFIER",     uint256(3));
        uint256 splitB     = vm.envOr("SPLIT_BUYBACK",      uint256(2));
        uint256 splitD     = vm.envOr("SPLIT_DEVELOPER",    uint256(2));
        uint256 minRepScore  = vm.envOr("MIN_REPUTATION_SCORE", uint256(0));
        uint256 challengeStake = vm.envOr("CHALLENGE_STAKE",   uint256(0));

        console.log("=== Karma Protocol Full Stack Deployment ===");
        console.log("Chain ID             ", block.chainid);
        console.log("Deployer             ", vm.addr(deployerKey));
        console.log("Admin                ", admin);
        console.log("Arbitrator           ", arbitrator);
        console.log("Attestation N-of-M   ", verifierN);
        console.log("Challenge window     ", challengeWindow);

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
        _tl(tl, address(registry), abi.encodeCall(VerifierRegistry.setThresholds, (verifierN, verifierM)));
        _tl(tl, address(registry), abi.encodeCall(VerifierRegistry.setStakingConfig, (paymentToken, 100_000_000, 10_000_000)));

        // ── 2. EvidenceChain ──────────────────────────────────────────────────
        EvidenceChain evidence = new EvidenceChain(admin);

        // ── 3. ScoringEngine ──────────────────────────────────────────────────
        ScoringEngine scoring = new ScoringEngine(admin);

        // ── 4. KarmaBilateral ─────────────────────────────────────────────────
        KarmaBilateral karma = new KarmaBilateral(admin);
        _tl(tl, address(karma), abi.encodeCall(KarmaBilateral.setTokenAllowed, (paymentToken, true)));
        _tl(tl, address(karma), abi.encodeCall(KarmaBilateral.setBatchThreshold, (paymentToken, batchThreshold)));
        _tl(tl, address(karma), abi.encodeCall(KarmaBilateral.setSettleDelay, (disputeWindow)));
        _tl(tl, address(karma), abi.encodeCall(KarmaBilateral.setSettleTimeout, (settleTimeout)));
        _tl(tl, address(scoring), abi.encodeCall(ScoringEngine.setAuthorizedSettler, (address(karma))));
        _tl(tl, address(scoring), abi.encodeCall(ScoringEngine.setVerifierRegistry, (address(registry))));

        // Fee bridge wiring: pull 0.5% of every settled pool and split it.
        KarmaFeeBridge feeBridge = new KarmaFeeBridge(admin);
        _tl(tl, address(feeBridge), abi.encodeCall(KarmaFeeBridge.setCore, (address(karma))));
        _tl(tl, address(feeBridge), abi.encodeCall(KarmaFeeBridge.setToken, (paymentToken)));
        _tl(tl, address(feeBridge), abi.encodeCall(KarmaFeeBridge.setFeeBps, (feeBps)));
        _tl(tl, address(feeBridge), abi.encodeCall(KarmaFeeBridge.setSplit, (splitT, splitV, splitB, splitD)));
        _tl(tl, address(feeBridge), abi.encodeCall(KarmaFeeBridge.setDestinations, (treasury, address(registry), buyback, developer)));
        _tl(tl, address(karma), abi.encodeCall(KarmaBilateral.setFeeBridge, (address(feeBridge))));
        _tl(tl, address(registry), abi.encodeCall(VerifierRegistry.setSlashRecipient, (treasury)));
        // P2-7: fee bridge credits the registry reward pool (separate from stake).
        _tl(tl, address(registry), abi.encodeCall(VerifierRegistry.setRewardAllocator, (address(feeBridge))));
        _tl(tl, address(registry), abi.encodeCall(VerifierRegistry.setScoringEngine, (address(scoring))));
        // P2-8: reputation gate source + minimum agent score (0 disables).
        _tl(tl, address(karma), abi.encodeCall(KarmaBilateral.setScoringEngine, (address(scoring))));
        _tl(tl, address(karma), abi.encodeCall(KarmaBilateral.setMinReputationScore, (minRepScore)));

        CircuitBreaker breaker = new CircuitBreaker(admin);
        EmergencyFreeze freeze = new EmergencyFreeze(admin);
        _tl(tl, address(freeze), abi.encodeCall(EmergencyFreeze.setCircuitBreaker, (address(breaker))));
        _tl(tl, address(karma), abi.encodeCall(KarmaBilateral.setEmergencyGuard, (address(freeze))));

        KarmaReputationAnchor reputationAnchor = new KarmaReputationAnchor(admin);
        KarmaIdentityRegistry identityRegistry = new KarmaIdentityRegistry(address(karma));

        // ── 5. KarmaAttestationGateway ────────────────────────────────────────
        KarmaAttestationGateway gateway = new KarmaAttestationGateway(
            address(registry),
            address(karma),
            arbitrator,
            challengeWindow
        );

        // ── 6. Wire ───────────────────────────────────────────────────────────
        _tl(tl, address(karma), abi.encodeCall(KarmaBilateral.setAttestationGateway, (address(gateway))));
        // Gateway replacement delay: 0 on testnet (fast re-point for E2E),
        // > 0 enforced by the mainnet guard above.
        _tl(tl, address(karma), abi.encodeCall(KarmaBilateral.setGatewayChangeDelay, (gwDelay)));
        // Privilege: only Gateway may recordAttestation / rewardVerifier
        _tl(tl, address(registry), abi.encodeCall(VerifierRegistry.setAuthorizedCaller, (address(gateway), true)));

        // P2-9: anti-grief challenge stake (only the arbitrator may configure it).
        if (challengeStake > 0) {
            if (arbitrator != vm.addr(deployerKey)) {
                console.log("WARN: CHALLENGE_STAKE set but arbitrator != deployer; skipping setChallengeStake");
            } else {
                gateway.setChallengeStake(paymentToken, challengeStake);
                console.log("Challenge stake configured ", challengeStake, " ", paymentToken);
            }
        }

        // ── Reconfigure timelock to the final multisig config ─────────────
        if (tlDelay != 0 || tlThreshold != 1 ||
            tlOwners.length != 1 || tlOwners[0] != vm.addr(deployerKey)) {
            _tl(tl, address(tl), abi.encodeCall(AdminTimelock.reconfigure, (tlOwners, tlThreshold, tlDelay)));
            console.log("Timelock reconfigured: owners/threshold/delay applied");
        }

        vm.stopBroadcast();

        // ── Post-deploy sanity checks ─────────────────────────────────────────
        require(karma.admin()                 == admin,           "karma admin mismatch");
        require(karma.tokenAllowed(paymentToken),                 "token not allowlisted");
        require(karma.attestationGateway()    == address(gateway), "gateway not wired");
        require(karma.feeBridge()             == address(feeBridge), "fee bridge not wired");
        require(registry.slashRecipient()     == treasury, "slash recipient not wired");
        require(gateway.bilateralContract()   == address(karma),  "bilateral not wired");
        require(address(gateway.registry())   == address(registry), "registry not wired");
        require(registry.authorizedCallers(address(gateway)),     "gateway not authorized on registry");
        require(registry.rewardAllocator()      == address(feeBridge), "reward allocator not wired");
        require(karma.scoringEngine()           == address(scoring),   "scoring engine not wired");
        require(karma.minReputationScore()      == minRepScore,        "reputation gate not wired");
        require(registry.getRequiredThreshold() == verifierN,     "threshold mismatch");
        require(scoring.admin()               == admin,           "scoring admin");
        require(scoring.verifierRegistry()      == address(registry), "scoring registry not wired");
        require(registry.scoringEngine()        == address(scoring),  "registry scoring not wired");
        require(evidence.admin()              == admin,           "evidence admin");
        require(karma.emergencyGuard()        == address(freeze), "freeze guard not wired");
        require(freeze.circuitBreaker()       == address(breaker), "breaker not wired");
        require(reputationAnchor.admin()      == admin,           "reputation anchor admin");
        require(identityRegistry.bilateral()   == address(karma), "identity registry not wired");
        require(karma.checkInvariant(paymentToken),               "invariant broken at deploy");

        // ── Output ────────────────────────────────────────────────────────────
        console.log("");
        console.log("=== Deployed Addresses ===");
        console.log("TIMELOCK  ", address(tl));
        console.log("TOKEN     ", paymentToken);
        console.log("REGISTRY  ", address(registry));
        console.log("EVIDENCE  ", address(evidence));
        console.log("SCORING   ", address(scoring));
        console.log("BREAKER   ", address(breaker));
        console.log("FREEZE    ", address(freeze));
        console.log("REP_ANCHOR", address(reputationAnchor));
        console.log("IDENTITY   ", address(identityRegistry));
        console.log("KARMA     ", address(karma));
        console.log("GATEWAY   ", address(gateway));
        console.log("FEE_BRIDGE", address(feeBridge));
        console.log("TREASURY  ", treasury);
        console.log("BUYBACK   ", buyback);
        console.log("DEVELOPER ", developer);
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
        console.log("KARMA_REPUTATION_ANCHOR_ADDRESS=");
        console.log(address(reputationAnchor));
        console.log("");
        console.log("=== Verify on Basescan ===");
        console.log("chain 84532 --etherscan-api-key $BASESCAN_API_KEY");
        console.log(address(registry));
        console.log(address(evidence));
        console.log(address(scoring));
        console.log(address(karma));
        console.log(address(gateway));
        console.log(address(feeBridge));
        if (useMock) {
            console.log(paymentToken);
        }
    }
}
