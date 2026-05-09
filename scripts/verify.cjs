#!/usr/bin/env node
/**
 * verify.cjs — On-chain state verification
 *
 * Reads deployment.json + simulate-result.json, then queries chain
 * to verify all invariants and expected state transitions.
 */

const { ethers } = require("ethers");
const fs = require("fs");
const path = require("path");

const ANVIL_RPC = process.env.RPC_URL || "http://127.0.0.1:8545";

async function main() {
  console.log("═══════════════════════════════════════════");
  console.log("  Karma MVP — On-Chain Verification");
  console.log("═══════════════════════════════════════════\n");

  const deployPath = path.join(__dirname, "..", "deployment.json");
  const resultPath = path.join(__dirname, "..", "results", "simulate-result.json");

  if (!fs.existsSync(deployPath)) {
    console.error("❌ deployment.json not found");
    process.exit(1);
  }
  if (!fs.existsSync(resultPath)) {
    console.error("❌ results/simulate-result.json not found. Run simulate first.");
    process.exit(1);
  }

  const dep = JSON.parse(fs.readFileSync(deployPath, "utf8"));
  const simResult = JSON.parse(fs.readFileSync(resultPath, "utf8"));
  const abis = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "abis.json"), "utf8"));

  const provider = new ethers.JsonRpcProvider(ANVIL_RPC);

  const billMgr = new ethers.Contract(dep.billManager, abis.BillManager, provider);
  const pool = new ethers.Contract(dep.lockPoolManager, abis.LockPoolManager, provider);
  const auth = new ethers.Contract(dep.authTokenManager, abis.AuthTokenManager, provider);
  const kya = new ethers.Contract(dep.kyaRegistry, abis.KYARegistry, provider);
  const token = new ethers.Contract(dep.token, abis.DemoToken, provider);
  const breaker = new ethers.Contract(dep.circuitBreaker, abis.CircuitBreaker, provider);

  const checks = [];
  let passed = 0;
  let failed = 0;

  function check(name, condition, detail) {
    if (condition) {
      console.log(`   ✅ ${name}: ${detail || "OK"}`);
      passed++;
    } else {
      console.log(`   ❌ ${name}: ${detail || "FAILED"}`);
      failed++;
    }
    checks.push({ name, passed: condition, detail });
  }

  // ── Circuit Breaker: not paused ──
  const globalPaused = await breaker.isGlobalPaused();
  check("CircuitBreaker.globalPaused == false", !globalPaused);

  // ── DIDs active ──
  const PRIV_KEYS = [
    "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",
    "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",
    "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",
  ];
  const w0 = new ethers.Wallet(PRIV_KEYS[0], provider);
  const w1 = new ethers.Wallet(PRIV_KEYS[1], provider);
  const w2 = new ethers.Wallet(PRIV_KEYS[2], provider);

  const [p1ok] = await kya.verifyDID(w1.address);
  const [p2ok] = await kya.verifyDID(w2.address);
  check("Payer DID active", p1ok);
  check("Payee DID active", p2ok);

  // ── Simulation step checks ──
  const lastStep = simResult.steps[simResult.steps.length - 1];
  check("Simulation completed all steps", simResult.steps.length >= 7);

  // ── Bill state ──
  const createStep = simResult.steps.find((s) => s.step === "create_bill");
  if (createStep && createStep.billId) {
    const bill = await billMgr.bills(createStep.billId);
    check("Bill status is Settled (3)", bill.status === 3n, `status=${bill.status}`);

    // Batch should be settled
    const batch = await billMgr.batches(bill.batchId);
    check("Batch status is Settled (2)", batch.status === 2n, `status=${batch.status}`);
  }

  // ── Pool accounting ──
  const poolStep = simResult.steps.find((s) => s.step === "create_pool");
  if (poolStep && poolStep.poolId) {
    const acct = await pool.getPoolAccounting(poolStep.poolId);

    // Pool should have 45000 remaining (50000 - 5000 settled)
    const expLocked = ethers.parseUnits("45000", 6);
    check("Pool totalLocked == 45000 sUSDC", acct.totalLocked === expLocked,
      `${ethers.formatUnits(acct.totalLocked, 6)} sUSDC`);

    check("Pool pendingAmount == 0", acct.pendingAmount === 0n,
      `${ethers.formatUnits(acct.pendingAmount, 6)} sUSDC`);

    check("Pool settledAmount == 5000 sUSDC", acct.settledAmount === ethers.parseUnits("5000", 6),
      `${ethers.formatUnits(acct.settledAmount, 6)} sUSDC`);
  }

  // ── Token balances ──
  const payeeBal = await token.balanceOf(w2.address);
  const expPayee = ethers.parseUnits("5000", 6);
  check("Payee received 5000 sUSDC", payeeBal === expPayee,
    `${ethers.formatUnits(payeeBal, 6)} sUSDC`);

  // ── Auth tokens consumed ──
  const authStep = simResult.steps.find((s) => s.step === "issue_auth_tokens");
  if (authStep) {
    const ct = await auth.authTokens(authStep.createBillToken);
    const cf = await auth.authTokens(authStep.confirmBillToken);
    check("CreateBill token consumed", ct.used === true);
    check("ConfirmBill token consumed", cf.used === true);
  }

  // ── Deployer owns contracts ──
  const breakerAdmin = await breaker.admin();
  check("CircuitBreaker admin is deployer", breakerAdmin.toLowerCase() === w0.address.toLowerCase());

  // ── Summary ──
  const total = passed + failed;
  const summary = {
    timestamp: new Date().toISOString(),
    total,
    passed,
    failed,
    success: failed === 0,
    checks,
  };

  const outPath = path.join(__dirname, "..", "results", "verify-result.json");
  fs.writeFileSync(outPath, JSON.stringify(summary, null, 2));

  console.log(`\n📊 Results: ${passed}/${total} passed`);
  if (failed > 0) {
    console.log(`   ❌ ${failed} verification checks FAILED`);
  } else {
    console.log("   ✅ All verification checks passed!");
  }
  console.log(`📁 Saved: ${outPath}`);
  console.log("\n═══════════════════════════════════════════\n");

  if (failed > 0) process.exit(1);
}

main().catch((err) => {
  console.error("❌ Verification failed:", err);
  process.exit(1);
});
