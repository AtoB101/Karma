/**
 * Karma Protocol — Full Flow Demo Script
 *
 * Runs against deployed contracts on any EVM chain.
 *
 * Usage:
 *   npx tsx examples/v02-full-flow-test.ts
 *
 * Required env vars:
 *   RPC_URL              Base Sepolia RPC
 *   DEPLOYER_KEY         Private key with admin role
 *   TOKEN_ADDR           Payment token (USDC or MockERC20)
 *   KARMA_ADDR           KarmaBilateral contract
 *   REGISTRY_ADDR        VerifierRegistry contract
 *   SCORING_ADDR         ScoringEngine contract
 *   EVIDENCE_ADDR        EvidenceChain contract
 *
 * Optional:
 *   PROVIDER_KEY         Provider private key (auto-generates if not set)
 *   BUYER_KEY            Buyer private key (auto-generates if not set)
 */

import { ethers } from "ethers";
import {
  KarmaBilateral,
  VerifierRegistry,
  ScoringEngine,
  EvidenceChain,
  type IntentPackage,
} from "../packages/karma-sdk/typescript/src/index.js";

// ── Config ────────────────────────────────────────────────────────────────────

const RPC          = process.env.RPC_URL!;
const DEPLOYER_KEY = process.env.DEPLOYER_KEY!;
const TOKEN        = process.env.TOKEN_ADDR!;
const KARMA_ADDR   = process.env.KARMA_ADDR!;
const REGISTRY     = process.env.REGISTRY_ADDR!;
const SCORING      = process.env.SCORING_ADDR!;
const EVIDENCE     = process.env.EVIDENCE_ADDR!;

// Generate test accounts or use provided ones
const provider = new ethers.JsonRpcProvider(RPC);
const deployer = new ethers.Wallet(DEPLOYER_KEY, provider);
const providerWallet = process.env.PROVIDER_KEY
  ? new ethers.Wallet(process.env.PROVIDER_KEY, provider)
  : ethers.Wallet.createRandom().connect(provider);
const buyerWallet = process.env.BUYER_KEY
  ? new ethers.Wallet(process.env.BUYER_KEY, provider)
  : ethers.Wallet.createRandom().connect(provider);

// ── Clients ───────────────────────────────────────────────────────────────────

const karma = new KarmaBilateral({
  rpc: RPC, privateKey: DEPLOYER_KEY, contract: KARMA_ADDR,
});
const vrf = new VerifierRegistry({
  rpc: RPC, privateKey: DEPLOYER_KEY, contract: REGISTRY,
});
const scoring = new ScoringEngine({
  rpc: RPC, privateKey: DEPLOYER_KEY, contract: SCORING,
});
const evidence = new EvidenceChain({
  rpc: RPC, privateKey: DEPLOYER_KEY, contract: EVIDENCE,
});

// Provider-side client
const karmaProvider = new KarmaBilateral({
  rpc: RPC, privateKey: providerWallet.privateKey, contract: KARMA_ADDR,
});
const karmaBuyer = new KarmaBilateral({
  rpc: RPC, privateKey: buyerWallet.privateKey, contract: KARMA_ADDR,
});

// ── Test Data ─────────────────────────────────────────────────────────────────

const SERVICE_TYPE = ethers.keccak256(ethers.toUtf8Bytes("flight_booking"));
const AMOUNT = 50_000_000n; // 50 USDC (6 decimals)
const NOW = BigInt(Math.floor(Date.now() / 1000));

const intent: IntentPackage = {
  buyer:               buyerWallet.address,
  seller:              providerWallet.address,
  serviceType:         SERVICE_TYPE,
  requirements:        "0x",    // empty for demo
  amount:              AMOUNT,
  penaltyRate:         500n,     // 5% penalty
  deadline:            NOW + 3600n,
  expiresAt:           NOW + 7200n,
  proofSchema:         ethers.keccak256(ethers.toUtf8Bytes("flight_completion")),
  requiredProofFields: [ethers.keccak256(ethers.toUtf8Bytes("flight_number")),
                         ethers.keccak256(ethers.toUtf8Bytes("departure_time"))],
  verifier:            deployer.address,  // deployer acts as verifier for demo
  disputeWindow:       300n,   // 5 min dispute window
  arbitrators:         [deployer.address],
};

// ── Main Flow ─────────────────────────────────────────────────────────────────

async function main() {
  console.log("=== Karma Protocol Full Flow Demo ===\n");
  console.log("Chain RPC:     ", RPC);
  console.log("Token:         ", TOKEN);
  console.log("KarmaBilateral:", KARMA_ADDR);
  console.log("Registry:      ", REGISTRY);
  console.log("Scoring:       ", SCORING);
  console.log("Evidence:      ", EVIDENCE);

  // ── Step 1: Fund test accounts ─────────────────────────────────────────────
  console.log("\n── Step 1: Fund test accounts ──");

  const tokenContract = new ethers.Contract(TOKEN, [
    "function transfer(address to, uint256 amount) returns (bool)",
    "function balanceOf(address) view returns (uint256)",
  ], deployer);

  // Check if test accounts have tokens (MockERC20 auto-mints to deployer only)
  const providerBal = await tokenContract.balanceOf(providerWallet.address);
  const buyerBal   = await tokenContract.balanceOf(buyerWallet.address);

  const fundAmount = AMOUNT + 10_000_000n; // extra for gas buffer
  if (providerBal < fundAmount) {
    console.log("Funding provider...");
    const tx = await tokenContract.transfer(providerWallet.address, fundAmount);
    await tx.wait();
  }
  if (buyerBal < fundAmount) {
    console.log("Funding buyer...");
    const tx = await tokenContract.transfer(buyerWallet.address, fundAmount);
    await tx.wait();
  }

  console.log("Provider balance:", await tokenContract.balanceOf(providerWallet.address));
  console.log("Buyer balance:   ", await tokenContract.balanceOf(buyerWallet.address));

  // ── Step 2: Register verifier ──────────────────────────────────────────────
  console.log("\n── Step 2: Register & stake verifier ──");

  try {
    const existing = await vrf.getVerifier(deployer.address);
    console.log("Verifier already registered:", existing.active);
  } catch {
    console.log("Registering verifier...");
    await vrf.registerVerifier(deployer.address, "https://demo-verifier.karma.dev");
  }

  // Check stake
  const vi = await vrf.getVerifier(deployer.address);
  const minStake = await vrf.minStake();
  if (vi.stakeAmount < minStake) {
    console.log("Staking", minStake.toString(), "tokens...");
    await vrf.stake(minStake);
  }
  console.log("Verifier active:", await vrf.isVerifierActive(deployer.address));

  // ── Step 3: Lock tokens ────────────────────────────────────────────────────
  console.log("\n── Step 3: Lock tokens (both sides) ──");

  const buyerBillId  = await karmaBuyer.lock(TOKEN, AMOUNT);
  const sellerBillId = await karmaProvider.lock(TOKEN, AMOUNT);

  console.log("Buyer bill: ", buyerBillId.toString());
  console.log("Seller bill:", sellerBillId.toString());

  const buyerBill = await karma.getBill(buyerBillId);
  console.log("Bill state:", buyerBill.state, "(0=MINTED)");

  // ── Step 4: bindWithIntent ─────────────────────────────────────────────────
  console.log("\n── Step 4: bindWithIntent ──");

  const bindingId = await karma.bindWithIntent(intent, buyerBillId, sellerBillId);
  console.log("Binding ID:", bindingId.toString());

  const binding = await karma.getBinding(bindingId);
  console.log("Binding state:", binding.state, "(0=ACTIVE/PENDING)");

  const stored = await karma.getIntentPackage(bindingId);
  console.log("Intent serviceType:", stored.serviceType);
  console.log("Intent amount:     ", stored.amount.toString());
  console.log("Intent verifier:   ", stored.verifier);

  // ── Step 5: Submit evidence ────────────────────────────────────────────────
  console.log("\n── Step 5: Submit on-chain evidence ──");

  const evidenceItem = {
    evidenceType: ethers.keccak256(ethers.toUtf8Bytes("flight_completion")),
    bindingId:    bindingId,
    submitter:    deployer.address,
    data:         ethers.toUtf8Bytes(JSON.stringify({
      flight_number: "CA1234",
      departure_time: "2026-06-11T10:00:00Z",
      actual_departure: "2026-06-11T10:05:00Z",
      passenger: buyerWallet.address,
    })),
    timestamp:    NOW + 100n,
    isValid:      true,
    hash:         ethers.ZeroHash,
  };
  const evHash = await evidence.submitEvidence(evidenceItem);
  console.log("Evidence tx:", evHash);

  const count = await evidence.getEvidenceCount(bindingId);
  console.log("Evidence count for binding:", count.toString());

  // ── Step 6: Wait for dispute window ─────────────────────────────────────────
  console.log("\n── Step 6: Wait for dispute window (", intent.disputeWindow.toString(), "s) ──");

  // For demo we just wait
  const waitSeconds = Number(intent.disputeWindow) + 2;
  console.log("Waiting", waitSeconds, "seconds...");
  await new Promise(r => setTimeout(r, waitSeconds * 1000));

  // ── Step 7: Settle ─────────────────────────────────────────────────────────
  console.log("\n── Step 7: Settle ──");

  const proofHash = ethers.keccak256(ethers.toUtf8Bytes("proof_of_completion"));
  const settleTx = await karma.settle(bindingId, proofHash);
  console.log("Settle tx:", settleTx);

  const finalBinding = await karma.getBinding(bindingId);
  console.log("Final state:", finalBinding.state, "(0=ACTIVE, 1=PENDING, 2=FINALIZING, 3=SETTLED)");

  // ── Step 8: Record scoring ─────────────────────────────────────────────────
  console.log("\n── Step 8: Record scoring ──");

  await scoring.recordSettlement(
    providerWallet.address,
    buyerWallet.address,
    deployer.address,  // verifier
    9500n,              // 95% on-time
  );

  const providerScore = await scoring.getScore(providerWallet.address);
  const buyerScore    = await scoring.getScore(buyerWallet.address);
  const verifierScore = await scoring.getScore(deployer.address);

  console.log("Provider reputation:", providerScore.reputationScore.toString(), "/ 10000");
  console.log("Buyer reputation:   ", buyerScore.reputationScore.toString(), "/ 10000");
  console.log("Verifier reputation:", verifierScore.reputationScore.toString(), "/ 10000");

  // ── Step 9: Verify invariant ────────────────────────────────────────────────
  console.log("\n── Step 9: Verify invariant ──");
  const invariantOk = await karma.checkInvariant(TOKEN);
  console.log("Invariant:", invariantOk ? "PASS" : "FAIL");

  console.log("\n=== Demo complete! ===");
}

main().catch(err => {
  console.error("Demo failed:", err);
  process.exit(1);
});
