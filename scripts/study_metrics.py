"""Interval distributions and a baseline gate; no averaging of run averages."""
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path
import re
import statistics
from study_layout import validate_du_roles

METRIC = re.compile(r'Executor metrics "pusch_dec_exec": (.*)')
PRIORITY_FAILURE = re.compile(r'Scheduling priority.*not changed|not enough privileges|failed to.*(?:priority|sched)', re.I)


def dump(path, value):
    Path(path).write_text(json.dumps(value, indent=2, allow_nan=False))


def fingerprint(paths):
    h = hashlib.sha256()
    for path in paths:
        h.update(Path(path).name.encode())
        h.update(Path(path).read_bytes())
    return h.hexdigest()


def audit_threads(folder, meta):
    """Check recorded evidence, rather than only trusting verified booleans."""
    source = folder / 'threads.jsonl'
    start, end = meta.get('sample_start_epoch'), meta.get('sample_end_epoch')
    if not source.exists() or start is None or end is None:
        return False
    expected = set(range(int(start), int(end)))
    seen = set()
    roles = meta.get('cpu_roles')
    du_mask = set(roles['du_cpus']) if roles else set(range(8 if meta['layout'] == 'shared' else 4))
    ai_mask = set(roles['dqn_cpus']) if roles else (set(range(8)) if meta['layout'] == 'shared' else set(range(4, 8)))
    for line in source.read_text().splitlines():
        record = json.loads(line)
        second = int(record['epoch'])
        if second not in expected:
            continue
        if second in seen:
            return False
        du = record.get('du', [])
        if roles:
            try:
                validate_du_roles(du, roles)
            except RuntimeError:
                return False
            if record.get('observer') != {'cpus': roles['observer_cpus'], 'policy': 0}:
                return False
        pool = [r for r in du if r.get('name', '').startswith('main_pool#')]
        if meta.get('main_pool_threads') is not None and (
                len(pool) != meta['main_pool_threads'] or
                any(r['policy'] not in [1, 2] or r['rt_priority'] <= 0 for r in pool)):
            return False
        if meta.get('thread_audit_required') and (
                record.get('scheduled_epoch') != second or
                not record['epoch'] <= record.get('completed_epoch', float('inf')) < second + 1):
            return False
        if not du or any(not r['cpus'] or not set(r['cpus']) <= du_mask for r in du):
            return False
        if not any(r['policy'] in [1, 2] and r['rt_priority'] > 0 and
                   ('main_pool' in r['name'] or 'ru_dummy' in r['name']) for r in du):
            return False
        if meta['threads']:
            ai = record.get('dqn', [])
            if not ai or any(not r['cpus'] or not set(r['cpus']) <= ai_mask or r['policy'] != 0 for r in ai):
                return False
        seen.add(second)
    return bool(expected) and seen == expected



def read_run(folder):
    folder = Path(folder)
    meta = json.loads((folder / 'run.json').read_text())
    reasons = []
    if meta.get('status') != 'ok':
        reasons.append(meta.get('error', meta.get('status', 'incomplete')))
    start, end = meta.get('sample_start_epoch'), meta.get('sample_end_epoch')
    intervals, seconds = [], []
    log = (folder / 'gnb.log').read_text(errors='replace') if (folder / 'gnb.log').exists() else ''
    stdout = (folder / 'stdout.txt').read_text(errors='replace') if (folder / 'stdout.txt').exists() else ''
    if PRIORITY_FAILURE.search(log + '\n' + stdout):
        reasons.append('RT scheduling permission failure')
    if not meta.get('affinity_verified'):
        reasons.append('affinity not verified for all sampled threads')
    if not meta.get('rt_verified'):
        reasons.append('no verified FIFO/RR DU worker')
    if start is not None and end is not None:
        bins = {s: {'epoch_second': s, 'rt_failure_messages': 0, 'skipped_slot_messages': 0} for s in range(int(start), int(end))}
        for line in log.splitlines():
            try:
                stamp = dt.datetime.fromisoformat(line.split()[0]).replace(tzinfo=dt.timezone.utc).timestamp()
            except (ValueError, IndexError):
                continue
            if start <= stamp < end and int(stamp) in bins:
                bins[int(stamp)]['rt_failure_messages'] += int('Real-time failure' in line)
                bins[int(stamp)]['skipped_slot_messages'] += int('Skipped slot' in line)
            match = METRIC.search(line)
            # Reports describe their preceding one-second interval.
            if not match or not start + 1 <= stamp <= end:
                continue
            values = {k: float(v) for k, v in re.findall(r'(\w+)=([0-9.]+)', match[1])}
            needed = ['enqueue_avg', 'enqueue_max', 'nof_executes', 'nof_defers']
            if any(k not in values for k in needed):
                continue
            intervals.append({'epoch_end': stamp, **values})
        seconds = list(bins.values())
        min_intervals = max(1, math.floor(end - start) - 1)
        if len(intervals) < min_intervals:
            reasons.append(f'missing decoder intervals ({len(intervals)} < {min_intervals})')
        if len(intervals) > math.ceil(end - start) + 1:
            reasons.append('duplicate decoder intervals')
        if len(intervals) > 1 and any(b['epoch_end'] - a['epoch_end'] > 1.5 for a, b in zip(intervals, intervals[1:])):
            reasons.append('gap in decoder reporting')
        if not intervals or any(v['nof_executes'] + v['nof_defers'] <= 0 for v in intervals):
            reasons.append('inactive decoder interval')
    else:
        reasons.append('sample window missing')
    dqn = []
    if (folder / 'dqn.csv').exists() and start is not None and end is not None:
        with (folder / 'dqn.csv').open() as f:
            dqn = [dict(r) for r in csv.DictReader(f) if start <= int(r['epoch_second']) < end and r['full_second'] == '1']
    if meta.get('threads', 0) and (len(dqn) != len(seconds) or {int(r['epoch_second']) for r in dqn} != {s['epoch_second'] for s in seconds}):
        reasons.append('missing full-second DQN throughput')
    if meta.get('thread_audit_required') and not audit_threads(folder, meta):
        reasons.append('missing or inconsistent per-second affinity/RT policy evidence')
    result = {'run': folder.name, 'layout': meta['layout'], 'threads': meta['threads'],
              'valid': not reasons, 'invalid_reason': '; '.join(reasons), 'decoder_intervals': len(intervals),
              'rt_failure_messages': sum(v['rt_failure_messages'] for v in seconds),
              'skipped_slot_messages': sum(v['skipped_slot_messages'] for v in seconds)}
    if intervals:
        result.update(median_interval_avg_us=statistics.median(v['enqueue_avg'] for v in intervals),
                      median_interval_max_us=statistics.median(v['enqueue_max'] for v in intervals),
                      max_interval_max_us=max(v['enqueue_max'] for v in intervals))
    if dqn:
        result['dqn_steps_per_second'] = sum(int(r['steps']) for r in dqn) / sum(float(r['seconds']) for r in dqn)
    elif not meta.get('threads', 0):
        result['dqn_steps_per_second'] = 0.
    return result, intervals, seconds, dqn


def baseline_gate(base, expected_context=None):
    base = Path(base)
    protocol = json.loads((base / 'protocol.json').read_text())
    paths = sorted(base.glob('*/run.json'))
    results = [read_run(p.parent)[0] for p in paths]
    reasons = []
    if protocol.get('phase') != 'baseline' or len(results) != 10 or len(protocol.get('schedule', [])) != 10:
        reasons.append('requires exactly ten planned and completed baseline attempts')
    if any(r['threads'] != 0 or r['layout'] != protocol.get('layout') for r in results):
        reasons.append('baseline contains other conditions')
    if any(not r['valid'] for r in results):
        reasons.append('one or more invalid baseline runs')
    if expected_context is not None and protocol['context'] != expected_context:
        reasons.append('baseline context differs: binary/config/duration/collector/environment/threshold')
    limit = protocol['context']['effect_pct'] / 4
    cvs = {}
    for key in ['median_interval_avg_us', 'median_interval_max_us', 'max_interval_max_us']:
        vals = [r[key] for r in results if r.get('valid') and key in r]
        cv = 100 * statistics.stdev(vals) / statistics.mean(vals) if len(vals) == 10 and statistics.mean(vals) > 0 else None
        cvs[key] = cv
        if cv is None or cv > limit:
            reasons.append(f'{key} CV exceeds {limit:g}% or cannot be calculated')
    max_rt = protocol['context']['max_rt_per_second']
    for p in paths:
        if any(s['rt_failure_messages'] > max_rt for s in read_run(p.parent)[2]):
            reasons.append('baseline RT failure messages exceed declared per-second ceiling')
            break
    return {'passed': not reasons, 'reasons': reasons, 'attempts': len(results),
            'invalid_runs': sum(not r['valid'] for r in results), 'cv_pct': cvs,
            'cv_limit_pct': limit, 'minimum_effect_pct': protocol['context']['effect_pct']}
