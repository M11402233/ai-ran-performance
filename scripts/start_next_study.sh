#!/usr/bin/env bash
# Independent UL-only round; run with sudo in a normal SSH terminal.
set -euo pipefail
cd "$(dirname "$0")/.."
exec bash scripts/start_remote_study.sh \
  --session-name ai-ran-study-ul-v2 \
  --config configs/du-uplink-only.yml
