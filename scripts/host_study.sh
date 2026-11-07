#!/usr/bin/env bash
# Run in an ordinary VM terminal. sudo is limited to host preparation and runner.
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $# -lt 1 ]]; then
  echo 'Usage: bash scripts/host_study.sh baseline|matrix [run_study.py options]' >&2
  exit 2
fi
python_bin="${STUDY_PYTHON:-$PWD/.venv-study/bin/python}"
if [[ ! -x "$python_bin" ]]; then
  echo "Missing $python_bin. Create .venv-study and install requirements-study.txt first." >&2
  exit 2
fi
collector=perf
for argument in "$@"; do
  if [[ "$argument" == proc || "$argument" == --collector=proc ]]; then collector=proc; fi
done
restore_paranoid=''
cleanup() {
  if [[ -n "$restore_paranoid" ]]; then
    sudo -n sysctl -w "kernel.perf_event_paranoid=$restore_paranoid" || echo "Restore manually: sudo sysctl -w kernel.perf_event_paranoid=$restore_paranoid" >&2
  fi
}
trap cleanup EXIT
sudo -v
if [[ "$collector" == perf ]]; then
  restore_paranoid=$(cat /proc/sys/kernel/perf_event_paranoid)
  sudo sysctl -w kernel.perf_event_paranoid=1
fi
# Runner stays SCHED_OTHER. gNB sets its own worker RT policies; DQN stays normal.
sudo "$python_bin" scripts/run_study.py "$@"
