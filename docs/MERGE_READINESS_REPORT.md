# Merge readiness report — Trusted Agent MVP (Phases 2–4)

**Date:** 2026-05-09  
**Scope:** Public repository only. **No new architecture or features** beyond what is already on the Trusted Agent branches. This document answers merge order, PR dependencies, tests run in this environment, and safety for `main`.

---

## 1. Executive conclusion

| Question | Answer |
|----------|--------|
| Can `main` safely accept the Trusted Agent MVP? | **Yes**, from a **public-surface** perspective: work is **adapter + docs + scripts + tests** only. It does **not** add a second on-chain settlement or evidence system; it maps into existing `NonCustodialAgentPayment` / `proofHash` semantics and optional testnet helpers. |
| Duplicate settlement/evidence system? | **No.** Core contracts and OpenAPI evidence shapes are unchanged in role; new code is **integration and structural validation** only. |
| Private logic in public repo? | **No** new private risk scoring; stress and verification paths remain **structural-only** (see `docs/PRIVATE_ALIGNMENT_REPORT.md`). |

---

## 2. PR merge order (recommended)

### Option A — **Single merge (preferred)**

1. **Merge [PR #29](https://github.com/AtoB101/Karma/pull/29)** (`cursor/trusted-agent-phase4-stress-2fe5`) into `main` **only**.

**Rationale:** Branch `cursor/trusted-agent-phase4-stress-2fe5` is **linearly stacked** on `main` and already contains the three commits for Phases 2, 3, and 4 (alignment + offchain MVP, testnet scripts, stress harness). Merging **#29** brings **all** Trusted Agent public work in one step.

2. **Close or supersede** [PR #27](https://github.com/AtoB101/Karma/pull/27) and [PR #28](https://github.com/AtoB101/Karma/pull/28) **without merging** them separately (unless your process requires per-PR audit history). Merging #27 then #28 then #29 risks **duplicate commits** or unnecessary **rebase/conflict** work.

### Option B — Sequential merges (only if required by policy)

If **#27** or **#28** must land on `main` first for procedural reasons:

1. Merge **#27** → `main`  
2. **Rebase or merge `main` into #28**, resolve conflicts, merge **#28**  
3. **Rebase or merge `main` into #29**, resolve conflicts, merge **#29**

This path is **higher friction** because later branches duplicate earlier file paths (`trusted_agent_runtime/`, `docs/`, `scripts/`).

---

## 3. Does PR #29 depend on PR #28?

| Dependency | Explanation |
|------------|-------------|
| **Git / content** | **No.** PR **#29’s branch already includes the same Phase 3 commits** that PR **#28** introduced (testnet client + scripts). You do **not** need to merge **#28** before **#29** if you merge **#29** alone. |
| **If #28 merged first** | **#29 must be updated** (merge `main` into #29 or rebase) so GitHub sees a clean diff; file-level conflicts are **unlikely** if #28 and #29 touched the same tree consistently, but duplicate merges of the same logical change must be avoided. |

**Summary:** **#29 does not depend on #28 being merged first**; **#29 supersedes #28** for a one-shot merge into `main`.

---

## 4. Phase 2 + 3 + 4 conflict check (logical + Git)

| Layer | Phase 2 | Phase 3 | Phase 4 | Conflict? |
|-------|---------|---------|---------|-----------|
| Settlement semantics | Offchain plan → existing contract names | On-chain optional scripts + same ABI surface | Stress uses **same** `EvidenceAdapter` / `SettlementAdapter` / verify | **None** — one adapter stack. |
| Evidence / `proofHash` | `karma-ta:v1/sha256/...` pointer | `createBill` uses same string | Stress reuses hashing; optional `bundle_id`/`created_at` for determinism | **None** — Phase 4 extends `build_evidence_bundle` **backward-compatibly**. |
| Verification | Structural `verify_evidence_bundle_structural` | N/A | Sort key `(step_index, receipt_id)` only stabilizes ordering | **None** — compatible with Phase 2 flows. |

**Git merge dry-run:** `git merge origin/main` on `cursor/trusted-agent-phase4-stress-2fe5` reported **“Already up to date.”** (branch is **ahead** of `main`; no pending upstream commits to conflict in this clone).

---

## 5. Tests run together (this environment)

| Suite | Command | Result (2026-05-09) |
|-------|---------|---------------------|
| Python unit / stress | `python3 -m unittest discover -s tests -p 'test_*.py' -v` | **15 tests, OK** (8 `test_trusted_agent_runtime` + 7 `test_trusted_agent_stress`) |
| Playwright (Agent Guard) | `npm ci` then `npx playwright install chromium` then `npm run test:agent-guard` | **3 passed** (after browser install; first run failed until `playwright install`) |
| Visibility guard | `bash scripts/visibility-guard.sh "origin/main..HEAD"` | **PASS** (full Trusted Agent diff vs `main`) |
| Trust engine public schema | `bash scripts/test-trust-engine-public-schema.sh` | **OK** |
| Foundry | `forge test` | **Not executed** — `forge` not installed in this agent image. **CI** (`.github/workflows/forge-ci.yml`) is the source of truth for Solidity tests. |

### Expected outputs (success)

- **unittest:** `Ran 15 tests in … OK` (or similar count if more tests are added on `main`).
- **Playwright:** `3 passed` for `tests/agent-service-guard.spec.js`.
- **visibility-guard:** `[visibility-guard] PASS`.
- **trust-engine schema script:** `OK   trust-engine public schema fields are present`.
- **forge (when available):** `forge test` exits **0**; CI logs should show all karma-core tests green.

---

## 6. Commands to re-run before merge (checklist)

Run from repository root after `git checkout` of the branch to merge (e.g. `cursor/trusted-agent-phase4-stress-2fe5`):

```bash
python3 -m unittest discover -s tests -p 'test_*.py' -v
npm ci
npx playwright install chromium   # once per machine/CI image
npm run test:agent-guard
bash scripts/visibility-guard.sh
bash scripts/test-trust-engine-public-schema.sh
```

If `forge` is installed:

```bash
forge test
```

Optional smoke (no chain required):

```bash
python3 scripts/trusted_agent_minimal_flow.py --output-dir /tmp/ta-min
python3 scripts/testnet_full_flow.py --output-dir /tmp/ta-hybrid
python3 scripts/stress_trusted_agent_runtime.py --agents 100 --malicious-rate 0.1 --seed 42 --output-dir /tmp/stress
```

---

## 7. Merge conflicts (prediction)

| Area | Risk |
|------|------|
| `trusted_agent_runtime/` | Low if **only #29** merges; higher if **#27/#28 merged separately** first (same paths). |
| `docs/PUBLIC_ALIGNMENT_REPORT.md` | Low unless another PR edits the same sections. |
| `scripts/` | Low; new files are additive. |
| `karma-core/contracts/` | **Untouched** by Trusted Agent PRs in this series — no contract merge conflicts from this work. |

---

## 8. Sign-off (definition of done)

- [x] **All public tests available here pass** (Python + Playwright + listed scripts). **Forge** deferred to CI / local Foundry install.
- [x] **Merge order documented:** prefer **#29 only**; **#29 does not require #28 merged first** (content already included).
- [x] **No duplicate settlement/evidence system** in design or code touched by these phases.
- [x] **Public repo remains structural-only** for Trusted Agent (no private risk engine logic).

---

## 9. Post-merge (operational, not blocking)

- Ensure **CI** runs **forge**, **Playwright** (with browser cache or `playwright install`), and any **security** workflows on `main` after merge.
- Mark **#27** / **#28** as superseded by **#29** to avoid double-merge.
