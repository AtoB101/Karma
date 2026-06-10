/**
 * @karma/sdk — TypeScript client for Karma Protocol (all 5 contracts)
 *
 * Quick start:
 *   import { KarmaBilateral, VerifierRegistry, ScoringEngine, EvidenceChain } from '@karma/sdk'
 *
 *   const karma  = new KarmaBilateral({ rpc, privateKey, contract: KARMA_ADDR })
 *   const vrf    = new VerifierRegistry({ rpc, privateKey, contract: REGISTRY_ADDR })
 *
 *   // Lock tokens
 *   const billId = await karma.lock(USDC_ADDRESS, 100_000_000n)
 *
 *   // bindWithIntent
 *   const bindingId = await karma.bindWithIntent({
 *     buyer: buyerAddr, seller: sellerAddr,
 *     serviceType: "0x...", amount: 100_000_000n,
 *     deadline: BigInt(Math.floor(Date.now()/1000) + 3600),
 *     // ... rest of fields
 *   }, buyerBillId, sellerBillId)
 *
 *   // Verifier stake
 *   await token.approve(vrfContract, stakeAmount)
 *   await vrf.stake(stakeAmount)
 */

import { ethers } from "ethers";

// ── ABI Definitions ───────────────────────────────────────────────────────────

const KARMA_BILATERAL_ABI = [
  "function lock(address token, uint256 amount) returns (uint256 billId)",
  "function bind(uint256 buyerBillId, uint256 agentBillId, bytes32 scopeHash) returns (uint256 bindingId)",
  "function bindWithIntent(tuple(address buyer, address seller, bytes32 serviceType, bytes requirements, uint256 amount, uint256 penaltyRate, uint256 deadline, uint256 expiresAt, bytes32 proofSchema, bytes32[] requiredProofFields, address verifier, uint256 disputeWindow, address[] arbitrators) intent, uint256 buyerBillId, uint256 sellerBillId) returns (uint256 bindingId)",
  "function settle(uint256 bindingId, bytes32 proofHash)",
  "function unlock(uint256 billId)",
  "function getBill(uint256 billId) view returns (tuple(uint256 billId, address owner, address token, uint256 amount, uint8 state, uint256 mintedAt))",
  "function getBinding(uint256 bindingId) view returns (tuple(uint256 bindingId, uint256 buyerBillId, uint256 agentBillId, bytes32 scopeHash, uint8 state, uint256 createdAt, uint256 settleAfter, bytes32 proofHash, uint256 disputedAt, address disputeInitiator))",
  "function getIntentPackage(uint256 bindingId) view returns (tuple(address buyer, address seller, bytes32 serviceType, bytes requirements, uint256 amount, uint256 penaltyRate, uint256 deadline, uint256 expiresAt, bytes32 proofSchema, address verifier, uint256 disputeWindow))",
  "function checkInvariant(address token) view returns (bool)",
  "function setTokenAllowed(address token, bool allowed)",
  "function setBatchThreshold(address token, uint256 threshold)",
  "function setDisputeWindow(uint256 seconds_)",
  "function setSettleTimeout(uint256 seconds_)",
  "function setAttestationGateway(address gateway)",
  "function admin() view returns (address)",
  "function tokenAllowed(address) view returns (bool)",
  "function attestationGateway() view returns (address)",
  "event BillMinted(uint256 indexed billId, address indexed owner, address token, uint256 amount)",
  "event BillsBound(uint256 indexed bindingId, uint256 buyerBillId, uint256 agentBillId, bytes32 scopeHash)",
  "event IntentBound(uint256 indexed bindingId, bytes32 serviceType, uint256 amount)",
  "event BindingSettled(uint256 indexed bindingId, bytes32 proofHash, uint256 buyerAmount, uint256 agentAmount)",
];

const VERIFIER_REGISTRY_ABI = [
  "function registerVerifier(address wallet, string calldata endpointUrl)",
  "function deregisterVerifier(address wallet)",
  "function setThresholds(uint256 n, uint256 m)",
  "function setStakingConfig(address token, uint256 minStake_, uint256 reward)",
  "function stake(uint256 amount)",
  "function unstake(uint256 amount)",
  "function slash(address verifier, uint256 amount)",
  "function rewardVerifier(address verifier)",
  "function getVerifier(address wallet) view returns (tuple(address wallet, string endpointUrl, bool active, uint256 stakeAmount, uint256 successCount, uint256 falseAttestationCount, uint256 totalEarnings, uint256 slashedAmount))",
  "function getRequiredThreshold() view returns (uint256)",
  "function getTotalVerifiers() view returns (uint256)",
  "function isVerifierActive(address wallet) view returns (bool)",
  "function admin() view returns (address)",
  "function stakingToken() view returns (address)",
  "function minStake() view returns (uint256)",
  "function verificationReward() view returns (uint256)",
];

const SCORING_ENGINE_ABI = [
  "function setAuthorizedSettler(address settler)",
  "function registerParty(address party, uint8 partyType)",
  "function recordSettlement(address seller, address buyer, address verifier, uint256 speedRatio)",
  "function recordDisputeResolution(address seller, address buyer, address verifier, bool sellerWon)",
  "function recordVerifierSlashed(address verifier)",
  "function recordBuyerConfirmation(address buyer, uint256 speedRatio)",
  "function getScore(address party) view returns (tuple(uint256 reputationScore, uint256 settlementCount, uint256 successRate, uint256 avgSpeed, uint256 disputeCount, uint256 disputeWinRate, uint256 slashedCount, uint256 lastUpdated))",
  "function admin() view returns (address)",
  "function authorizedSettler() view returns (address)",
];

const EVIDENCE_CHAIN_ABI = [
  "function submitEvidence(tuple(bytes32 evidenceType, uint256 bindingId, address submitter, bytes data, uint256 timestamp, bool isValid, bytes32 hash))",
  "function submitEvidenceBatch(tuple(bytes32 evidenceType, uint256 bindingId, address submitter, bytes data, uint256 timestamp, bool isValid, bytes32 hash)[] calldata items)",
  "function invalidateEvidence(bytes32 evidenceHash)",
  "function getEvidence(bytes32 evidenceHash) view returns (tuple(bytes32 evidenceType, uint256 bindingId, address submitter, bytes data, uint256 timestamp, bool isValid, bytes32 hash))",
  "function getEvidenceCount(uint256 bindingId) view returns (uint256)",
  "function admin() view returns (address)",
];

const ERC20_ABI = [
  "function approve(address spender, uint256 amount) returns (bool)",
  "function balanceOf(address account) view returns (uint256)",
  "function decimals() view returns (uint8)",
  "function symbol() view returns (string)",
];

// ── Types ─────────────────────────────────────────────────────────────────────

export const BillState = { MINTED: 0, BOUND: 1, BURNED: 2 } as const;
export const BindingState = { ACTIVE: 0, PENDING: 1, FINALIZING: 2, SETTLED: 3, DISPUTED: 4, REFUNDED: 5 } as const;
export const PartyType = { SUPPLIER: 0, BUYER: 1, VERIFIER: 2 } as const;

export interface BillToken {
  billId:   bigint;
  owner:    string;
  token:    string;
  amount:   bigint;
  state:    number;
  mintedAt: bigint;
}

export interface Binding {
  bindingId:        bigint;
  buyerBillId:      bigint;
  agentBillId:      bigint;
  scopeHash:        string;
  state:            number;
  createdAt:        bigint;
  settleAfter:      bigint;
  proofHash:        string;
  disputedAt:       bigint;
  disputeInitiator: string;
}

export interface IntentPackage {
  buyer:              string;
  seller:             string;
  serviceType:        string;
  requirements:       string;
  amount:             bigint;
  penaltyRate:        bigint;
  deadline:           bigint;
  expiresAt:          bigint;
  proofSchema:        string;
  requiredProofFields: string[];
  verifier:           string;
  disputeWindow:      bigint;
  arbitrators:        string[];
}

export interface StoredIntentPackage {
  buyer:          string;
  seller:         string;
  serviceType:    string;
  requirements:   string;
  amount:         bigint;
  penaltyRate:    bigint;
  deadline:       bigint;
  expiresAt:      bigint;
  proofSchema:    string;
  verifier:       string;
  disputeWindow:  bigint;
}

export interface VerifierInfo {
  wallet:                 string;
  endpointUrl:            string;
  active:                 boolean;
  stakeAmount:            bigint;
  successCount:           bigint;
  falseAttestationCount:  bigint;
  totalEarnings:          bigint;
  slashedAmount:          bigint;
}

export interface ScoringVector {
  reputationScore:   bigint;
  settlementCount:   bigint;
  successRate:       bigint;
  avgSpeed:          bigint;
  disputeCount:      bigint;
  disputeWinRate:    bigint;
  slashedCount:      bigint;
  lastUpdated:       bigint;
}

export interface Evidence {
  evidenceType: string;
  bindingId:    bigint;
  submitter:    string;
  data:         string;
  timestamp:    bigint;
  isValid:      boolean;
  hash:         string;
}

export interface ClientOptions {
  rpc:         string;
  privateKey:  string;
  contract:    string;
  gas?:        bigint;
}

// ── Base Client ───────────────────────────────────────────────────────────────

class BaseClient {
  protected wallet:  ethers.Wallet;
  protected contract: ethers.Contract;

  constructor(opts: ClientOptions, abi: any[]) {
    const provider = new ethers.JsonRpcProvider(opts.rpc);
    this.wallet    = new ethers.Wallet(opts.privateKey, provider);
    this.contract  = new ethers.Contract(opts.contract, abi, this.wallet);
  }
}

// ── KarmaBilateral Client ─────────────────────────────────────────────────────

export class KarmaBilateral extends BaseClient {
  constructor(opts: ClientOptions) {
    super(opts, KARMA_BILATERAL_ABI);
  }

  /** Lock ERC-20 tokens and mint a Bill Token. Sends approve first. */
  async lock(token: string, amount: bigint): Promise<bigint> {
    const erc20 = new ethers.Contract(token, ERC20_ABI, this.wallet);
    const tx = await erc20.approve(this.contract.target, amount);
    await tx.wait();
    const tx2 = await this.contract.lock(token, amount);
    const receipt = await tx2.wait();
    // Parse BillMinted event
    const log = receipt.logs.find((l: any) => {
      try { return this.contract.interface.parseLog({ topics: l.topics as string[], data: l.data })?.name === "BillMinted"; }
      catch { return false; }
    });
    if (!log) throw new Error("BillMinted event not found");
    const parsed = this.contract.interface.parseLog({ topics: log.topics as string[], data: log.data });
    return parsed!.args.billId;
  }

  /** Bilaterally bind a buyer Bill and an agent Bill. */
  async bind(buyerBillId: bigint, agentBillId: bigint, scopeHash: string): Promise<bigint> {
    const tx = await this.contract.bind(buyerBillId, agentBillId, scopeHash);
    const receipt = await tx.wait();
    const log = receipt.logs.find((l: any) => {
      try { return this.contract.interface.parseLog({ topics: l.topics as string[], data: l.data })?.name === "BillsBound"; }
      catch { return false; }
    });
    if (!log) throw new Error("BillsBound event not found");
    const parsed = this.contract.interface.parseLog({ topics: log.topics as string[], data: log.data });
    return parsed!.args.bindingId;
  }

  /**
   * Bind with structured IntentPackage (new in v2).
   * Validates: buyer/seller match bill owners, amounts match, intent not expired.
   */
  async bindWithIntent(
    intent: IntentPackage,
    buyerBillId: bigint,
    sellerBillId: bigint,
  ): Promise<bigint> {
    const tx = await this.contract.bindWithIntent(intent, buyerBillId, sellerBillId);
    const receipt = await tx.wait();
    const log = receipt.logs.find((l: any) => {
      try { return this.contract.interface.parseLog({ topics: l.topics as string[], data: l.data })?.name === "IntentBound"; }
      catch { return false; }
    });
    if (!log) throw new Error("IntentBound event not found");
    const parsed = this.contract.interface.parseLog({ topics: log.topics as string[], data: log.data });
    return parsed!.args.bindingId;
  }

  /** Settle a Binding: verify proof, burn both Bills, release funds. */
  async settle(bindingId: bigint, proofHash: string): Promise<string> {
    const tx = await this.contract.settle(bindingId, proofHash);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  async unlock(billId: bigint): Promise<string> {
    const tx = await this.contract.unlock(billId);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  async getBill(billId: bigint): Promise<BillToken> {
    const raw = await this.contract.getBill(billId);
    return {
      billId:   raw.billId,
      owner:    raw.owner,
      token:    raw.token,
      amount:   raw.amount,
      state:    raw.state,
      mintedAt: raw.mintedAt,
    };
  }

  async getBinding(bindingId: bigint): Promise<Binding> {
    const raw = await this.contract.getBinding(bindingId);
    return {
      bindingId:        raw.bindingId,
      buyerBillId:      raw.buyerBillId,
      agentBillId:      raw.agentBillId,
      scopeHash:        raw.scopeHash,
      state:            raw.state,
      createdAt:        raw.createdAt,
      settleAfter:      raw.settleAfter,
      proofHash:        raw.proofHash,
      disputedAt:       raw.disputedAt,
      disputeInitiator: raw.disputeInitiator,
    };
  }

  async getIntentPackage(bindingId: bigint): Promise<StoredIntentPackage> {
    const raw = await this.contract.getIntentPackage(bindingId);
    return {
      buyer:          raw.buyer,
      seller:         raw.seller,
      serviceType:    raw.serviceType,
      requirements:   raw.requirements,
      amount:         raw.amount,
      penaltyRate:    raw.penaltyRate,
      deadline:       raw.deadline,
      expiresAt:      raw.expiresAt,
      proofSchema:    raw.proofSchema,
      verifier:       raw.verifier,
      disputeWindow:  raw.disputeWindow,
    };
  }

  async checkInvariant(token: string): Promise<boolean> {
    return this.contract.checkInvariant(token);
  }

  // Admin
  async setTokenAllowed(token: string, allowed: boolean): Promise<void> {
    const tx = await this.contract.setTokenAllowed(token, allowed);
    await tx.wait();
  }

  async setDisputeWindow(seconds: bigint): Promise<void> {
    const tx = await this.contract.setDisputeWindow(seconds);
    await tx.wait();
  }

  async admin(): Promise<string> { return this.contract.admin(); }
  async attestationGateway(): Promise<string> { return this.contract.attestationGateway(); }
}

// ── VerifierRegistry Client ───────────────────────────────────────────────────

export class VerifierRegistry extends BaseClient {
  constructor(opts: ClientOptions) {
    super(opts, VERIFIER_REGISTRY_ABI);
  }

  async registerVerifier(wallet: string, endpointUrl: string): Promise<void> {
    const tx = await this.contract.registerVerifier(wallet, endpointUrl);
    await tx.wait();
  }

  async deregisterVerifier(wallet: string): Promise<void> {
    const tx = await this.contract.deregisterVerifier(wallet);
    await tx.wait();
  }

  /** Stake tokens to become an active verifier. Must approve token first. */
  async stake(amount: bigint): Promise<void> {
    const stakingTokenAddr = await this.contract.stakingToken();
    const erc20 = new ethers.Contract(stakingTokenAddr, ERC20_ABI, this.wallet);
    const approveTx = await erc20.approve(this.contract.target, amount);
    await approveTx.wait();
    const tx = await this.contract.stake(amount);
    await tx.wait();
  }

  async unstake(amount: bigint): Promise<void> {
    const tx = await this.contract.unstake(amount);
    await tx.wait();
  }

  /** Admin: slash a verifier for bad behavior */
  async slash(verifier: string, amount: bigint): Promise<void> {
    const tx = await this.contract.slash(verifier, amount);
    await tx.wait();
  }

  /** Admin: reward a verifier for successful attestation */
  async rewardVerifier(verifier: string): Promise<void> {
    const tx = await this.contract.rewardVerifier(verifier);
    await tx.wait();
  }

  async getVerifier(wallet: string): Promise<VerifierInfo> {
    const raw = await this.contract.getVerifier(wallet);
    return {
      wallet:                raw.wallet,
      endpointUrl:           raw.endpointUrl,
      active:                raw.active,
      stakeAmount:           raw.stakeAmount,
      successCount:          raw.successCount,
      falseAttestationCount: raw.falseAttestationCount,
      totalEarnings:         raw.totalEarnings,
      slashedAmount:         raw.slashedAmount,
    };
  }

  async isVerifierActive(wallet: string): Promise<boolean> {
    return this.contract.isVerifierActive(wallet);
  }

  async getRequiredThreshold(): Promise<bigint> { return this.contract.getRequiredThreshold(); }
  async getTotalVerifiers(): Promise<bigint> { return this.contract.getTotalVerifiers(); }
  async admin(): Promise<string> { return this.contract.admin(); }
  async stakingToken(): Promise<string> { return this.contract.stakingToken(); }
  async minStake(): Promise<bigint> { return this.contract.minStake(); }
  async verificationReward(): Promise<bigint> { return this.contract.verificationReward(); }
}

// ── ScoringEngine Client ──────────────────────────────────────────────────────

export class ScoringEngine extends BaseClient {
  constructor(opts: ClientOptions) {
    super(opts, SCORING_ENGINE_ABI);
  }

  async getScore(party: string): Promise<ScoringVector> {
    const raw = await this.contract.getScore(party);
    return {
      reputationScore:  raw.reputationScore,
      settlementCount:  raw.settlementCount,
      successRate:      raw.successRate,
      avgSpeed:         raw.avgSpeed,
      disputeCount:     raw.disputeCount,
      disputeWinRate:   raw.disputeWinRate,
      slashedCount:     raw.slashedCount,
      lastUpdated:      raw.lastUpdated,
    };
  }

  /** Admin: record settlement for scoring */
  async recordSettlement(seller: string, buyer: string, verifier: string, speedRatio: bigint): Promise<void> {
    const tx = await this.contract.recordSettlement(seller, buyer, verifier, speedRatio);
    await tx.wait();
  }

  /** Admin: record dispute resolution outcome */
  async recordDisputeResolution(seller: string, buyer: string, verifier: string, sellerWon: boolean): Promise<void> {
    const tx = await this.contract.recordDisputeResolution(seller, buyer, verifier, sellerWon);
    await tx.wait();
  }

  async admin(): Promise<string> { return this.contract.admin(); }
  async authorizedSettler(): Promise<string> { return this.contract.authorizedSettler(); }
}

// ── EvidenceChain Client ──────────────────────────────────────────────────────

export class EvidenceChain extends BaseClient {
  constructor(opts: ClientOptions) {
    super(opts, EVIDENCE_CHAIN_ABI);
  }

  async submitEvidence(evidence: Evidence): Promise<string> {
    const tx = await this.contract.submitEvidence(evidence);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  async submitEvidenceBatch(items: Evidence[]): Promise<string> {
    const tx = await this.contract.submitEvidenceBatch(items);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  /** Admin: invalidate a previously submitted evidence */
  async invalidateEvidence(evidenceHash: string): Promise<string> {
    const tx = await this.contract.invalidateEvidence(evidenceHash);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  async getEvidence(evidenceHash: string): Promise<Evidence> {
    const raw = await this.contract.getEvidence(evidenceHash);
    return {
      evidenceType: raw.evidenceType,
      bindingId:    raw.bindingId,
      submitter:    raw.submitter,
      data:         raw.data,
      timestamp:    raw.timestamp,
      isValid:      raw.isValid,
      hash:         raw.hash,
    };
  }

  async getEvidenceCount(bindingId: bigint): Promise<bigint> {
    return this.contract.getEvidenceCount(bindingId);
  }

  async admin(): Promise<string> { return this.contract.admin(); }
}

// ── Helpers ───────────────────────────────────────────────────────────────────

/** One-shot: lock tokens on both sides and bind with intent */
export async function quickBind(
  karma: KarmaBilateral,
  token: string,
  buyerPk: string,
  sellerPk: string,
  intent: IntentPackage,
  rpc: string,
): Promise<{ buyerBillId: bigint; sellerBillId: bigint; bindingId: bigint }> {
  const buyerKarma = new KarmaBilateral({ rpc, privateKey: buyerPk, contract: karma.contract.target as string });
  const sellerKarma = new KarmaBilateral({ rpc, privateKey: sellerPk, contract: karma.contract.target as string });

  const buyerBillId  = await buyerKarma.lock(token, intent.amount);
  const sellerBillId = await sellerKarma.lock(token, intent.amount);

  const bindingId = await buyerKarma.bindWithIntent(intent, buyerBillId, sellerBillId);
  return { buyerBillId, sellerBillId, bindingId };
}

// ── Re-export ABIs ────────────────────────────────────────────────────────────
export { KARMA_BILATERAL_ABI, VERIFIER_REGISTRY_ABI, SCORING_ENGINE_ABI, EVIDENCE_CHAIN_ABI, ERC20_ABI };
