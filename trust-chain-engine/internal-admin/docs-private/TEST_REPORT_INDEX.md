# OpenClaw v0.1 Test Report Index

Date: 2026-04-26  
Package Status: Ready for internal and partner sharing

## 1) Document Set

### A) Execution Baseline + Final Embedded Record
- File: `docs/OPENCLOW_V01_DEPLOY_TEST_INSTRUCTIONS.txt`
- Purpose:
  - Original execution brief and acceptance criteria
  - Embedded final completion record
  - Artifact schema and compatibility notes
- Primary audience: Engineering, QA, release operators

### B) External-Facing Final Report (English)
- File: `docs/FINAL_TEST_REPORT.md`
- Purpose:
  - Audit-friendly final test report for partner/external review
  - Includes document control, environment, evidence links, and sign-off
- Primary audience: Partners, auditors, cross-org stakeholders

### C) Internal Reporting Version (Chinese)
- File: `docs/FINAL_TEST_REPORT_CN.md`
- Purpose:
  - Chinese internal reporting package aligned with the English structure
  - Suitable for management updates and internal archival
- Primary audience: Internal management, local delivery teams

## 2) Suggested Reading Order

1. `docs/TEST_REPORT_INDEX.md` (this file)
2. `docs/FINAL_TEST_REPORT.md` (external official narrative)
3. `docs/FINAL_TEST_REPORT_CN.md` (internal localized narrative)
4. `docs/OPENCLOW_V01_DEPLOY_TEST_INSTRUCTIONS.txt` (execution-level details and constraints)

## 3) Evidence Artifacts

- `results/run-050.json`
- `results/run-100.json`
- `results/aggregate-summary.json`

Note:
- Use `txHashes` as the canonical transaction hash field.
- If legacy files contain `sampleTxHashes`, migrate or regenerate before aggregation.

## 4) Executive Outcome Snapshot

- `ENGINE_ADDRESS`: `0x5FbDB2315678afecb367f032d93F642f64180aa3`
- `TOKEN_ADDRESS`: `0xe7f1725E7734CE288F8367e1Bb143E90bb3F0512`
- Single settlement: `1/1` pass
- Batch 50: `50/50` pass (`100%`)
- Batch 100: `100/100` pass (`100%`)
- Aggregate: `150/150` pass (`100%`)
- Acceptance criteria: fully met

## 5) Distribution Guidance

- Internal distribution:
  - Share `docs/FINAL_TEST_REPORT_CN.md` + this index file
- External/partner distribution:
  - Share `docs/FINAL_TEST_REPORT.md` + relevant `results/*.json` artifacts
- Engineering traceability:
  - Keep `docs/OPENCLOW_V01_DEPLOY_TEST_INSTRUCTIONS.txt` in the release evidence package

## 6) Versioning Note

If any rerun occurs (new addresses, new artifact data, or changed parser fields), update:

1. `docs/FINAL_TEST_REPORT.md`
2. `docs/FINAL_TEST_REPORT_CN.md`
3. `docs/TEST_REPORT_INDEX.md`

and preserve report ID/version consistency across the set.
