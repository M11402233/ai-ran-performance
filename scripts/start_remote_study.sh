#!/usr/bin/env bash
# Invoke ONCE in a normal SSH terminal: sudo bash scripts/start_remote_study.sh
set -euo pipefail
cd "$(dirname "$0")/.."
if [[ $(id -u) -ne 0 ]] || [[ $(awk '/^NoNewPrivs:/ {print $2}' /proc/self/status) == 1 ]]; then
  echo 'Use sudo in an ordinary SSH terminal. The restricted agent cannot start this study.' >&2
  exit 1
fi
command -v tmux >/dev/null || { echo 'Install tmux first.' >&2; exit 1; }
command -v perf >/dev/null || { echo 'Install perf/linux-tools matching the guest kernel first.' >&2; exit 1; }
mkdir -p results/processed
# Even dependency setup stays inside the detached session. It does not change
# the predeclared acceptance rule or silently install OS packages.
python3 - "$@" <<'PY'
import argparse
import fcntl
from pathlib import Path
import shlex
import subprocess
parser = argparse.ArgumentParser()
parser.add_argument('--config', default='configs/du-reduced.yml')
parser.add_argument('--layout-plan')
parser.add_argument('--session-name', default='ai-ran-study')
args = parser.parse_args()
if not args.session_name or any(c not in 'abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_' for c in args.session_name):
    raise SystemExit('Session name must contain only letters, digits, hyphens or underscores.')
if subprocess.run(['tmux', 'has-session', '-t', args.session_name], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0:
    raise SystemExit(f'Session {args.session_name} already exists; attach to inspect it.')
root = Path.cwd()
if not (root / args.config).is_file():
    raise SystemExit('Study configuration does not exist.')
if args.layout_plan:
    import sys
    sys.path.insert(0, str(root / 'scripts'))
    from study_layout import load_layout_plan
    load_layout_plan(root / args.layout_plan)
with (root / 'results/.remote-study.lock').open('a') as lock:
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('A remote study is still running; do not start another configuration concurrently.')
body = 'set -euo pipefail\ncd ' + shlex.quote(str(root)) + '\n'
body += 'python3 -m venv .venv-study\n'
body += '.venv-study/bin/python -m pip install -r requirements-study.txt\n'
runner = ['.venv-study/bin/python', '-u', 'scripts/remote_study.py', '--config', args.config]
if args.layout_plan:
    runner.extend(['--layout-plan', args.layout_plan])
body += shlex.join(runner) + '\n'
# Shell persists after completion so status/output remain inspectable.
command = 'bash -lc ' + shlex.quote(body + '\n')
command = '( ' + command + ' ); code=$?; echo "Study exit status: $code"; exec bash'
log = root / 'results/processed/remote-console.log'
# Fixed path quoted as shell data, not interpolated as executable text.
subprocess.run(['tmux', 'new-session', '-d', '-s', args.session_name, 'bash', '-c', command], check=True)
subprocess.run(['tmux', 'pipe-pane', '-o', '-t', args.session_name, 'cat >> ' + shlex.quote(str(log))], check=True)
print('Started root tmux session: ' + args.session_name)
print(f'Observe: sudo tmux attach -t {args.session_name} (detach: Ctrl-b then d)')
print('Log: ' + str(log))
print('No measurements are claimed until host preflight and baseline gates complete.')
PY
