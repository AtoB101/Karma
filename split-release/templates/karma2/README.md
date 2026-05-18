# Karma2 Private Repo Alignment Kit

Copy this directory into the private repository (`Karma2`) as:

- `ops/release/CORE_VERSION.lock.example`
- `ops/release/deployment-manifest.json.example`
- `ops/release/ENV_SYNC.example`
- `ops/release/verify-manifest.sh`
- `.github/workflows/lockstep-sync-check.yml`

Then:

1. Copy `CORE_VERSION.lock.example` to `CORE_VERSION.lock` and fill real values.
2. Copy `deployment-manifest.json.example` to `deployment-manifest.json` and fill release data.
3. Copy `ENV_SYNC.example` to `ENV_SYNC` and fill environment mapping (RPC/API/base URLs).
4. Run `./verify-manifest.sh` in the private repository root before deployment.
5. Keep `CORE_VERSION.lock`, `deployment-manifest.json`, and `ENV_SYNC` in the same PR.
6. Enable the `Lockstep Sync Check` workflow as required status check in branch protection.

This keeps private engine releases pinned to one audited public core release.

## Phase 1–3 private gap checklist

After running `prepare-karma2-sync-package.sh`, copy:

- `docs/PHASE1-3_PRIVATE_GAP_CHECKLIST-zh.md` → Karma2 `ops/release/` (or your ops docs tree)

Template source: `split-release/templates/karma2/PHASE1-3_PRIVATE_GAP_CHECKLIST-zh.md.tpl` (commit and `GENERATED_AT_UTC` are filled at package generation time).
