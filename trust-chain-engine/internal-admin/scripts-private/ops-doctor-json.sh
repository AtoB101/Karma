#!/usr/bin/env bash
set -euo pipefail
./scripts/doctor.sh --port 8790 --format json --output results/doctor-report.json
