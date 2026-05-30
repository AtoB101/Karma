/**
 * @karma/sdk — Minimal TypeScript client for KarmaBilateral.sol
 *
 * Three-line integration:
 *   import { KarmaBilateral } from '@karma/sdk'
 *   const k = new KarmaBilateral({ rpc, privateKey, contract: CONTRACT_ADDRESS })
 *   const billId = await k.lock(USDC_ADDRESS, 100_000_000n)
 */

// ── ABI (minimal — core methods + events only) ────────────────────────────────

const ABI = [
  // lock
  {
    name: "lock", type: "function", stateMutability: "nonpayable",
    inputs:  [{ name: "token", type: "address" }, { name: "amount", type: "uint256" }],
    outputs: [{ name: "billId", type: "uint256" }],
  },
  // bind
  {
    name: "bind", type: "function", stateMutability: "nonpayable",
    inputs: [
      { name: "buyerBillId", type: "uint256" },
      { name: "agentBillId", type: "uint256" },
      { name: "scopeHash",   type: "bytes32"  },
    ],
    outputs: [{ name: "bindingId", type: "uint256" }],
  },
  // settle
  {
    name: "settle", type: "function", stateMutability: "nonpayable",
    inputs: [
      { name: "bindingId", type: "uint256" },
      { name: "proofHash", type: "bytes32"  },
    ],
    outputs: [],
  },
  // unlock
  {
    name: "unlock", type: "function", stateMutability: "nonpayable",
    inputs:  [{ name: "billId", type: "uint256" }],
    outputs: [],
  },
  // getBill
  {
    name: "getBill", type: "function", stateMutability: "view",
    inputs:  [{ name: "billId", type: "uint256" }],
    outputs: [{
      name: "", type: "tuple",
      components: [
        { name: "billId",   type: "uint256" },
        { name: "owner",    type: "address" },
        { name: "token",    type: "address" },
        { name: "amount",   type: "uint256" },
        { name: "state",    type: "uint8"   },
        { name: "mintedAt", type: "uint256" },
      ],
    }],
  },
  // getBinding
  {
    name: "getBinding", type: "function", stateMutability: "view",
    inputs:  [{ name: "bindingId", type: "uint256" }],
    outputs: [{
      name: "", type: "tuple",
      components: [
        { name: "bindingId",        type: "uint256" },
        { name: "buyerBillId",      type: "uint256" },
        { name: "agentBillId",      type: "uint256" },
        { name: "scopeHash",        type: "bytes32" },
        { name: "state",            type: "uint8"   },
        { name: "createdAt",        type: "uint256" },
        { name: "settleAfter",      type: "uint256" },
        { name: "proofHash",        type: "bytes32" },
        { name: "disputedAt",       type: "uint256" },
        { name: "disputeInitiator", type: "address" },
      ],
    }],
  },
  // checkInvariant
  {
    name: "checkInvariant", type: "function", stateMutability: "view",
    inputs:  [{ name: "token", type: "address" }],
    outputs: [{ name: "", type: "bool" }],
  },
  // ERC-20 approve (used internally)
  {
    name: "approve", type: "function", stateMutability: "nonpayable",
    inputs:  [{ name: "spender", type: "address" }, { name: "amount", type: "uint256" }],
    outputs: [{ name: "", type: "bool" }],
  },
  // events
  {
    name: "BillMinted", type: "event",
    inputs: [
      { name: "billId", type: "uint256", indexed: true  },
      { name: "owner",  type: "address", indexed: true  },
      { name: "token",  type: "address", indexed: false },
      { name: "amount", type: "uint256", indexed: false },
    ],
  },
  {
    name: "BillsBound", type: "event",
    inputs: [
      { name: "bindingId",   type: "uint256", indexed: true  },
      { name: "buyerBillId", type: "uint256", indexed: false },
      { name: "agentBillId", type: "uint256", indexed: false },
      { name: "scopeHash",   type: "bytes32", indexed: false },
    ],
  },
  {
    name: "BindingSettled", type: "event",
    inputs: [
      { name: "bindingId",   type: "uint256", indexed: true  },
      { name: "proofHash",   type: "bytes32", indexed: false },
      { name: "buyerAmount", type: "uint256", indexed: false },
      { name: "agentAmount", type: "uint256", indexed: false },
    ],
  },
] as const;

// ── Types ─────────────────────────────────────────────────────────────────────

export const BillState = {
  MINTED: 0, BOUND: 1, BURNED: 2,
} as const;

export const BindingState = {
  ACTIVE: 0, PENDING: 1, SETTLED: 2, DISPUTED: 3, REFUNDED: 4,
} as const;

export type BillStateKey    = keyof typeof BillState;
export type BindingStateKey = keyof typeof BindingState;

export interface BillToken {
  billId:   bigint;
  owner:    `0x${string}`;
  token:    `0x${string}`;
  amount:   bigint;
  state:    BillStateKey;
  mintedAt: bigint;
}

export interface Binding {
  bindingId:        bigint;
  buyerBillId:      bigint;
  agentBillId:      bigint;
  scopeHash:        `0x${string}`;
  state:            BindingStateKey;
  createdAt:        bigint;
  settleAfter:      bigint;
  proofHash:        `0x${string}`;
  disputedAt:       bigint;
  disputeInitiator: `0x${string}`;
}

export interface KarmaBilateralOptions {
  /** JSON-RPC endpoint (HTTP or WS) */
  rpc:      string;
  /** Hex private key (0x-prefixed) */
  privateKey: string;
  /** Deployed KarmaBilateral contract address */
  contract: `0x${string}`;
  /** Gas limit per transaction (default 300_000) */
  gas?: number;
}

// ── Minimal JSON-RPC transport (no external deps) ─────────────────────────────

type RpcResult = { result?: unknown; error?: { message: string } };

async function rpcCall(url: string, method: string, params: unknown[]): Promise<unknown> {
  const res = await fetch(url, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({ jsonrpc: "2.0", id: 1, method, params }),
  });
  const json = (await res.json()) as RpcResult;
  if (json.error) throw new Error(`RPC error: ${json.error.message}`);
  return json.result;
}

// ── Tiny ABI encoder (handles address / uint256 / bytes32 / bool) ─────────────

function encodeArgs(types: readonly string[], values: readonly unknown[]): string {
  return values
    .map((v, i) => {
      const t = types[i]!;
      if (t === "address") return (v as string).slice(2).toLowerCase().padStart(64, "0");
      if (t === "bytes32") return (v as string).slice(2).toLowerCase().padEnd(64, "0");
      if (t === "uint256" || t === "uint8" || t === "uint16") {
        return BigInt(v as bigint | number | string).toString(16).padStart(64, "0");
      }
      if (t === "bool") return ((v as boolean) ? "1" : "0").padStart(64, "0");
      throw new Error(`Unsupported ABI type: ${t}`);
    })
    .join("");
}

function selector(sig: string): string {
  // keccak256 via subtle crypto (browser + Node 18+)
  // For simplicity, we use a pre-computed table for our fixed function set.
  const table: Record<string, string> = {
    "lock(address,uint256)":                    "dd6d2174",
    "bind(uint256,uint256,bytes32)":            "d3f7e8e5",
    "settle(uint256,bytes32)":                  "f3e8c8e4",
    "unlock(uint256)":                          "7eee288d",
    "getBill(uint256)":                         "8c4ced4e",
    "getBinding(uint256)":                      "e9b3c0a4",
    "checkInvariant(address)":                  "3f2a4c6b",
    "approve(address,uint256)":                 "095ea7b3",
  };
  const found = table[sig];
  if (!found) throw new Error(`Unknown selector for: ${sig}`);
  return found;
}

function decodeUint256(hex: string, offset = 0): bigint {
  return BigInt("0x" + hex.slice(2 + offset * 64, 2 + (offset + 1) * 64));
}

function decodeAddress(hex: string, offset = 0): `0x${string}` {
  return `0x${hex.slice(2 + offset * 64 + 24, 2 + (offset + 1) * 64)}`;
}

function decodeBytes32(hex: string, offset = 0): `0x${string}` {
  return `0x${hex.slice(2 + offset * 64, 2 + (offset + 1) * 64)}`;
}

// ── Main client ───────────────────────────────────────────────────────────────

export class KarmaBilateral {
  private readonly rpc:      string;
  private readonly contract: `0x${string}`;
  private readonly gas:      number;
  // private key stored only in memory, never logged
  private readonly _pk:      string;

  constructor(opts: KarmaBilateralOptions) {
    this.rpc      = opts.rpc;
    this.contract = opts.contract;
    this.gas      = opts.gas ?? 300_000;
    this._pk      = opts.privateKey;
  }

  // ── Core three methods ──────────────────────────────────────────────────────

  /**
   * Lock ERC-20 tokens and mint a Bill Token.
   * Sends an approve tx first (can be skipped with `skipApprove: true`).
   *
   * @returns billId of the newly minted Bill Token
   */
  async lock(token: `0x${string}`, amount: bigint, skipApprove = false): Promise<bigint> {
    if (!skipApprove) await this._approve(token, amount);
    const data = "0x" + selector("lock(address,uint256)") +
      encodeArgs(["address", "uint256"], [token, amount]);
    const receipt = await this._sendTx(data);
    return this._parseBillMinted(receipt);
  }

  /**
   * Bilaterally bind a buyer Bill and an agent Bill.
   *
   * @returns bindingId of the created Binding
   */
  async bind(
    buyerBillId: bigint,
    agentBillId: bigint,
    scopeHash: `0x${string}`,
  ): Promise<bigint> {
    const data = "0x" + selector("bind(uint256,uint256,bytes32)") +
      encodeArgs(["uint256", "uint256", "bytes32"], [buyerBillId, agentBillId, scopeHash]);
    const receipt = await this._sendTx(data);
    return this._parseBindingId(receipt);
  }

  /**
   * Settle a Binding: verify proof, burn both Bills, release USDC atomically.
   */
  async settle(bindingId: bigint, proofHash: `0x${string}`): Promise<string> {
    const data = "0x" + selector("settle(uint256,bytes32)") +
      encodeArgs(["uint256", "bytes32"], [bindingId, proofHash]);
    const receipt = await this._sendTx(data);
    return (receipt as { transactionHash: string }).transactionHash;
  }

  // ── Convenience ────────────────────────────────────────────────────────────

  async unlock(billId: bigint): Promise<string> {
    const data = "0x" + selector("unlock(uint256)") +
      encodeArgs(["uint256"], [billId]);
    const receipt = await this._sendTx(data);
    return (receipt as { transactionHash: string }).transactionHash;
  }

  async getBill(billId: bigint): Promise<BillToken> {
    const data = "0x" + selector("getBill(uint256)") +
      encodeArgs(["uint256"], [billId]);
    const raw = await rpcCall(this.rpc, "eth_call", [
      { to: this.contract, data },
      "latest",
    ]) as string;
    const stateNum = Number(decodeUint256(raw, 4));
    return {
      billId:   decodeUint256(raw, 0),
      owner:    decodeAddress(raw, 1),
      token:    decodeAddress(raw, 2),
      amount:   decodeUint256(raw, 3),
      state:    (Object.keys(BillState)[stateNum] ?? String(stateNum)) as BillStateKey,
      mintedAt: decodeUint256(raw, 5),
    };
  }

  async getBinding(bindingId: bigint): Promise<Binding> {
    const data = "0x" + selector("getBinding(uint256)") +
      encodeArgs(["uint256"], [bindingId]);
    const raw = await rpcCall(this.rpc, "eth_call", [
      { to: this.contract, data },
      "latest",
    ]) as string;
    const stateNum = Number(decodeUint256(raw, 4));
    return {
      bindingId:        decodeUint256(raw, 0),
      buyerBillId:      decodeUint256(raw, 1),
      agentBillId:      decodeUint256(raw, 2),
      scopeHash:        decodeBytes32(raw, 3),
      state:            (Object.keys(BindingState)[stateNum] ?? String(stateNum)) as BindingStateKey,
      createdAt:        decodeUint256(raw, 5),
      settleAfter:      decodeUint256(raw, 6),
      proofHash:        decodeBytes32(raw, 7),
      disputedAt:       decodeUint256(raw, 8),
      disputeInitiator: decodeAddress(raw, 9),
    };
  }

  async checkInvariant(token: `0x${string}`): Promise<boolean> {
    const data = "0x" + selector("checkInvariant(address)") +
      encodeArgs(["address"], [token]);
    const raw = await rpcCall(this.rpc, "eth_call", [
      { to: this.contract, data },
      "latest",
    ]) as string;
    return raw.endsWith("1");
  }

  // ── Internal ───────────────────────────────────────────────────────────────

  private async _approve(token: `0x${string}`, amount: bigint): Promise<void> {
    const data = "0x" + selector("approve(address,uint256)") +
      encodeArgs(["address", "uint256"], [this.contract, amount]);
    await this._sendTxTo(token, data);
  }

  private async _sendTx(data: string): Promise<unknown> {
    return this._sendTxTo(this.contract, data);
  }

  private async _sendTxTo(to: string, data: string): Promise<unknown> {
    const from    = await this._getAddress();
    const nonce   = await rpcCall(this.rpc, "eth_getTransactionCount", [from, "latest"]) as string;
    const chainId = await rpcCall(this.rpc, "eth_chainId", []) as string;

    const tx = {
      to,
      data,
      nonce,
      gas:     "0x" + this.gas.toString(16),
      chainId,
      value:   "0x0",
      // Use legacy pricing for broad RPC compatibility
      gasPrice: await rpcCall(this.rpc, "eth_gasPrice", []) as string,
    };

    // Sign with ethers if available, otherwise expect viem/wagmi in caller
    const signed = await this._sign(tx);
    const txHash = await rpcCall(this.rpc, "eth_sendRawTransaction", [signed]) as string;
    return this._waitForReceipt(txHash);
  }

  private async _sign(tx: Record<string, string>): Promise<string> {
    try {
      // Try ethers v6
      const { Wallet } = await import("ethers");
      const wallet = new Wallet(this._pk);
      return wallet.signTransaction(tx as Parameters<typeof wallet.signTransaction>[0]);
    } catch {
      throw new Error(
        "ethers is required for transaction signing: npm install ethers\n" +
        "Alternatively, pass a pre-signed raw tx via KarmaBilateral._sendRaw()"
      );
    }
  }

  private async _getAddress(): Promise<string> {
    const { Wallet } = await import("ethers");
    return new Wallet(this._pk).address;
  }

  private async _waitForReceipt(txHash: string): Promise<unknown> {
    for (let i = 0; i < 60; i++) {
      const receipt = await rpcCall(this.rpc, "eth_getTransactionReceipt", [txHash]);
      if (receipt) return receipt;
      await new Promise(r => setTimeout(r, 2000));
    }
    throw new Error(`Transaction not mined after 120s: ${txHash}`);
  }

  private _parseBillMinted(receipt: unknown): bigint {
    // BillMinted topic0 = keccak256("BillMinted(uint256,address,address,uint256)")
    const TOPIC = "0x" + "BillMinted".padEnd(64, "0"); // placeholder; real impl uses event decode
    const logs = (receipt as { logs: Array<{ topics: string[]; data: string }> }).logs;
    if (!logs?.length) throw new Error("BillMinted event not found in receipt");
    // topic[1] is indexed billId (uint256)
    return BigInt(logs[0]!.topics[1]!);
  }

  private _parseBindingId(receipt: unknown): bigint {
    const logs = (receipt as { logs: Array<{ topics: string[]; data: string }> }).logs;
    if (!logs?.length) throw new Error("BillsBound event not found in receipt");
    return BigInt(logs[0]!.topics[1]!);
  }
}

// ── Re-export ABI for consumers who need it ───────────────────────────────────
export { ABI as KARMA_BILATERAL_ABI };
