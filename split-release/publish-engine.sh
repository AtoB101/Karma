#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  split-release/publish-engine.sh

This script previously published a local karma-engine/ directory from the public monorepo.

The public Karma repository no longer contains karma-engine/. Maintain the private engine
in its own private Git repository (e.g. Karma2) and use:

  ./split-release/prepare-karma2-sync-package.sh

to sync public contract/API baselines into the private repo.
EOF
}

usage
echo "ERR  karma-engine/ is not present in this public repository; nothing to publish." >&2
exit 1
