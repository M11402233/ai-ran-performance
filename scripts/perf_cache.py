"""perf stat CSV collection. Unsupported/unscheduled events are never zeros."""
import csv
import os
import math
from pathlib import Path
import shutil
import subprocess
import tempfile

EVENTS = ('cache-references', 'cache-misses', 'instructions', 'cycles')

def read_counts(path):
    counts = {}
    for row in csv.reader(Path(path).read_text().splitlines(), delimiter=';'):
        if len(row) < 3 or row[2].strip() not in EVENTS:
            continue
        event = row[2].strip()
        try:
            value = float(row[0].strip())
            coverage = float(row[4].strip().rstrip('%')) if len(row) > 4 and row[4].strip() else 100.0
        except ValueError as exc:
            raise RuntimeError(f'{event}: counter unavailable: {row[0]}') from exc
        if not math.isfinite(value) or not math.isfinite(coverage) or value < 0 or not 90 <= coverage <= 100.01:
            raise RuntimeError(f'{event}: invalid value or running coverage below 90%')
        counts[event] = value
    missing = set(EVENTS) - counts.keys()
    if missing:
        raise RuntimeError(f'Missing perf events: {sorted(missing)}')
    if counts['cache-references'] <= 0 or counts['instructions'] <= 0 or counts['cycles'] <= 0:
        raise RuntimeError('No usable cache references, instructions or cycles')
    return counts

def preflight():
    if not shutil.which('perf'):
        raise SystemExit('perf is not installed. Install matching linux-tools on the measurement host; no measurements were started.')
    with tempfile.TemporaryDirectory() as tmp:
        output = Path(tmp) / 'probe.csv'
        result = subprocess.run(['perf', 'stat', '-x', ';', '-o', str(output), '-e', ','.join(EVENTS), '--', 'python3', '-c', 'sum(range(1000000))'], capture_output=True, text=True, env={**os.environ, 'LC_ALL':'C'})
        if result.returncode:
            raise SystemExit(f'perf preflight failed: {result.stderr}\n{output.read_text() if output.exists() else ""}')
        read_counts(output)

def start_perf(pid, seconds, output):
    # -p attaches to all current threads; perf inherits future threads by default.
    return subprocess.Popen(['perf', 'stat', '-x', ';', '-o', str(output), '-e', ','.join(EVENTS), '-p', str(pid), '--', 'sleep', str(seconds)], env={**os.environ, 'LC_ALL':'C'})

def finish_perf(process, output):
    if process.wait(timeout=10):
        raise RuntimeError(f'perf failed; inspect {output}')
    counts = read_counts(output)
    return {**counts, 'cache_miss_rate_pct':100*counts['cache-misses']/counts['cache-references'], 'cache_mpki':1000*counts['cache-misses']/counts['instructions'], 'ipc':counts['instructions']/counts['cycles']}
