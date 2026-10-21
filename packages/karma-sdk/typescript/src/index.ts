/**
 * @karma/sdk — TypeScript client for Karma Protocol (all 5 contracts)
 *
 * Quick start:
 *   import { KarmaBilateral, VerifierRegistry, ScoringEngine, EvidenceChain } from '@karma/sdk'
 *
 *   const karma  = new KarmaBilateral({ rpc, privateKey, contract: KARMA_ADDR })
 *   const vrf    = new VerifierRegistry({ rpc, privateKey, contract: REGISTRY_ADDR })
 *
 *   // Lock → bind → settle → finalizeSettle
 *   const billId = await karma.lock(USDC_ADDRESS, 100_000_000n)
 *   const bindingId = await karma.bind(buyerBillId, agentBillId, scopeHash)
 *   await karma.settle(bindingId, proofHash)       // FINALIZING
 *   await karma.finalizeSettle(bindingId)          // after dispute window
 */

import { ethers } from "ethers";

// ── ABI Definitions ───────────────────────────────────────────────────────────

const KARMA_BILATERAL_ABI = [
  "function lock(address token, uint256 amount) returns (uint256 billId)",
  "function lockFor(address token, uint256 amount, address master) returns (uint256 billId)",
  "function bind(uint256 buyerBillId, uint256 agentBillId, bytes32 scopeHash) returns (uint256 bindingId)",
  "function bindWithIntent(tuple(address buyer, address seller, bytes32 serviceType, bytes requirements, uint256 amount, uint256 penaltyRate, uint256 deadline, uint256 expiresAt, bytes32 proofSchema, bytes32[] requiredProofFields, address verifier, uint256 disputeWindow, address[] arbitrators) intent, uint256 buyerBillId, uint256 sellerBillId) returns (uint256 bindingId)",
  "function settle(uint256 bindingId, bytes32 proofHash)",
  "function finalizeSettle(uint256 bindingId)",
  "function dispute(uint256 bindingId, bytes32 evidenceHash)",
  "function submitArbitrationEvidence(uint256 bindingId, bytes32 evidenceHash)",
  "function autoResolveArbitration(uint256 bindingId)",
  "function resolveDispute(uint256 bindingId, uint16 buyerShareBps)",
  "function refundOnTimeout(uint256 bindingId)",
  "function unlock(uint256 billId)",
  "function finalizeAfter(uint256 bindingId) view returns (uint256)",
  "function getBill(uint256 billId) view returns (tuple(address owner, uint8 state, address token, uint256 amount))",
  "function getBinding(uint256 bindingId) view returns (tuple(uint256 bindingId, uint256 buyerBillId, uint256 agentBillId, bytes32 scopeHash, uint8 state, uint256 createdAt, uint256 settleAfter, bytes32 proofHash, uint256 settleSubmittedAt, uint256 disputedAt, address disputeInitiator))",
  "function getIntentPackage(uint256 bindingId) view returns (tuple(address buyer, address seller, bytes32 serviceType, bytes requirements, uint256 amount, uint256 penaltyRate, uint256 deadline, uint256 expiresAt, bytes32 proofSchema, address verifier, uint256 disputeWindow))",
  "function checkInvariant(address token) view returns (bool)",
  "function setTokenAllowed(address token, bool allowed)",
  "function setBatchThreshold(address token, uint256 threshold)",
  "function setSettleDelay(uint256 seconds_)",
  "function setSettleTimeout(uint256 seconds_)",
  "function setAttestationGateway(address gateway)",
  "function admin() view returns (address)",
  "function tokenAllowed(address) view returns (bool)",
  "function identityRegistry() view returns (address)",
  "function freeBalance(address) view returns (uint256)",
  "function attestationGateway() view returns (address)",
  "event BillMinted(uint256 indexed billId, address indexed owner, address token, uint256 amount)",
  "event BillsBound(uint256 indexed bindingId, uint256 buyerBillId, uint256 agentBillId, bytes32 scopeHash)",
  "event IntentBound(uint256 indexed bindingId, uint256 buyerBillId, uint256 agentBillId, bytes32 intentHash)",
  "event BindingSettled(uint256 indexed bindingId, bytes32 proofHash, uint256 buyerAmount, uint256 agentAmount)",
];

const VERIFIER_REGISTRY_ABI = [
  "function registerVerifier(address wallet, string calldata endpointUrl, uint256 stakeAmount)",
  "function removeVerifier(address wallet)",
  "function setThresholds(uint256 threshold, uint256 totalVerifiers)",
  "function setStakingConfig(address token, uint256 minStake_, uint256 reward)",
  "function setAuthorizedCaller(address caller, bool allowed)",
  "function authorizedCallers(address caller) view returns (bool)",
  "function stake(uint256 amount)",
  "function unstake(uint256 amount)",
  "function slash(address verifier, uint256 amount, string calldata reason)",
  "function rewardVerifier(address verifier, uint256 amount)",
  "function recordAttestation(address verifier, bool success)",
  "function verifiers(address wallet) view returns (address wallet, string endpointUrl, bool active, uint256 stakeAmount, uint256 successCount, uint256 falseAttestationCount, uint256 totalEarnings, uint256 slashedAmount)",
  "function isActiveVerifier(address wallet) view returns (bool)",
  "function getRequiredThreshold() view returns (uint256)",
  "function getTotalVerifiers() view returns (uint256)",
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

const KARMA_IDENTITY_REGISTRY_ABI = [
  "function registerIdentity(bytes32 masterAgentId)",
  "function addSubAgent(address subWallet, bytes32 subAgentId)",
  "function removeSubAgent(address subWallet)",
  "function setSubAgentBounds(address subWallet, uint256 allowance, uint256 perTxLimit, uint256 expiresAt)",
  "function isAuthorized(address subWallet, uint256 amount) view returns (bool)",
  "function getSubAgents(address master) view returns (tuple(address subWallet, bytes32 subAgentId, address master, uint256 allowance, uint256 perTxLimit, uint256 expiresAt, uint8 status, uint256 addedAt, uint256 removedAt)[])",
  "function getIdentity(address master) view returns (tuple(address masterWallet, bytes32 masterAgentId, bool registered))",
  "function getMasterOf(address subWallet) view returns (address)",
  "function getMaster(bytes32 subAgentId) view returns (address)",
  "function bilateral() view returns (address)",
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
  billId: bigint;
  owner:  string;
  token:  string;
  amount: bigint;
  state:  number;
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
  settleSubmittedAt: bigint;
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

export interface SubAgent {
  subWallet:   string;
  subAgentId:  string;
  master:      string;
  allowance:   bigint;
  perTxLimit:  bigint;
  expiresAt:   bigint;
  status:      number;
  addedAt:     bigint;
  removedAt:   bigint;
}

export interface KarmaIdentity {
  masterWallet:  string;
  masterAgentId: string;
  registered:    boolean;
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

  /** Sub-agent delegated lock: signing wallet locks master's token, mints Bill to master. */
  async lockFor(token: string, amount: bigint, master: string): Promise<bigint> {
    const tx = await this.contract.lockFor(token, amount, master);
    const receipt = await tx.wait();
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

  /** Submit settlement proof → FINALIZING (USDC not released yet). */
  async settle(bindingId: bigint, proofHash: string): Promise<string> {
    const tx = await this.contract.settle(bindingId, proofHash);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  /** Finalize after dispute window; burns bills and releases USDC. */
  async finalizeSettle(bindingId: bigint): Promise<string> {
    const tx = await this.contract.finalizeSettle(bindingId);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  /** Challenge a FINALIZING binding within the dispute window. */
  async dispute(bindingId: bigint, evidenceHash: string): Promise<string> {
    const tx = await this.contract.dispute(bindingId, evidenceHash);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  /** Submit / update evidence for a DISPUTED binding during the evidence window. */
  async submitArbitrationEvidence(bindingId: bigint, evidenceHash: string): Promise<string> {
    const tx = await this.contract.submitArbitrationEvidence(bindingId, evidenceHash);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  /** Anyone may trigger after the evidence window closes; applies auto-resolution rules. */
  async autoResolveArbitration(bindingId: bigint): Promise<string> {
    const tx = await this.contract.autoResolveArbitration(bindingId);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  /** Admin: resolve a dispute with an explicit buyer share in basis points. */
  async resolveDispute(bindingId: bigint, buyerShareBps: bigint): Promise<string> {
    const tx = await this.contract.resolveDispute(bindingId, buyerShareBps);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  /** Refund when settle timeout elapses without a valid settlement. */
  async refundOnTimeout(bindingId: bigint): Promise<string> {
    const tx = await this.contract.refundOnTimeout(bindingId);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  async unlock(billId: bigint): Promise<string> {
    const tx = await this.contract.unlock(billId);
    const receipt = await tx.wait();
    return receipt.hash;
  }

  /** Unix timestamp when finalizeSettle becomes available (0 if not FINALIZING). */
  async finalizeAfter(bindingId: bigint): Promise<bigint> {
    return this.contract.finalizeAfter(bindingId);
  }

  async getBill(billId: bigint): Promise<BillToken> {
    const raw = await this.contract.getBill(billId);
    return {
      billId,
      owner:  raw.owner,
      token:  raw.token,
      amount: raw.amount,
      state:  raw.state,
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
      settleSubmittedAt: raw.settleSubmittedAt,
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

  async setSettleDelay(seconds: bigint): Promise<void> {
    const tx = await this.contract.setSettleDelay(seconds);
    await tx.wait();
  }

  async admin(): Promise<string> { return this.contract.admin(); }
  async attestationGateway(): Promise<string> { return this.contract.attestationGateway(); }
  async identityRegistry(): Promise<string> { return this.contract.identityRegistry(); }
  async freeBalance(address: string): Promise<bigint> { return this.contract.freeBalance(address); }
}

// ── KarmaIdentityRegistry Client ─────────────────────────────────────────────────────────────

export class KarmaIdentityRegistry extends BaseClient {
  constructor(opts: ClientOptions) {
    super(opts, KARMA_IDENTITY_REGISTRY_ABI);
  }

  /** Register the signing wallet as a master identity. */
  async registerIdentity(masterAgentId: string): Promise<void> {
    const tx = await this.contract.registerIdentity(masterAgentId);
    await tx.wait();
  }

  /** Add an active sub-agent wallet under the signing master. */
  async addSubAgent(subWallet: string, subAgentId: string): Promise<void> {
    const tx = await this.contract.addSubAgent(subWallet, subAgentId);
    await tx.wait();
  }

  /** Deactivate a sub-agent (reverts if it holds bound balance). */
  async removeSubAgent(subWallet: string): Promise<void> {
    const tx = await this.contract.removeSubAgent(subWallet);
    await tx.wait();
  }

  /** Set a sub-agent spending envelope: budget, per-tx cap, expiry. */
  async setSubAgentBounds(subWallet: string, allowance: bigint, perTxLimit: bigint, expiresAt: bigint = 0n): Promise<void> {
    const tx = await this.contract.setSubAgentBounds(subWallet, allowance, perTxLimit, expiresAt);
    await tx.wait();
  }

  async isAuthorized(subWallet: string, amount: bigint): Promise<boolean> {
    return this.contract.isAuthorized(subWallet, amount);
  }

  async getSubAgents(master: string): Promise<SubAgent[]> {
    const raw = await this.contract.getSubAgents(master);
    return raw.map((s: any) => ({
      subWallet: s.subWallet, subAgentId: s.subAgentId, master: s.master,
      allowance: s.allowance, perTxLimit: s.perTxLimit, expiresAt: s.expiresAt,
      status: s.status, addedAt: s.addedAt, removedAt: s.removedAt,
    }));
  }

  async getIdentity(master: string): Promise<KarmaIdentity> {
    const raw = await this.contract.getIdentity(master);
    return { masterWallet: raw.masterWallet, masterAgentId: raw.masterAgentId, registered: raw.registered };
  }

  async getMasterOf(subWallet: string): Promise<string> { return this.contract.getMasterOf(subWallet); }
  async getMaster(subAgentId: string): Promise<string> { return this.contract.getMaster(subAgentId); }
  async bilateral(): Promise<string> { return this.contract.bilateral(); }
}

// ── VerifierRegistry Client ───────────────────────────────────────────────────

export class VerifierRegistry extends BaseClient {
  constructor(opts: ClientOptions) {
    super(opts, VERIFIER_REGISTRY_ABI);
  }

  async registerVerifier(wallet: string, endpointUrl: string, stakeAmount: bigint = 0n): Promise<void> {
    const tx = await this.contract.registerVerifier(wallet, endpointUrl, stakeAmount);
    await tx.wait();
  }

  async removeVerifier(wallet: string): Promise<void> {
    const tx = await this.contract.removeVerifier(wallet);
    await tx.wait();
  }

  /** @deprecated Use removeVerifier */
  async deregisterVerifier(wallet: string): Promise<void> {
    return this.removeVerifier(wallet);
  }

  /** Admin: authorize Gateway (etc.) for recordAttestation / rewardVerifier */
  async setAuthorizedCaller(caller: string, allowed: boolean): Promise<void> {
    const tx = await this.contract.setAuthorizedCaller(caller, allowed);
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
  async slash(verifier: string, amount: bigint, reason: string = ""): Promise<void> {
    const tx = await this.contract.slash(verifier, amount, reason);
    await tx.wait();
  }

  /**
   * Authorized caller only (Gateway/admin): pay verification reward.
   * Not discoverable as a public agent skill — privileged registry write.
   */
  async rewardVerifier(verifier: string, amount: bigint): Promise<void> {
    const tx = await this.contract.rewardVerifier(verifier, amount);
    await tx.wait();
  }

  /** Authorized caller only (Gateway/admin): record attestation outcome. */
  async recordAttestation(verifier: string, success: boolean): Promise<void> {
    const tx = await this.contract.recordAttestation(verifier, success);
    await tx.wait();
  }

  async getVerifier(wallet: string): Promise<VerifierInfo> {
    const raw = await this.contract.verifiers(wallet);
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
    return this.contract.isActiveVerifier(wallet);
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
export { KARMA_BILATERAL_ABI, VERIFIER_REGISTRY_ABI, SCORING_ENGINE_ABI, EVIDENCE_CHAIN_ABI, KARMA_IDENTITY_REGISTRY_ABI, ERC20_ABI };
