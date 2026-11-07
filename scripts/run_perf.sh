#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
label="perf-cache-$(date -u +%Y%m%dT%H%M%SZ)"
python3 scripts/run_matrix.py --collector perf --config configs/du-reduced.yml --label "$label" "$@"
run_dir=$(find results/raw -maxdepth 1 -type d -name "$label-*" | sort | tail -n 1)
python3 analysis/plot_cache.py "$run_dir" --out deliverables
