import "dotenv/config";
import { Contract, JsonRpcProvider, Wallet, keccak256, Signature, toUtf8Bytes } from "ethers";

type Quote = {
  quoteId: string;
  payer: string;
  payee: string;
  token: string;
  amount: bigint;
  nonce: bigint;
  deadline: bigint;
  scopeHash: string;
};

const engineAbi = [
  "function nonces(address) view returns (uint256)",
  "function submitSettlement((bytes32 quoteId,address payer,address payee,address token,uint256 amount,uint256 nonce,uint256 deadline,bytes32 scopeHash) quote,uint8 v,bytes32 r,bytes32 s)",
];

function required(name: string): string {
  const v = process.env[name];
  if (!v) throw new Error(`Missing env var: ${name}`);
  return v;
}

function delay(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

function classifyError(error: unknown): string {
  const msg = String(error);
  if (msg.includes("TokenNotAllowed")) return "TokenNotAllowed";
  if (msg.includes("InvalidNonce")) return "InvalidNonce";
  if (msg.includes("DeadlineExpired")) return "DeadlineExpired";
  if (msg.includes("InvalidSignature")) return "InvalidSignature";
  if (msg.includes("TokenTransferFailed")) return "TokenTransferFailed";
  if (msg.includes("QuoteAlreadyExecuted")) return "QuoteAlreadyExecuted";
  if (msg.includes("EnginePaused")) return "EnginePaused";
  return "Other";
}

async function main() {
  const rpcUrl = required("RPC_URL");
  const engineAddress = required("ENGINE_ADDRESS");
  const tokenAddress = required("TOKEN_ADDRESS");
  const payerPk = required("PAYER_PRIVATE_KEY");
  const payeeAddress = required("PAYEE_ADDRESS");

  const batchSize = Number(process.env.BATCH_SIZE ?? "50");
  const minAmount = BigInt(process.env.MIN_AMOUNT ?? "100");
  const maxAmount = BigInt(process.env.MAX_AMOUNT ?? "200");
  const delayMs = Number(process.env.DELAY_MS ?? "300");
  const deadlineSeconds = Number(process.env.DEADLINE_SECONDS ?? "3600");
  const now = Math.floor(Date.now() / 1000);

  if (batchSize < 1 || batchSize > 1000) throw new Error("BATCH_SIZE must be in [1, 1000]");
  if (minAmount <= 0n || maxAmount < minAmount) throw new Error("Invalid MIN_AMOUNT / MAX_AMOUNT");

  const provider = new JsonRpcProvider(rpcUrl);
  const payer = new Wallet(payerPk, provider);
  const engine = new Contract(engineAddress, engineAbi, payer);
  const network = await provider.getNetwork();

  const domain = {
    name: "TrustChainSettlementEngine",
    version: "1",
    chainId: Number(network.chainId),
    verifyingContract: engineAddress,
  };
  const types = {
    Quote: [
      { name: "quoteId", type: "bytes32" },
      { name: "payer", type: "address" },
      { name: "payee", type: "address" },
      { name: "token", type: "address" },
      { name: "amount", type: "uint256" },
      { name: "nonce", type: "uint256" },
      { name: "deadline", type: "uint256" },
      { name: "scopeHash", type: "bytes32" },
    ],
  };

  const stats = {
    attempted: 0,
    sent: 0,
    succeeded: 0,
    failed: 0,
    failureReasons: new Map<string, number>(),
    txHashes: [] as string[],
  };

  let nonce: bigint = await engine.nonces(payer.address);
  console.log("Start batch settlement");
  console.log(`Batch size=${batchSize}, nonceStart=${nonce}, chainId=${domain.chainId}`);

  for (let i = 0; i < batchSize; i++) {
    stats.attempted++;
    const amount = minAmount + (BigInt(i) % (maxAmount - minAmount + 1n));
    const quote: Quote = {
      quoteId: keccak256(toUtf8Bytes(`batch-quote:${payer.address}:${i}:${now}`)),
      payer: payer.address,
      payee: payeeAddress,
      token: tokenAddress,
      amount,
      nonce,
      deadline: BigInt(now + deadlineSeconds),
      scopeHash: keccak256(toUtf8Bytes(`batch-task:${i}`)),
    };

    try {
      const signature = await payer.signTypedData(domain, types, quote);
      const sig = Signature.from(signature);
      const tx = await engine.submitSettlement(quote, sig.v, sig.r, sig.s);
      stats.sent++;
      stats.txHashes.push(tx.hash);

      const receipt = await tx.wait();
      if (receipt.status === 1) {
        stats.succeeded++;
      } else {
        stats.failed++;
        const key = "RevertedReceipt";
        stats.failureReasons.set(key, (stats.failureReasons.get(key) ?? 0) + 1);
      }
      nonce += 1n;
    } catch (error) {
      stats.failed++;
      const key = classifyError(error);
      stats.failureReasons.set(key, (stats.failureReasons.get(key) ?? 0) + 1);
      console.error(`[${i}] failed -> ${key}`);
    }

    if (delayMs > 0) {
      await delay(delayMs);
    }
  }

  const successRate = stats.attempted === 0 ? 0 : (stats.succeeded / stats.attempted) * 100;
  console.log("\n=== Batch Summary ===");
  console.log(`attempted: ${stats.attempted}`);
  console.log(`sent:      ${stats.sent}`);
  console.log(`succeeded: ${stats.succeeded}`);
  console.log(`failed:    ${stats.failed}`);
  console.log(`successRate: ${successRate.toFixed(2)}%`);
  console.log("failureReasons:", Object.fromEntries(stats.failureReasons.entries()));
  console.log("sampleTxHashes:", stats.txHashes.slice(0, 5));
}

main().catch((error) => {
  console.error(error);
  process.exit(1);
});
