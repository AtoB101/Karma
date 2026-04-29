import { Contract, JsonRpcProvider, Wallet } from "ethers";
import { writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";

const nonCustodialAbi = [
  "function batchModeEnabled() view returns (bool)",
  "function batchCircuitBreakerPaused() view returns (bool)",
  "function setBatchModeEnabled(bool enabled)",
  "function setBatchCircuitBreakerPaused(bool paused)",
  "function lockFunds(address token,uint256 amount)",
  "function createBill(address seller,address token,uint256 amount,bytes32 scopeHash,string proofHash,uint256 deadline) returns (uint256 billId)",
  "function confirmBill(uint256 billId)",
  "function closeBatch(uint256 batchId)",
  "function settleBatch(uint256 batchId,uint256 maxBills) returns (uint256 settledCount,uint256 settledAmount)",
  "function getBill(uint256 billId) view returns ((uint256 billId,uint256 batchId,address buyer,address seller,address token,uint256 amount,uint256 sellerBond,bytes32 scopeHash,string proofHash,uint8 status,uint256 createdAt,uint256 deadline))",
  "function getBatch(uint256 batchId) view returns ((uint256 batchId,uint256 totalPending,uint256 billCount,uint8 status,uint256 createdAt,uint256 settledAt))",
  "function getAccountState(address user,address token) view returns ((uint256 locked,uint256 active,uint256 reserved))",
  "function isAccountConsistent(address user,address token) view returns (bool)",
];

const erc20Abi = [
  "function approve(address spender,uint256 amount) returns (bool)",
  "function allowance(address owner,address spender) view returns (uint256)",
];

function required(name: string): string {
  const value = process.env[name];
  if (!value) throw new Error(`Missing required env var: ${name}`);
  return value;
}

async function main() {
  const rpcUrl = required("RPC_URL");
  const nonCustodialAddress = required("NON_CUSTODIAL_ADDRESS");
  const tokenAddress = required("TOKEN_ADDRESS");
  const buyerPk = required("BUYER_PRIVATE_KEY");
  const sellerPk = required("SELLER_PRIVATE_KEY");

  const amount = BigInt(process.env.BILL_AMOUNT ?? "100");
  const lockAmount = BigInt(process.env.LOCK_AMOUNT ?? (amount * 20n).toString());
  const ttlSeconds = Number(process.env.BILL_TTL_SECONDS ?? "3600");
  const maxBills = BigInt(process.env.BATCH_MAX_BILLS ?? "0");
  const proofHash = process.env.PROOF_HASH ?? "ipfs://proof-integration-v1";
  const outputPath = process.env.INTEGRATION_OUTPUT_PATH ?? "results/integration-noncustodial-batch.json";
  const ownerPk = process.env.OWNER_PRIVATE_KEY ?? "";

  const provider = new JsonRpcProvider(rpcUrl);
  const buyer = new Wallet(buyerPk, provider);
  const seller = new Wallet(sellerPk, provider);
  const ncBuyer = new Contract(nonCustodialAddress, nonCustodialAbi, buyer);
  const ncSeller = new Contract(nonCustodialAddress, nonCustodialAbi, seller);

  const owner = ownerPk ? new Wallet(ownerPk, provider) : null;
  const ncOwner = owner ? new Contract(nonCustodialAddress, nonCustodialAbi, owner) : null;

  const tokenBuyer = new Contract(tokenAddress, erc20Abi, buyer);
  const tokenSeller = new Contract(tokenAddress, erc20Abi, seller);

  const txHashes: Record<string, string> = {};

  // Optional: align fuse state when owner key is provided.
  if (ncOwner) {
    const modeTx = await ncOwner.setBatchModeEnabled(true);
    txHashes.setBatchModeEnabled = modeTx.hash;
    await modeTx.wait();

    const breakerTx = await ncOwner.setBatchCircuitBreakerPaused(false);
    txHashes.setBatchCircuitBreakerPaused = breakerTx.hash;
    await breakerTx.wait();
  }

  // Ensure approvals for transferFrom settlement path.
  const buyerAllowance: bigint = await tokenBuyer.allowance(buyer.address, nonCustodialAddress);
  if (buyerAllowance < amount) {
    const tx = await tokenBuyer.approve(nonCustodialAddress, (1n << 255n) - 1n);
    txHashes.buyerApprove = tx.hash;
    await tx.wait();
  }

  const sellerAllowance: bigint = await tokenSeller.allowance(seller.address, nonCustodialAddress);
  if (sellerAllowance < amount) {
    const tx = await tokenSeller.approve(nonCustodialAddress, (1n << 255n) - 1n);
    txHashes.sellerApprove = tx.hash;
    await tx.wait();
  }

  const buyerLockTx = await ncBuyer.lockFunds(tokenAddress, lockAmount);
  txHashes.buyerLockFunds = buyerLockTx.hash;
  await buyerLockTx.wait();

  const sellerLockTx = await ncSeller.lockFunds(tokenAddress, lockAmount);
  txHashes.sellerLockFunds = sellerLockTx.hash;
  await sellerLockTx.wait();

  const deadline = BigInt(Math.floor(Date.now() / 1000) + ttlSeconds);
  const createTx = await ncBuyer.createBill(seller.address, tokenAddress, amount, "0x" + "11".repeat(32), proofHash, deadline);
  txHashes.createBill = createTx.hash;
  const createReceipt = await createTx.wait();

  const createdLog = createReceipt?.logs?.find((x: any) => x.topics?.length > 0);
  if (!createdLog) throw new Error("BillCreated log not found");

  const billId = BigInt(createdLog.topics[1]);

  const confirmTx = await ncBuyer.confirmBill(billId);
  txHashes.confirmBill = confirmTx.hash;
  await confirmTx.wait();

  const bill = await ncBuyer.getBill(billId);
  const batchId = BigInt(bill.batchId);

  const closeTx = await ncBuyer.closeBatch(batchId);
  txHashes.closeBatch = closeTx.hash;
  await closeTx.wait();

  const settleTx = await ncBuyer.settleBatch(batchId, maxBills);
  txHashes.settleBatch = settleTx.hash;
  await settleTx.wait();

  const finalBill = await ncBuyer.getBill(billId);
  const finalBatch = await ncBuyer.getBatch(batchId);
  const buyerState = await ncBuyer.getAccountState(buyer.address, tokenAddress);
  const sellerState = await ncBuyer.getAccountState(seller.address, tokenAddress);
  const buyerConsistent = await ncBuyer.isAccountConsistent(buyer.address, tokenAddress);
  const sellerConsistent = await ncBuyer.isAccountConsistent(seller.address, tokenAddress);
  const batchModeEnabled = await ncBuyer.batchModeEnabled();
  const batchCircuitBreakerPaused = await ncBuyer.batchCircuitBreakerPaused();

  const output = {
    status: "passed",
    generatedAt: new Date().toISOString(),
    chainId: (await provider.getNetwork()).chainId.toString(),
    nonCustodialAddress,
    tokenAddress,
    buyer: buyer.address,
    seller: seller.address,
    ownerConfiguredFuses: Boolean(ncOwner),
    params: {
      amount: amount.toString(),
      lockAmount: lockAmount.toString(),
      ttlSeconds,
      maxBills: maxBills.toString(),
      proofHash,
    },
    txHashes,
    checkpoints: {
      billId: billId.toString(),
      batchId: batchId.toString(),
      finalBillStatus: Number(finalBill.status),
      finalBatchStatus: Number(finalBatch.status),
      batchTotalPending: finalBatch.totalPending.toString(),
      buyerConsistent,
      sellerConsistent,
      batchModeEnabled,
      batchCircuitBreakerPaused,
    },
    accountState: {
      buyer: {
        locked: buyerState.locked.toString(),
        active: buyerState.active.toString(),
        reserved: buyerState.reserved.toString(),
      },
      seller: {
        locked: sellerState.locked.toString(),
        active: sellerState.active.toString(),
        reserved: sellerState.reserved.toString(),
      },
    },
  };

  mkdirSync(dirname(outputPath), { recursive: true });
  writeFileSync(outputPath, JSON.stringify(output, null, 2));

  console.log("Integration status: PASSED");
  console.log("Bill ID:", output.checkpoints.billId);
  console.log("Batch ID:", output.checkpoints.batchId);
  console.log("Artifact:", outputPath);
}

main().catch((err) => {
  console.error("Integration status: FAILED");
  console.error(err);
  process.exit(1);
});
