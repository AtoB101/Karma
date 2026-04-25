import { JsonRpcProvider, Wallet, Contract, keccak256, toUtf8Bytes } from "ethers";

/**
 * Minimal v0.1 client template:
 * 1) read nonce from SettlementEngine
 * 2) build Quote
 * 3) sign EIP-712 Quote
 * 4) submit settlement tx
 *
 * Required env vars:
 * - RPC_URL
 * - ENGINE_ADDRESS
 * - TOKEN_ADDRESS
 * - PAYER_PRIVATE_KEY
 * - PAYEE_ADDRESS
 */

const engineAbi = [
  "function nonces(address) view returns (uint256)",
  "function getQuoteDigest((bytes32 quoteId,address payer,address payee,address token,uint256 amount,uint256 nonce,uint256 deadline,bytes32 scopeHash) quote) view returns (bytes32)",
  "function submitSettlement((bytes32 quoteId,address payer,address payee,address token,uint256 amount,uint256 nonce,uint256 deadline,bytes32 scopeHash) quote,uint8 v,bytes32 r,bytes32 s)",
];

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

async function main() {
  const rpcUrl = process.env.RPC_URL;
  const engineAddress = process.env.ENGINE_ADDRESS;
  const tokenAddress = process.env.TOKEN_ADDRESS;
  const payerPk = process.env.PAYER_PRIVATE_KEY;
  const payeeAddress = process.env.PAYEE_ADDRESS;

  if (!rpcUrl || !engineAddress || !tokenAddress || !payerPk || !payeeAddress) {
    throw new Error("Missing required env vars: RPC_URL/ENGINE_ADDRESS/TOKEN_ADDRESS/PAYER_PRIVATE_KEY/PAYEE_ADDRESS");
  }

  const provider = new JsonRpcProvider(rpcUrl);
  const payer = new Wallet(payerPk, provider);
  const engine = new Contract(engineAddress, engineAbi, payer);

  const network = await provider.getNetwork();
  const chainId = Number(network.chainId);
  const nonce: bigint = await engine.nonces(payer.address);
  const now = Math.floor(Date.now() / 1000);
  const deadline = BigInt(now + 3600); // 1h

  const quote: Quote = {
    quoteId: keccak256(toUtf8Bytes(`quote:${payer.address}:${payeeAddress}:${now}`)),
    payer: payer.address,
    payee: payeeAddress,
    token: tokenAddress,
    amount: 100n, // token base unit; adapt to decimals
    nonce,
    deadline,
    scopeHash: keccak256(toUtf8Bytes("api-call:inference:v1")),
  };

  const domain = {
    name: "TrustChainSettlementEngine",
    version: "1",
    chainId,
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

  const signature = await payer.signTypedData(domain, types, quote);
  const { v, r, s } = (await import("ethers")).Signature.from(signature);

  // Optional local sanity check: should match contract digest
  const onchainDigest = await engine.getQuoteDigest(quote);
  console.log("On-chain digest:", onchainDigest);
  console.log("Submitting settlement...");

  const tx = await engine.submitSettlement(quote, v, r, s);
  const receipt = await tx.wait();
  console.log("Settlement tx hash:", receipt.hash);
}

main().catch((err) => {
  console.error(err);
  process.exit(1);
});
