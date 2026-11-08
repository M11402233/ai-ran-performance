#!/usr/bin/env bash
# v4: identical DU in both layouts; only AI placement differs. sudo in a normal SSH terminal.
# New host: sudo LAYOUT_PLAN=configs/cpu-layout-v4-<host>.csv bash scripts/start_baseline_v4.sh
set -euo pipefail
cd "$(dirname "$0")/.."
exec bash scripts/start_remote_study.sh \
  --session-name ai-ran-study-ul-v4 \
  --config configs/du-uplink-only.yml \
  --layout-plan "${LAYOUT_PLAN:-configs/cpu-layout-v4.csv}"
