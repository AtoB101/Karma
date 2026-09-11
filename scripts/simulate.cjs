#!/usr/bin/env node
/**
 * simulate.cjs — Karma full E2E simulation
 *
 * Flow:
 *   1. Read deployment.json (written by forge script DeployDemo)
 *   2. Mint tokens → Payer
 *   3. Register DIDs for Payer & Payee
 *   4. Create LockPool (Payer deposits sUSDC)
 *   5. Issue AuthTokens for CreateBill & ConfirmBill
 *   6. Sign & submit CreateBill (EIP-712)
 *   7. Sign & submit ConfirmBill (EIP-712)
 *   8. CloseBatch + SettleBatch
 *   9. Verify final balances
 */

const { ethers } = require("ethers");
const fs = require("fs");
const path = require("path");

const ANVIL_RPC = process.env.RPC_URL || "http://127.0.0.1:8545";

// Anvil default accounts (index 0 = deployer/admin, 1 = payer, 2 = payee)
const PRIV_KEYS = [
  "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80", // #0 deployer/admin
  "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d", // #1 payer
  "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a", // #2 payee
];

async function main() {
  console.log("═══════════════════════════════════════════");
  console.log("  Karma MVP — E2E Simulation");
  console.log("═══════════════════════════════════════════\n");

  // ── Load deployment ──
  const deployPath = path.join(__dirname, "..", "deployment.json");
  if (!fs.existsSync(deployPath)) {
    console.error("❌ deployment.json not found. Run run-demo.sh first.");
    process.exit(1);
  }
  const dep = JSON.parse(fs.readFileSync(deployPath, "utf8"));
  console.log("📦 Loaded deployment:");
  for (const [k, v] of Object.entries(dep)) {
    if (k !== "deployer") console.log(`   ${k}: ${v}`);
  }

  // ── Load ABIs ──
  const abis = JSON.parse(fs.readFileSync(path.join(__dirname, "..", "abis.json"), "utf8"));

  // ── Connect signers with nonce management ──
  const provider = new ethers.JsonRpcProvider(ANVIL_RPC);
  const wallet0 = new ethers.NonceManager(new ethers.Wallet(PRIV_KEYS[0], provider));
  const wallet1 = new ethers.NonceManager(new ethers.Wallet(PRIV_KEYS[1], provider));
  const wallet2 = new ethers.NonceManager(new ethers.Wallet(PRIV_KEYS[2], provider));

  // Known anvil addresses
  const ADDRS = {
    0: "0xf39Fd6e51aad88F6F4ce6aB8827279cffFb92266",
    1: "0x70997970C51812dc3A010C7d01b50e0d17dc79C8",
    2: "0x3C44CdDdB6a900fa2b585dd299e03d12FA4293BC",
  };

  const token = new ethers.Contract(dep.token, abis.DemoToken, wallet0);
  const kya = new ethers.Contract(dep.kyaRegistry, abis.KYARegistry, wallet0);
  const pool = new ethers.Contract(dep.lockPoolManager, abis.LockPoolManager, wallet0);
  const auth = new ethers.Contract(dep.authTokenManager, abis.AuthTokenManager, wallet0);
  const billMgr = new ethers.Contract(dep.billManager, abis.BillManager, wallet0);

  const results = { steps: [], timestamp: new Date().toISOString() };

  // ═══════════════════════════════════════════
  // STEP 1: Mint tokens to Payer
  // ═══════════════════════════════════════════
  console.log("\n── Step 1: Mint sUSDC to Payer ──");
  const mintAmount = ethers.parseUnits("1000000", 6);
  const tx1 = await token.mint(ADDRS[1], mintAmount);
  await tx1.wait();
  const bal1 = await token.balanceOf(ADDRS[1]);
  console.log(`   Payer balance: ${ethers.formatUnits(bal1, 6)} sUSDC ✅`);
  results.steps.push({ step: "mint", status: "ok", payer: ADDRS[1], amount: "1000000" });

  // ═══════════════════════════════════════════
  // STEP 2: Register DIDs
  // ═══════════════════════════════════════════
  console.log("\n── Step 2: Register DIDs ──");
  const didStake = ethers.parseEther("0.01");
  const permsHash = ethers.zeroPadValue(ethers.toUtf8Bytes("full"), 32);

  // Register payer DID (wallet1 pays for itself)
  const kya1 = kya.connect(wallet1);
  const tx2a = await kya1.registerDID(ADDRS[1], permsHash, 365, { value: didStake });
  await tx2a.wait();
  console.log(`   Payer DID registered ✅`);

  // Register payee DID (wallet2 pays for itself)
  const kya2 = kya.connect(wallet2);
  const tx2b = await kya2.registerDID(ADDRS[2], permsHash, 365, { value: didStake });
  await tx2b.wait();
  console.log(`   Payee DID registered ✅`);

  const [payerOk, ,] = await kya.verifyDID(ADDRS[1]);
  const [payeeOk, ,] = await kya.verifyDID(ADDRS[2]);
  results.steps.push({ step: "register_dids", status: "ok", payer_verified: payerOk, payee_verified: payeeOk });
  if (!payerOk || !payeeOk) throw new Error("DID verification failed");

  // ═══════════════════════════════════════════
  // STEP 3: Create LockPool
  // ═══════════════════════════════════════════
  console.log("\n── Step 3: Create LockPool ──");
  const poolAmount = ethers.parseUnits("50000", 6);

  // Payer approves LockPoolManager to spend tokens
  const token1 = token.connect(wallet1);
  const txApprove = await token1.approve(dep.lockPoolManager, poolAmount);
  await txApprove.wait();

  const pool1 = pool.connect(wallet1);
  const tx3 = await pool1.createLockPool(ADDRS[1], dep.token, poolAmount);
  const receipt3 = await tx3.wait();

  // Extract poolId from event
  const poolEvent = receipt3.logs.find(
    (l) => l.address.toLowerCase() === dep.lockPoolManager.toLowerCase()
  );
  const poolId = poolEvent ? poolEvent.topics[1] : null;
  console.log(`   Pool created: poolId=${poolId}`);
  console.log(`   Pool balance: ${ethers.formatUnits(poolAmount, 6)} sUSDC ✅`);
  results.steps.push({ step: "create_pool", status: "ok", poolId, amount: "50000" });

  // ═══════════════════════════════════════════
  // STEP 4: Issue AuthTokens
  // ═══════════════════════════════════════════
  console.log("\n── Step 4: Issue AuthTokens ──");
  const auth1 = auth.connect(wallet1);

  // CreateBill auth token
  const tx4a = await auth1.issueAuthToken(ADDRS[1], 0, poolAmount, 3600);
  const receipt4a = await tx4a.wait();
  const createTokenEvent = receipt4a.logs.find(
    (l) => l.address.toLowerCase() === dep.authTokenManager.toLowerCase()
  );
  const createTokenId = createTokenEvent ? createTokenEvent.topics[1] : await auth.ownerNonce(ADDRS[1]).then(n => {
    // Reconstruct tokenId
    const now = Math.floor(Date.now() / 1000);
    return ethers.keccak256(
      ethers.solidityPacked(
        ["address", "address", "uint8", "uint256", "uint256", "uint256", "uint256"],
        [ADDRS[1], ADDRS[1], 0, poolAmount, n, now + 3600, 31337]
      )
    );
  });
  console.log(`   CreateBill auth token: ${createTokenId} ✅`);

  // ConfirmBill auth token
  const tx4b = await auth1.issueAuthToken(ADDRS[1], 1, poolAmount, 3600);
  const receipt4b = await tx4b.wait();
  const confirmTokenEvent = receipt4b.logs.find(
    (l) => l.address.toLowerCase() === dep.authTokenManager.toLowerCase()
  );
  const confirmTokenId = confirmTokenEvent ? confirmTokenEvent.topics[1] : null;
  console.log(`   ConfirmBill auth token: ${confirmTokenId} ✅`);

  results.steps.push({
    step: "issue_auth_tokens",
    status: "ok",
    createBillToken: createTokenId,
    confirmBillToken: confirmTokenId,
  });

  // ═══════════════════════════════════════════
  // STEP 5: Create Bill (EIP-712 signed)
  // ═══════════════════════════════════════════
  console.log("\n── Step 5: Create Bill (EIP-712) ──");
  const billAmount = ethers.parseUnits("5000", 6);
  const deadline = Math.floor(Date.now() / 1000) + 3600;

  // Sign EIP-712 digest
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

  // Get nonce from contract
  const createToken = await auth.authTokens(createTokenId);
  const nonce = createToken.nonce;

  const createSig = await wallet1.signTypedData(domain, types, {
    tokenId: createTokenId,
    agent: ADDRS[1],
    opType: 0, // CreateBill
    amount: billAmount,
    nonce,
    deadline,
  });
  const createSplit = ethers.Signature.from(createSig);

  const billTx = await billMgr.connect(wallet1).createBill(
    poolId,
    ADDRS[2],
    billAmount,
    "Karma MVP Demo Bill",
    ethers.id("proof-data-001"),
    createTokenId,
    deadline,
    createSplit.v,
    createSplit.r,
    createSplit.s
  );
  const billReceipt = await billTx.wait();

  // Extract billId from event
  const billEvent = billReceipt.logs.find(
    (l) => l.address.toLowerCase() === dep.billManager.toLowerCase()
  );
  const billId = billEvent ? BigInt(billEvent.topics[1]) : 1n;
  console.log(`   Bill created: billId=${billId} ✅`);

  const bill = await billMgr.bills(billId);
  console.log(`   Bill status: ${["Pending", "Confirmed", "Cancelled", "Settled"][bill.status]}`);
  results.steps.push({ step: "create_bill", status: "ok", billId: billId.toString() });

  // ═══════════════════════════════════════════
  // STEP 6: Confirm Bill (EIP-712 signed by payer)
  // ═══════════════════════════════════════════
  console.log("\n── Step 6: Confirm Bill (EIP-712) ──");
  const confirmToken = await auth.authTokens(confirmTokenId);
  const confirmNonce = confirmToken.nonce;

  const confirmSig = await wallet1.signTypedData(domain, types, {
    tokenId: confirmTokenId,
    agent: ADDRS[1],
    opType: 1, // ConfirmBill
    amount: billAmount,
    nonce: confirmNonce,
    deadline,
  });
  const confirmSplit = ethers.Signature.from(confirmSig);

  // Confirm must be called by payee (wallet2)? No - confirm is called by pool owner (wallet1)
  const confirmTx = await billMgr.connect(wallet1).confirmBill(
    billId,
    confirmTokenId,
    deadline,
    confirmSplit.v,
    confirmSplit.r,
    confirmSplit.s
  );
  await confirmTx.wait();

  const bill2 = await billMgr.bills(billId);
  console.log(`   Bill status: ${["Pending", "Confirmed", "Cancelled", "Settled"][bill2.status]} ✅`);
  results.steps.push({ step: "confirm_bill", status: "ok" });

  // ═══════════════════════════════════════════
  // STEP 7: CloseBatch + SettleBatch
  // ═══════════════════════════════════════════
  console.log("\n── Step 7: Close & Settle Batch ──");
  const batchId = bill.batchId;

  const closeTx = await billMgr.connect(wallet1).closeAndSettleBatch(batchId);
  await closeTx.wait();

  const batch = await billMgr.batches(batchId);
  console.log(`   Batch status: ${["Open", "Closed", "Settled"][batch.status]} ✅`);

  const bill3 = await billMgr.bills(billId);
  console.log(`   Bill status: ${["Pending", "Confirmed", "Cancelled", "Settled"][bill3.status]} ✅`);
  results.steps.push({ step: "close_settle_batch", status: "ok", batchId: batchId.toString() });

  // ═══════════════════════════════════════════
  // STEP 8: Verify final balances
  // ═══════════════════════════════════════════
  console.log("\n── Step 8: Final Balances ──");
  const payerBal = await token.balanceOf(ADDRS[1]);
  const payeeBal = await token.balanceOf(ADDRS[2]);
  const poolAcct = await pool.getPoolAccounting(poolId);

  console.log(`   Payer balance: ${ethers.formatUnits(payerBal, 6)} sUSDC`);
  console.log(`   Payee balance: ${ethers.formatUnits(payeeBal, 6)} sUSDC`);
  console.log(`   Pool totalLocked: ${ethers.formatUnits(poolAcct.totalLocked, 6)} sUSDC`);
  console.log(`   Pool mappingBalance: ${ethers.formatUnits(poolAcct.mappingBalance, 6)} sUSDC`);
  console.log(`   Pool settledAmount: ${ethers.formatUnits(poolAcct.settledAmount, 6)} sUSDC`);

  // Verify: payee should have received 5000 sUSDC
  const expectedPayee = ethers.parseUnits("5000", 6);
  const payeeMatch = payeeBal === expectedPayee;
  console.log(`\n   Payee received correct amount: ${payeeMatch ? "✅" : "❌"} (expected 5000, got ${ethers.formatUnits(payeeBal, 6)})`);

  results.steps.push({
    step: "final_balances",
    status: payeeMatch ? "ok" : "fail",
    payer_balance: ethers.formatUnits(payerBal, 6),
    payee_balance: ethers.formatUnits(payeeBal, 6),
    pool_total_locked: ethers.formatUnits(poolAcct.totalLocked, 6),
    pool_settled: ethers.formatUnits(poolAcct.settledAmount, 6),
  });

  // ═══════════════════════════════════════════
  // Save results
  // ═══════════════════════════════════════════
  const resultsDir = path.join(__dirname, "..", "results");
  if (!fs.existsSync(resultsDir)) fs.mkdirSync(resultsDir, { recursive: true });

  const resultsPath = path.join(resultsDir, "simulate-result.json");
  fs.writeFileSync(resultsPath, JSON.stringify(results, null, 2));

  console.log(`\n📁 Results saved: ${resultsPath}`);
  console.log("\n═══════════════════════════════════════════");
  console.log("  ✅ E2E Simulation Complete");
  console.log("═══════════════════════════════════════════\n");
}

main().catch((err) => {
  console.error("❌ Simulation failed:", err);
  process.exit(1);
});
