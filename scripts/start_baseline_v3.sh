#!/usr/bin/env bash
# Independent RU/observer isolation experiment. sudo in a normal SSH terminal.
set -euo pipefail
cd "$(dirname "$0")/.."
exec bash scripts/start_remote_study.sh \
  --session-name ai-ran-study-ul-v3 \
  --config configs/du-uplink-only.yml \
  --layout-plan configs/cpu-layout-v3.csv
