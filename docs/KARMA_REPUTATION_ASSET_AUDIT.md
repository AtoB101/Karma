# KARMA_REPUTATION_ASSET_AUDIT.md

**Audit type:** On-chain reputation asset system (code-path only)  
**Repo:** https://github.com/AtoB101/Karma  
**Tree audited:** workspace at `7223e37` (includes `origin/main` + PR #145 FeeBridge merge)  
**Method:** Solidity / Python / DB / API / tests traced end-to-end. README and comments were ignored as proof of implementation.

**ONE SENTENCE CONCLUSION:** Karma is an off-chain score ledger plus on-chain *settlement evidence hashes*; it is not an on-chain reputation-asset infrastructure.

---

## 1. Executive Summary

Karma has **several parallel reputation/identity/evidence stacks**. None of them closes the loop:

`economic activity → evidence → verification → reputation write → on-chain verifiable persistence → third-party verify without Karma servers → economic rights (fee/limit/collateral)`.

The only Solidity contract that *could* be a reputation registry (`ScoringEngine`) is **deployed and authorized** (`scoring.setAuthorizedSettler(address(karma))` in `DeployKarmaBilateral.s.sol`) but **`KarmaBilateral.sol` never imports or calls it**. `EvidenceChain.sol` is likewise deployed and never called from Bilateral. Live “reputation” lives in PostgreSQL (`reputation` table), MiniApp in-memory/`persist_json` maps, and a local JSON file (`.karma_data/settlement_attestations.json`).

**Verdict: PARTIAL / NO as a reputation asset. Formal answer in §19: NO for the full claim; PARTIAL for fragments.**

---

## 2. Current Implementation Conclusion

| Claim | Reality |
|---|---|
| Real trades produce Evidence | **Yes, partially.** Off-chain bundles + on-chain `proofHash` on settle. `EvidenceChain` unused. |
| Evidence becomes Reputation | **Yes, off-chain only**, and not via `proofHash`. Score deltas are counters/floats after HTTP settle/MiniApp settle. |
| Reputation accumulates | **Yes, as mutable floats/counters** in DB/JSON/memory. Not an append-only chain of attestations. |
| Bound to real identity | **Weak.** Wallet/SIWE/JSON identity and Postgres `identity_profiles` exist; SBT `KarmaIdentitySBT` is not read by scoring. New wallets = new scores. |
| Third-party verifiable | **Only if they trust Karma API/DB** or recompute a *hash they already have*. No portable VC / Merkle reputation proof. |
| Cross-platform carry | **No protocol-level carry.** `GET /v1/reputation/{agent_id}` is Karma-hosted. |
| Affects fee/limit/collateral | **No.** Discovery *ranking* uses score. `FeeBridge` / `payment_policy` limits do not read reputation. |
| Digital asset | **No.** Not soulbound score NFT, not transferable, not collateralizable. SBT has no score fields. |

---

## 3. Architecture (as coded) and break points

```
Wallet / SIWE / JSON KarmaIdentity / identity_profiles
        │
        ├─ (parallel, unwired) KarmaIdentitySBT.mintOrGet  → soulId only
        ├─ (parallel, unwired) KYARegistry.registerDID     → DID, not score
        ▼
Economic activity: lock/bind/settle (KarmaBilateral) OR HTTP settlement state machine OR MiniApp orders
        │
        ├─ Evidence: EvidenceBundle / MiniApp evidence JSON / proofHash on Binding
        ├─ BREAK: EvidenceChain.submitEvidence never called from Bilateral
        ▼
Verification: private runtime HTTP; MiniApp services.verification_engine; P7 delivery_verification
        │
        ▼
Settlement: Bilateral.settle/finalizeSettle OR api/routes/settlement.py OR MiniApp finalize
        │
        ├─ PATH A: apply_settle_reputation → ReputationModel (Postgres)     [off-chain]
        ├─ PATH B: miniapp_trust.reputation.record_settlement               [memory]
        ├─ PATH C: ScoringEngine.recordSettlement                           [DEAD: Bilateral never calls]
        ▼
Discovery ranking (agent_trust / discovery_priority)  ← only economic “use”
        │
        X  Fee / limit / collateral / settle speed / credit  ← NOT READ
```

**Primary break:** `KarmaBilateral` → `ScoringEngine` / `EvidenceChain` (deploy-time wiring without call sites).

**Secondary break:** off-chain scores never written to chain; chain scores never read by off-chain discovery or FeeBridge.

---

## 4. Identity audit

### 4.1 What exists (three stacks)

**A. On-chain soulbound id (no reputation fields)**  
- Contract: `karma-core/contracts/core/KarmaIdentitySBT.sol`  
- Functions: `mintOrGet(address)`, `ownerOf`, `soulByOwner`, `ownerBySoul`  
- Storage: `mapping(address => uint256) soulByOwner`  
- Tests: `karma-core/contracts/test/KarmaIdentitySBT.t.sol`  
- **Not referenced** by `ScoringEngine`, `KarmaBilateral`, or `ReputationModel`.

**B. On-chain agent DID (stake, not score)**  
- Contract: `karma-core/contracts/core/KYARegistry.sol`  
- Functions: `registerDID`, `revokeDID`, `verifyDID`  
- Storage: `mapping(address agent => Types.AgentDID) didByAgent`  
- Cost: `minStake = 0.01 ether` (Sybil cost for *DID slot*, not for reputation).

**C. Off-chain identities**

| Store | File | Create | Wallet bind |
|---|---|---|---|
| MiniApp JSON | `services/identity_gateway/store.py` `get_or_create_by_wallet`, `create_sub_identity`, `bind_telegram` | `kid_` + hex | `_BY_WALLET` one wallet → one id |
| Postgres | `db/models/orm.py` `IdentityProfileModel` table `identity_profiles` | `services/identity_wallet_binding.py` `_ensure_profile` | `bound_wallet_address` |
| Sub-ids | `SubIdentityModel` / `create_sub_identity` in store | child wallets | parent pays |

API: `api/routes/identities.py`, `api/routes/identity_card.py`, `api/routes/telegram_miniapp_auth.py`.

### 4.2 Required answers

1. **Where created?** MiniApp: `get_or_create_by_wallet`. Runtime: IdentityProfile rows. Chain: `mintOrGet` / `registerDID` if someone calls them (not hooked to MiniApp settle).  
2. **Wallet bind?** SIWE + `bind_telegram` / `identity_wallet_binding.ensure_wallet_authorized_for_runtime_key`. One bound wallet per profile when enforced.  
3. **Long-lived?** JSON persist + Postgres yes; MiniApp reputation `_REP` is process memory (history persist is identity, not score). SBT lives as long as chain.  
4. **Query history?** MiniApp `reputation_of` last 10 `ExecutionRecord`s in `_HISTORY`. Postgres `ReputationModel` is **aggregates only**, no per-event table. Bilateral `getBinding` is trade history, not reputation history.  
5. **Migrate/restore?** SBT: no transfer API (soulbound). Off-chain: copy DB/JSON; no protocol migrate. Sub-identities are extra wallets, not recovery of score.  
6. **Sybil / infinite identities?** **No protocol block.** New EOA → new SBT via `mintOrGet(self)`, new `kid_`, new `ReputationModel` PK `agent_id`. `wash_trade_flags` column is never incremented in application code (only `scripts/seed_demo_data.py` / comment in `scripts/attack_lv2.py`).

---

## 5. Evidence audit

| Layer | Location | What is stored | Mutable |
|---|---|---|---|
| Off-chain bundle | `core/schemas.py` `EvidenceBundle`; `core/evidence/bundle_builder.py` | Receipts, hashes | Yes (DB `EvidenceBundleModel`) |
| MiniApp | `telegram_miniapp_commerce.submit_evidence` | JSON on order | Yes |
| On-chain settle | `KarmaBilateral.settle(bindingId, proofHash)` | `Binding.proofHash` | Frozen after settle path |
| EvidenceChain | `EvidenceChain.submitEvidence` | `Types.Evidence` | `valid` can be flipped by **admin** `invalidateEvidence` |
| Adapter | `settlement_adapter.submit_evidence_hash` | SHA-256 of bundle JSON, used as `proofHash` | Hash only |

**Evidence does not enter ScoringEngine.** `EvidenceChain.sol` comment claims ScoringEngine consumes it; there is **no Solidity call graph** from EvidenceChain → ScoringEngine.

P8 “attestation” (`services/settlement_reputation.py` `seal_settlement_attestation`) is **AES-GCM ciphertext + SHA-256 commitments in a local JSON file**, not L1 storage.

---

## 6. Verification audit

- Public interface: `core/verification/engine.py` — HTTP to `private_runtime_url`; logic described as private.  
- Task worker: `worker/tasks.py` `_async_verify` POST `{private_runtime_url}/v1/verify`.  
- HTTP settle path: `api/routes/settlement.py` gates then `apply_settle_reputation`.  
- MiniApp: `telegram_miniapp_commerce` + `assert_pass_for_settle` (imported from `services.verification_engine`).  
- P7: `services/delivery_verification.py` (ticket stubs, etc.).  
- On-chain: `proofHash` is **not verified on-chain** as TEE/ZK; `settleWithTEE` / `settleWithZKProof` remain unimplemented stubs on Bilateral.

Verification **can** gate MiniApp/HTTP settle. It does **not** update `ScoringEngine`.

---

## 7. Reputation audit

### 7.1 Data structures that actually exist

**Postgres `reputation`** (`db/models/orm.py` `ReputationModel`, migration `db/migrations/0001_initial.py`):

- PK `agent_id`  
- Fields: `role`, `score`, `total_tasks`, `successful_tasks`, `disputed_tasks`, `arbitration_wins`, `arbitration_losses`, `consecutive_successes`, `wash_trade_flags`, `last_updated`  
- Write: `services/agent_trust.py` `record_worker_settlement_outcome`, `record_seller_non_confirm_reputation`, `ensure_reputation_row`  
- Read: `api/routes/reputation.py` `get_reputation`, `leaderboard`; `load_trust_stats_batch`

**MiniApp** (`services/miniapp_trust/reputation.py`):

- `_REP: dict[str, float]` identity_id → score  
- `_HISTORY: list[ExecutionRecord]`  
- Write: `record_settlement` (+1 buyer, +2 seller; `bump_agent_reputation` +2)  
- Read: `reputation_of`, `GET` MiniApp reputation route

**P8 scene ledger** (`settlement_reputation.py`): `_SCENE_REP` keyed by `sha256(agent|{id})`, fields `settled_count`, `success_count`, `score_delta_total`. Disk: `.karma_data/settlement_attestations.json`.

**On-chain vector** (`libraries/Types.sol` `ScoringVector` via `ScoringEngine.scores`): `totalTransactions`, `reputationScore`, `completionRate`, `avgCompletionSpeed`, `disputeRate`, `disputeWinRate`, `penaltyCount`, `confirmationSpeed`, `maliciousDisputeRate`, `verificationAccuracy`, `verificationVolume`, `slashedCount`, `lastUpdated`.  
Write only via `onlySettler` / admin — **settler never calls from Bilateral.**

**Not found:** `ReputationProfile` contract, `ReputationEvent` table, transferable reputation token, EIP-712 signed reputation credential.

### 7.2 Dimensions

Postgres + MiniApp are **thin**: mostly a single `score` plus a few counters. They do **not** persist average fulfillment time, evidence completeness, fraud records as first-class fields (beyond unused `wash_trade_flags`).  
`ScoringEngine` **defines** a richer vector but it is not populated in production path. `DECAY_WINDOW` is unused; `_decayScore` is a subtract, not time decay. `_computeComposite` ignores `PartyType` (`partyTypes[address(this)]` dummy).

### 7.3 Does settle change reputation?

| Path | Updates reputation? |
|---|---|
| `api/routes/settlement.py` after SETTLED | Yes → `apply_settle_reputation` → Postgres |
| MiniApp `settlement_finalize` | Yes → `record_settlement` memory + registry JSON |
| `KarmaBilateral.finalizeSettle` / `_executeSettle` | **No ScoringEngine call** |
| Celery `update_reputation` | POST to **private runtime** `/v1/reputation/update` — not this repo’s ScoringEngine |

---

## 8. On-chain audit (most important)

### A. True Solidity storage

| Contract | Reputation? | Notes |
|---|---|---|
| `ScoringEngine` | Intended registry | **Unwired from Bilateral** |
| `KarmaIdentitySBT` | Identity id only | No score |
| `KYARegistry` | DID | No score |
| `EvidenceChain` | Evidence blobs | Admin can invalidate; unused |
| `KarmaBilateral` Binding | `proofHash`, state | Settlement evidence, not a score |
| `VerifierRegistry` | Stake/weights | Verifier ops, not user reputation asset |
| `KarmaAttestationGateway` | Quorum attest | Can trigger `Bilateral.settle`, not score write |

Deploy: `DeployKarmaBilateral.s.sol` deploys ScoringEngine + EvidenceChain, `setAuthorizedSettler(karma)`. **No `evidence.setAuthorizedVerifier` wired to Bilateral in the same script’s Bilateral calls.** Addresses are printed as env hints; not a live “Reputation Registry” product.

**Contract addresses:** not in this audit (environment-specific). Names above are the only candidates.

### B–F. Off-chain

- **B DB:** `reputation`, `identity_profiles`, `settlements`  
- **C API:** `GET /v1/reputation`, P8 settlement-reputation routes, MiniApp reputation  
- **D Events:** `ScoreUpdated` / `ScoreVectorUpdated` only if ScoringEngine is called (tests: `KarmaIntentPackage.t.sol` calls `scores.recordSettlement` as *this* test contract, not Bilateral)  
- **E JSON:** `.karma_data/settlement_attestations.json`, MiniApp persist  
- **F UI:** console verifier explorer **hardcodes** demo reputation numbers in `apps/console/scripts/verifier-explorer.js` (not live scores)

---

## 9. Cross-platform audit

Third party Agent A / Platform D **without Karma UI**:

- **Chain:** Can read `ScoringEngine.getScore(address)` **if** that address was `registerParty`’d **and** `recordSettlement` ran. Production Bilateral path does neither automatically (`registerParty` is `onlyAdmin`; unregistered parties are skipped: `if (sv.lastUpdated == 0) return`).  
- **HTTP:** `GET /v1/reputation/{agent_id}` requires Karma’s Postgres. Not a cryptographic credential.  
- **P8:** `verify_outcome_commitment` checks hash integrity of **Karma-stored** attestation JSON; stranger cannot verify Alice’s 10,000 trades from L1 alone.  
- **SDK:** `sdk/client.py` `get_reputation` → same HTTP.  
- **EIP-712 / VC / Merkle reputation proof:** not implemented for scores.

**Answer:** A stranger **cannot** independently verify Alice’s Karma reputation as an asset. They can verify **a given binding’s proofHash** on Bilateral if they know `bindingId`.

---

## 10. Economic utility audit

| Lever | Reads reputation? |
|---|---|
| Discovery order | **Yes** — `compute_trust_bonus` / `priority_sort_key` (`services/agent_trust.py`, `services/discovery_priority.py`). Default `drop_ineligible=False` on `apply_trust_rerank` — ranking, not hard ban. |
| MiniApp offer ranking | Display / sort via `reputation_score` (`concierge.py`, `intent_discovery.py`) |
| FeeBridge `quoteFee` | **No** reputation input (`KarmaBilateral` fee path) |
| `payment_policy` single/daily limit | **No** — identity policy, not score |
| Collateral / dispute window / settle speed | **No** score-based params |
| Financing / credit line | **Absent** |

**Classification:** reputation exists as a **ranking signal**, not an **assetized right**. Displaying a score without fee/limit/collateral coupling is not assetization.

---

## 11. Sybil resistance audit

| Attack | Mitigated? |
|---|---|
| Self-score | MiniApp `record_settlement` adds score with no uniqueness beyond order id in memory. HTTP path needs a settlement row (stronger). Chain ScoringEngine would require Bilateral settle — **if wired**. |
| Infinite wallets | **Open.** |
| Fake trades | MiniApp can mark settled without Bilateral lock. HTTP/on-chain paths differ. |
| Erase negatives | DB `score` is a mutable float; no append-only log. Admin can change rows. MiniApp `reset_for_tests`. EvidenceChain `invalidateEvidence` is admin. |
| Transfer score | SBT non-transferable; **score is not on SBT**. Copying `agent_id` in DB would copy score. |
| Sell reputation | No market; trivial to sell a **wallet + DB row** off-protocol. |
| Wash / dust | `wash_trade_flags` **unused**. Volume bump in `record_worker_settlement_outcome`: `5 + min(volume,100)*0.05` — small payments still increment `successful_tasks`. |

---

## 12. Negative reputation audit

- Postgres: `disputed_tasks`, `-15` on dispute, `-8` on fail, P6 `record_seller_non_confirm_reputation` (clamped −5..0).  
- MiniApp: settle-only **positive** deltas in `record_settlement`; disputes do not decrement `_REP` in that module.  
- ScoringEngine: dispute/penalty math exists, unwired.  
- **Not** a public immutable fraud registry. Negatives are mutable counters.

---

## 13. Transfer / asset properties

| Property | Status |
|---|---|
| Transferable | Score: no token. SBT: no transfer API (good for soulbound **id**). |
| Sellable | Not in protocol |
| Collateral / lend | No |
| Delegate | No signed reputation grant |
| Verifiable by stranger | No (see §9) |
| Inheritable | No |
| Cross-platform | No |

Soulbound **identity** without soulbound **score** does not make reputation non-tradable in practice (new wallet + wash).

---

## 14. Code evidence (index)

- `karma-core/contracts/core/ScoringEngine.sol` — `recordSettlement`, `onlySettler`  
- `karma-core/contracts/core/KarmaBilateral.sol` — **zero** `ScoringEngine` / `recordSettlement` references  
- `karma-core/contracts/script/DeployKarmaBilateral.s.sol` L146–L154 — deploy + `setAuthorizedSettler`  
- `karma-core/contracts/core/EvidenceChain.sol` — unused by Bilateral  
- `karma-core/contracts/core/KarmaIdentitySBT.sol` — id only  
- `db/models/orm.py` `ReputationModel`  
- `services/agent_trust.py` `record_worker_settlement_outcome`  
- `services/settlement_reputation.py` `apply_settle_reputation`, `seal_settlement_attestation`  
- `services/miniapp_trust/reputation.py` `record_settlement`  
- `api/routes/reputation.py`, `api/routes/settlement.py`  
- `api/routes/telegram_miniapp_commerce.py` `settlement_finalize`  
- `worker/tasks.py` `update_reputation` → private runtime  
- `karma-core/contracts/test/KarmaIntentPackage.t.sol` — ScoringEngine tested **in isolation**

---

## 15. Missing modules (for a real reputation asset)

1. Bilateral (or Gateway) **must** call `ScoringEngine.recordSettlement` / `recordDisputeResolution` after finalize/dispute, and `registerParty` policy.  
2. Bind score to `KarmaIdentitySBT.soulId` (or KYA DID), not raw EOA alone.  
3. Append-only `ReputationEvent` (chain or merkle-anchored) — not a single mutable `score`.  
4. Wire `EvidenceChain` or freeze `proofHash` as the only evidence input to scoring.  
5. Portable proof: EIP-712 / VC / account-proof of `ScoringVector`.  
6. Economic hooks: fee bps, limits, collateral, dispute privilege **read** `getReputationScore`.  
7. Sybil: stake, unique human/KYA, wash detection writing `wash_trade_flags`.  
8. Unify MiniApp / Postgres / ScoringEngine (today three ledgers).

---

## 16. Risks

- **False marketing:** “on-chain reputation” while scores live in Postgres/JSON.  
- **Wash trading** on MiniApp and HTTP score bumps.  
- **Admin** can invalidate EvidenceChain entries and rewrite DB scores.  
- **ScoringEngine authorizedSettler = Bilateral** with no calls is a footgun (looks wired).  
- **P8 JSON file** is not consensus; multi-instance overwrite.  
- Console verifier “reputation” demo data can be mistaken for production.

---

## 17. Priority (implementation order)

1. P0: Call `ScoringEngine` from Bilateral `_executeSettle` / dispute resolve; `registerParty` on first lock or via SBT.  
2. P0: Stop treating MiniApp memory score as protocol reputation (or persist + require on-chain binding).  
3. P1: Event log of score deltas; no silent DB edits.  
4. P1: Discovery hard-gate optional; FeeBridge/limit read score.  
5. P2: Cross-platform attestation (EIP-712 over `ScoringVector` + soulId).  
6. P2: Wash trading + Sybil (KYA stake already exists — unused for score).

---

## 18. Scores (0–5)

| Dimension | Score | Why |
|---|---|---|
| Identity | 3 | Multiple real systems; SBT/KYA not bound to score |
| Evidence | 4 | Bundles + `proofHash`; EvidenceChain dead |
| Verification | 3 | Real gates on some paths; private/stub/TEE |
| Reputation | 3 | Off-chain engines work; fragmented |
| On-chain Reputation | 2 | Contract + tests; production call path missing |
| Reputation History | 2 | Aggregates; MiniApp last-10 RAM |
| Sybil Resistance | 1 | Unused wash flag; free EOAs |
| Cross-platform Verification | 2 | Hosted API only |
| Economic Utility | 2 | Ranking, not rights |
| Reputation Assetization | 1 | No asset, no portable proof |

**Karma Trust Layer: 46 / 100**  
(sum of ten scores × 2)

---

## 19. YES / PARTIAL / NO

**Question:** Has Karma *truly* implemented: economic behavior → verifiable evidence → **on-chain reputation** → long-term reputation **asset** → cross-platform verification → reputation **economic rights** → trust **assetization**?

### NO

for that conjunction.

### PARTIAL (fragments only)

**Done:** Off-chain score after some settle paths; evidence hashes on Bilateral; identity wallets/SBT/DID as **separate** products; discovery uses DB score; ScoringEngine **source** exists.

**Missing:** Bilateral→ScoringEngine writes; evidence→score coupling; portable third-party verify; fee/limit/collateral; sybil; unified long-term asset.

---

## ONE SENTENCE CONCLUSION

Karma 现在是「链下可变积分 + 链上结算 proofHash」，**不是**真正的链上信誉资产基础设施。

---

## 20. Follow-up implementation (this branch)

Product loop landed as a **dedicated** contract (not `KarmaBilateral`, EIP-170): `KarmaReputationAnchor`.

- Off-chain: undisputed settle → score; default/fraud/dispute → `last_incident_*` + slash path.
- Pack when score/successes pass threshold and 90-day rehab is clean.
- On-chain: non-transferable `scoreE2` + `rewardWeight`; **explicitly no fee waiver**.
- Dividends: `isDividendEligible` / `GET /v1/reputation/{id}/rewards`.
- Still missing vs §19 full claim: ScoringEngine still unwired from Bilateral; MiniApp ledger still separate; third-party portable VC; Sybil.

See `docs/REPUTATION_PACK-zh.md`.
