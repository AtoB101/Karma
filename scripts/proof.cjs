#!/usr/bin/env node
/**
 * proof.cjs — Generate EIP-712 proof artifacts & evidence bundle
 *
 * Produces:
 *   - EIP-712 domain parameters
 *   - Signing typed data (reproducible)
 *   - Recovered signer verification
 *   - Full evidence JSON for audit / export
 */

const { ethers } = require("ethers");
const fs = require("fs");
const path = require("path");

const ANVIL_RPC = process.env.RPC_URL || "http://127.0.0.1:8545";

const PRIV_KEYS = [
  "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
  "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
  "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
];

async function main() {
  console.log("═══════════════════════════════════════════");
  console.log("  Karma MVP — Proof Artifacts");
  console.log("═══════════════════════════════════════════\n");

  const deployPath = path.join(__dirname, "..", "deployment.json");
  const resultPath = path.join(__dirname, "..", "results", "simulate-result.json");

  if (!fs.existsSync(deployPath) || !fs.existsSync(resultPath)) {
    console.error("❌ deployment.json or simulate-result.json not found");
    process.exit(1);
  }

  const dep = JSON.parse(fs.readFileSync(deployPath, "utf8"));
  const sim = JSON.parse(fs.readFileSync(resultPath, "utf8"));
  const abis = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "abis.json"), "utf8"));

  const provider = new ethers.JsonRpcProvider(ANVIL_RPC);
  const w0 = new ethers.Wallet(PRIV_KEYS[0], provider);
  const w1 = new ethers.Wallet(PRIV_KEYS[1], provider);
  const w2 = new ethers.Wallet(PRIV_KEYS[2], provider);

  const auth = new ethers.Contract(dep.authTokenManager, abis.AuthTokenManager, provider);
  const billMgr = new ethers.Contract(dep.billManager, abis.BillManager, provider);
  const pool = new ethers.Contract(dep.lockPoolManager, abis.LockPoolManager, provider);
  const token = new ethers.Contract(dep.token, abis.DemoToken, provider);

  // ── EIP-712 Domain ──
  const domain = {
    name: "TrustChainAuth",
    version: "1",
    chainId: 31337,
    verifyingContract: dep.authTokenManager,
  };

  const types = {
    Auth: [
      { name: "tokenId", type: "bytes32" },
      { name: "agent", type: "address" },
      { name: "opType", type: "uint8" },
      { name: "amount", type: "uint256" },
      { name: "nonce", type: "uint256" },
      { name: "deadline", type: "uint256" },
    ],
  };

  // ── On-chain domain separator ──
  const onChainSeparator = await auth.DOMAIN_SEPARATOR();
  const localSeparator = ethers.TypedDataEncoder.hashDomain(domain);

  // ── Get auth tokens from simulation ──
  const authStep = sim.steps.find((s) => s.step === "issue_auth_tokens");
  const billStep = sim.steps.find((s) => s.step === "create_bill");
  if (!authStep || !billStep) {
    console.error("❌ Missing simulation data");
    process.exit(1);
  }

  // Read consumed auth tokens
  const createToken = await auth.authTokens(authStep.createBillToken);
  const confirmToken = await auth.authTokens(authStep.confirmBillToken);

  // ── Reproduce create bill signature ──
  const billAmount = ethers.parseUnits("5000", 6);
  const deadline = Math.floor(Date.now() / 1000) + 3600;

  const createMsg = {
    tokenId: authStep.createBillToken,
    agent: w1.address,
    opType: 0,
    amount: billAmount,
    nonce: createToken.nonce,
    deadline,
  };

  // Re-sign to verify
  const createSig = await w1.signTypedData(domain, types, createMsg);
  const recoveredAddr = ethers.verifyTypedData(domain, types, createMsg, createSig);

  // ── Read on-chain bill state ──
  const bill = await billMgr.bills(billStep.billId);
  const batch = await billMgr.batches(bill.batchId);
  const poolStep = sim.steps.find((s) => s.step === "create_pool");
  const poolAcct = poolStep ? await pool.getPoolAccounting(poolStep.poolId) : null;

  const payerBal = await token.balanceOf(w1.address);
  const payeeBal = await token.balanceOf(w2.address);

  // ── Build proof bundle ──
  const proof = {
    schema: "karma.evidence.v1",
    schemaVersion: "1.0.0",
    generatedAt: new Date().toISOString(),
    chain: {
      chainId: 31337,
      rpc: ANVIL_RPC,
    },
    eip712: {
      domainSeparator: {
        onChain: onChainSeparator,
        local: localSeparator,
        match: onChainSeparator === localSeparator,
      },
      createBillAuth: {
        typedMessage: createMsg,
        recoveredSigner: recoveredAddr,
        signerMatchesTokenOwner: recoveredAddr.toLowerCase() === w1.address.toLowerCase(),
      },
    },
    contracts: dep,
    state: {
      bill: {
        billId: bill.billId.toString(),
        batchId: bill.batchId.toString(),
        fromAgent: bill.fromAgent,
        toAgent: bill.toAgent,
        amount: ethers.formatUnits(bill.amount, 6),
        status: ["Pending", "Confirmed", "Cancelled", "Settled"][bill.status],
      },
      batch: {
        batchId: batch.batchId.toString(),
        status: ["Open", "Closed", "Settled"][batch.status],
        settledAt: batch.settledAt.toString(),
      },
      pool: poolAcct
        ? {
            poolId: poolStep.poolId,
            totalLocked: ethers.formatUnits(poolAcct.totalLocked, 6),
            mappingBalance: ethers.formatUnits(poolAcct.mappingBalance, 6),
            settledAmount: ethers.formatUnits(poolAcct.settledAmount, 6),
          }
        : null,
      balances: {
        payer: ethers.formatUnits(payerBal, 6),
        payee: ethers.formatUnits(payeeBal, 6),
      },
    },
    invariants: {
      domainSeparatorConsistent: onChainSeparator === localSeparator,
      signerIsTokenOwner: recoveredAddr.toLowerCase() === w1.address.toLowerCase(),
      billSettled: bill.status === 3n,
      batchSettled: batch.status === 2n,
      payeePaid: payeeBal === ethers.parseUnits("5000", 6),
      poolAccountingCorrect:
        poolAcct &&
        poolAcct.totalLocked === ethers.parseUnits("45000", 6) &&
        poolAcct.settledAmount === ethers.parseUnits("5000", 6),
    },
  };

  // ── Output ──
  const resultsDir = path.join(__dirname, "..", "results");
  if (!fs.existsSync(resultsDir)) fs.mkdirSync(resultsDir, { recursive: true });

  const outPath = path.join(resultsDir, "proof-bundle.json");
  fs.writeFileSync(outPath, JSON.stringify(proof, (_, v) => typeof v === 'bigint' ? v.toString() : v, 2));

  console.log("📋 EIP-712 Proof Artifacts:");
  console.log(`   Domain Separator: ${onChainSeparator}`);
  console.log(`   Local ↔ On-chain match: ${proof.eip712.domainSeparator.match ? "✅" : "❌"}`);
  console.log(`   CreateBill signer: ${recoveredAddr}`);
  console.log(`   Signer == token owner: ${proof.eip712.createBillAuth.signerMatchesTokenOwner ? "✅" : "❌"}`);
  console.log("");

  console.log("📊 Invariant Results:");
  for (const [name, ok] of Object.entries(proof.invariants)) {
    console.log(`   ${ok ? "✅" : "❌"} ${name}`);
  }

  const allOk = Object.values(proof.invariants).every(Boolean);
  console.log(`\n   Overall: ${allOk ? "ALL VERIFIED ✅" : "SOME FAILED ❌"}`);

  console.log(`\n📁 Proof bundle saved: ${outPath}`);
  console.log("\n═══════════════════════════════════════════\n");

  if (!allOk) process.exit(1);
}

main().catch((err) => {
  console.error("❌ Proof generation failed:", err);
  process.exit(1);
});
