# Karma Open Source Launch Checklist

This checklist is a practical launch plan for opening Karma to external builders
while preserving focus on the core settlement story:

> EIP-712 signed off-chain intent -> on-chain verifiable settlement

## 1) Repository Readiness (must have)

- [ ] License file present (`LICENSE`, recommend MIT or Apache-2.0)
- [ ] `README.md` states problem, core flow, and quickstart clearly
- [ ] `SECURITY.md` available with disclosure process and proof boundaries
- [ ] `docs/SECURITY_SUMMARY_CN_EN.md` linked for external stakeholders
- [ ] `docs/SIGNING_PAYLOAD_SPEC.md` covers backend integration details
- [ ] `foundry.lock` and `lib/forge-std` pinned for reproducibility

## 2) Contribution Infrastructure (must have)

- [ ] `CONTRIBUTING.md` with local setup, coding style, and PR flow
- [ ] `CODE_OF_CONDUCT.md` for community behavior standards
- [ ] Issue templates:
  - [ ] bug report
  - [ ] feature request
  - [ ] security concern redirect (non-public)
- [ ] Pull request template with:
  - [ ] scope
  - [ ] test evidence
  - [ ] risk notes

## 3) Quality Gates (must have)

- [ ] CI required on all PRs:
  - [ ] `forge test -vv`
  - [ ] core scenario test (`ScenarioFlow`)
  - [ ] at least one invariant suite
- [ ] Scheduled security jobs:
  - [ ] Slither
  - [ ] Echidna
- [ ] Release/security milestone jobs:
  - [ ] Certora critical rule set

## 4) Release Shape (should have)

- [ ] `CHANGELOG.md` initialized
- [ ] Semantic versioning policy documented
- [ ] Tags for stable demo baselines (for reproducible references)
- [ ] Minimal architecture diagram (core contracts and trust boundaries)

## 5) Community Narrative (should have)

- [ ] One sentence positioning for all channels
- [ ] "Do one thing well" scope statement pinned in README
- [ ] Public roadmap split by:
  - [ ] V1 core settlement
  - [ ] V1.5 integration polish
  - [ ] V2 optional expansion

## 6) Suggested Launch Sequence

1. Freeze a release candidate commit.
2. Run full quality gates and archive evidence artifacts.
3. Publish release notes with known limits and deferred scope.
4. Announce with:
   - one-page security summary,
   - demo command (`./scripts/run_focus_demo.sh`),
   - contribution guide.
5. Triage first external issues and tighten docs from real feedback.

## 7) Exit Criteria (ready to go public)

- [ ] New contributor can run demo in one command
- [ ] New contributor can run full tests from docs only
- [ ] Security posture can be understood from README + SECURITY docs
- [ ] Core flow is explained in under one minute without module overload
