#!/usr/bin/env python3
"""Host-terminal study: ten-attempt baseline gates before DQN conditions."""
import argparse
import datetime as dt
import fcntl
import importlib.util
import json
import math
import os
from pathlib import Path
import platform
import random
import re
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from perf_cache import preflight, start_perf, finish_perf
from study_metrics import baseline_gate, dump, fingerprint, PRIORITY_FAILURE, read_run


def stop(process):
    if process is None or process.poll() is not None:
        return
    process.send_signal(signal.SIGINT)
    try:
        process.wait(timeout=10)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def thread_snapshot(pid, allowed, require_rt=False, require_other=False):
    rows = []
    for task in sorted((Path('/proc') / str(pid) / 'task').iterdir()):
        try:
            tid = int(task.name)
            mask = sorted(os.sched_getaffinity(tid))
            policy = os.sched_getscheduler(tid)
            priority = os.sched_getparam(tid).sched_priority
            name = (task / 'comm').read_text().strip()
        except ProcessLookupError:
            continue
        if not set(mask) <= set(allowed):
            raise RuntimeError(f'{pid}/{tid} affinity {mask} escapes {allowed}')
        if require_other and policy != os.SCHED_OTHER:
            raise RuntimeError('DQN unexpectedly has non-normal scheduling policy')
        rows.append({'tid': tid, 'name': name, 'cpus': mask, 'policy': policy, 'rt_priority': priority})
    if not rows:
        raise RuntimeError('No threads observed')
    if require_rt and not any(r['policy'] in (os.SCHED_FIFO, os.SCHED_RR) and r['rt_priority'] > 0 and
                              ('main_pool' in r['name'] or 'ru_dummy' in r['name']) for r in rows):
        raise RuntimeError('No FIFO/RR main_pool or ru_dummy worker; RT permission not effective')
    if require_rt:
        pool_workers = [r for r in rows if r['name'].startswith('main_pool#')]
        if len(pool_workers) != 3:
            raise RuntimeError(f'Expected 3 actual main_pool workers, observed {len(pool_workers)}; CPU-mask worker cap may override nof_threads')
    return rows


def check_host(collector):
    status = Path('/proc/self/status').read_text()
    if re.search(r'^NoNewPrivs:\s+1$', status, re.M):
        raise SystemExit('NoNewPrivs=1: run this command in an ordinary host terminal with sudo or a CAP_SYS_NICE gNB. No runs started.')
    if not set(range(8)) <= os.sched_getaffinity(0):
        raise SystemExit('This protocol requires available vCPUs 0–7.')
    if collector == 'perf':
        if Path('/proc/sys/kernel/perf_event_paranoid').read_text().strip() != '1':
            raise SystemExit('Protocol requires temporary perf_event_paranoid=1. Use scripts/host_study.sh.')
        preflight()
    else:
        print('SCHEDULING-ONLY: no cache/IPC hardware conclusions are permitted.', flush=True)


def context(a):
    cpu = next((line for line in Path('/proc/cpuinfo').read_text().splitlines() if line.startswith('model name')), '')
    return {'fingerprint': fingerprint([ROOT / 'bin/gnb', ROOT / a.config, ROOT / 'configs/pucch-small.yml',
                                       Path(__file__), ROOT / 'scripts/study_metrics.py', ROOT / 'scripts/perf_cache.py',
                                       ROOT / 'workloads/dqn_train.py']),
            'config': a.config, 'warmup': a.warmup, 'sample': a.sample, 'collector': a.collector,
            'effect_pct': a.effect_pct, 'max_rt_per_second': a.max_rt_per_second,
            'kernel': platform.release(), 'hostname': platform.node(), 'cpu': cpu,
            'boot_id': Path('/proc/sys/kernel/random/boot_id').read_text().strip(),
            'available_cpus': sorted(os.sched_getaffinity(0)), 'uid': os.geteuid(),
            'main_pool_threads': 3, 'seed': a.seed,
            'paranoid': Path('/proc/sys/kernel/perf_event_paranoid').read_text().strip()}


def run_one(base, index, layout, threads, repeat, a):
    folder = base / f'{index:02d}-{layout}-DQN{threads}-{repeat}'
    folder.mkdir()
    du_mask = list(range(8 if layout == 'shared' else 4))
    ai_mask = list(range(8)) if layout == 'shared' else list(range(4, 8))
    mask_text = ','.join(map(str, du_mask))
    cfg = (ROOT / a.config).read_text().replace('results/raw/gnb.log', str(folder / 'gnb.log'))
    if 'expert_execution:' in cfg:
        raise RuntimeError('Study config must not already contain expert_execution; use supplied du-reduced.yml')
    cfg += f'\nexpert_execution:\n  affinities:\n    main_pool_cpus: "{mask_text}"\n    main_pool_pinning: mask\n  cell_affinities:\n    - ru_cpus: "{mask_text}"\n      ru_pinning: mask\n  threads:\n    main_pool:\n      nof_threads: 3\n'
    (folder / 'config.yml').write_text(cfg)
    meta = {'layout': layout, 'threads': threads, 'repeat': repeat, 'status': 'starting',
            'warmup': a.warmup, 'sample': a.sample, 'du_cpus': du_mask, 'dqn_cpus': ai_mask,
            'collector': a.collector, 'affinity_verified': False, 'rt_verified': False}
    du = ai = perf = None
    handles = []
    interrupted = False
    print(f'Attempt {index + 1}: {folder.name}', flush=True)
    try:
        out = (folder / 'stdout.txt').open('w'); handles.append(out)
        du = subprocess.Popen(['taskset', '-c', mask_text, str(ROOT / 'bin/gnb'), '-c', str(folder / 'config.yml'),
                               '-c', str(ROOT / 'configs/pucch-small.yml')], stdout=out, stderr=subprocess.STDOUT, stdin=subprocess.PIPE)
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline:
            if du.poll() is not None:
                raise RuntimeError('DU exited before active PHY')
            log = (folder / 'gnb.log').read_text(errors='replace') if (folder / 'gnb.log').exists() else ''
            if PRIORITY_FAILURE.search(log + (folder / 'stdout.txt').read_text(errors='replace')):
                raise RuntimeError('gNB RT priority permission failed')
            if re.search(r'"pusch_dec_exec": nof_executes=\d+ nof_defers=[1-9]\d*', log):
                break
            time.sleep(.25)
        else:
            raise RuntimeError('No active decoder within 30 seconds')
        thread_snapshot(du.pid, du_mask, require_rt=True)
        if threads:
            aiout = (folder / 'dqn.stdout').open('w'); handles.append(aiout)
            ai = subprocess.Popen(['taskset', '-c', ','.join(map(str, ai_mask)), sys.executable,
                                   str(ROOT / 'workloads/dqn_train.py'), '--threads', str(threads),
                                   '--seed', str(a.seed + repeat), '--output', str(folder / 'dqn.csv'),
                                   '--ready', str(folder / 'dqn-ready.json')], stdout=aiout, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + 120
            while not (folder / 'dqn-ready.json').exists():
                if ai.poll() is not None or du.poll() is not None:
                    raise RuntimeError('DQN/DU exited during DQN initialization')
                if time.monotonic() > deadline:
                    raise RuntimeError('DQN initialization timeout')
                time.sleep(.2)
        # Both DU and training warm up under the actual condition.
        deadline = time.monotonic() + a.warmup
        while time.monotonic() < deadline:
            if du.poll() is not None or (ai is not None and ai.poll() is not None):
                raise RuntimeError('DU/DQN exited during warmup')
            time.sleep(min(.25, max(0, deadline - time.monotonic())))
        start = math.ceil(time.time())
        time.sleep(max(0, start - time.time()))
        meta['sample_start_epoch'] = start
        end = start + a.sample
        # Exact log window is independent of the small perf startup overhead.
        if a.collector == 'perf':
            perf = start_perf(du.pid, a.sample, folder / 'perf.csv')
        for second in range(a.sample):
            if du.poll() is not None or (ai is not None and ai.poll() is not None):
                raise RuntimeError('DU/DQN exited during sample')
            if perf is not None and perf.poll() not in (None, 0):
                raise RuntimeError('perf attach/counter failure')
            snapshot = {'epoch': time.time(), 'du': thread_snapshot(du.pid, du_mask, require_rt=True),
                        'cpu': Path('/proc/stat').read_text().splitlines()[0]}
            if ai is not None:
                snapshot['dqn'] = thread_snapshot(ai.pid, ai_mask, require_other=True)
            with (folder / 'threads.jsonl').open('a') as f:
                f.write(json.dumps(snapshot) + '\n')
            time.sleep(max(0, start + second + 1 - time.time()))
        meta['sample_end_epoch'] = end
        if abs(time.time() - end) > 1.0:
            raise RuntimeError('Sampling deadline overrun >1 second')
        meta['affinity_verified'] = meta['rt_verified'] = True
        if perf is not None:
            meta['perf'] = finish_perf(perf, folder / 'perf.csv')
        # Allow the DQN writer to flush the final complete second.
        if ai is not None:
            deadline = time.monotonic() + 5
            while time.monotonic() < deadline:
                if ai.poll() is not None:
                    raise RuntimeError('DQN exited before metrics flush')
                if (folder / 'dqn.csv').exists() and str(end - 1) in (folder / 'dqn.csv').read_text().splitlines()[-1].split(',')[:1]:
                    break
                time.sleep(.1)
            else:
                raise RuntimeError('DQN final-second metrics missing')
        meta['status'] = 'ok'
    except KeyboardInterrupt:
        interrupted = True
        meta.update(status='aborted', error='interrupted; unattempted conditions remain in protocol')
    except Exception as exc:
        meta.update(status='failed', error=str(exc))
        print(f'  FAILED: {exc}', flush=True)
    finally:
        if 'sample_start_epoch' in meta and 'sample_end_epoch' not in meta:
            meta['sample_end_epoch'] = min(meta['sample_start_epoch'] + a.sample, math.floor(time.time()))
        for process in (perf, ai, du):
            stop(process)
        meta['returncodes'] = {name: process.returncode for name, process in [('du', du), ('dqn', ai), ('perf', perf)] if process is not None}
        for handle in handles:
            handle.close()
        dump(folder / 'run.json', meta)
    if interrupted:
        raise KeyboardInterrupt


def main():
    os.chdir(ROOT)
    os.environ['TZ'] = 'UTC'
    time.tzset()
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('phase', choices=['baseline', 'matrix'])
    p.add_argument('--layout', choices=['shared', 'split'], default='shared', help='baseline layout')
    p.add_argument('--collector', choices=['perf', 'proc'], default='perf')
    p.add_argument('--config', default='configs/du-reduced.yml')
    p.add_argument('--warmup', type=int, default=30)
    p.add_argument('--sample', type=int, default=60)
    p.add_argument('--repeats', type=int, default=5, help='matrix repetitions; baseline is always ten')
    p.add_argument('--effect-pct', type=float, default=20, help='minimum effect of interest; gate CV <= effect/4')
    p.add_argument('--max-rt-per-second', type=int, default=0, help='baseline RT warning ceiling')
    p.add_argument('--seed', type=int, default=20261030)
    p.add_argument('--baseline-shared', type=Path)
    p.add_argument('--baseline-split', type=Path)
    a = p.parse_args()
    if a.warmup < 0 or a.sample < 10 or a.repeats < 1 or not 0 < a.effect_pct <= 100 or a.max_rt_per_second < 0:
        p.error('require warmup>=0, sample>=10, repeats>=1, 0<effect<=100, RT ceiling>=0')
    check_host(a.collector)
    ctx = context(a)
    if a.phase == 'matrix':
        if importlib.util.find_spec('torch') is None:
            raise SystemExit('PyTorch missing; install requirements-study.txt in the host venv first.')
        for layout, base in [('shared', a.baseline_shared), ('split', a.baseline_split)]:
            if base is None:
                p.error('matrix requires --baseline-shared and --baseline-split (ten S0 attempts each)')
            gate = baseline_gate(base, ctx)
            protocol = json.loads((base / 'protocol.json').read_text())
            if not gate['passed'] or protocol['layout'] != layout:
                raise SystemExit(f'{layout} baseline gate blocked: {gate}')
        schedule = [(layout, threads, repeat) for repeat in range(a.repeats)
                    for layout in ['shared', 'split'] for threads in [0, 1, 2, 4]]
        random.Random(a.seed).shuffle(schedule)
    else:
        schedule = [(a.layout, 0, repeat) for repeat in range(10)]
    base = ROOT / 'results/raw' / f'{a.phase}-{a.layout}-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%S%fZ}'
    base.mkdir(parents=True)
    dump(base / 'protocol.json', {'phase': a.phase, 'layout': a.layout, 'context': ctx, 'schedule': schedule,
                                 'baselines': {'shared': str(a.baseline_shared), 'split': str(a.baseline_split)}})
    print(f'Results: {base}', flush=True)
    lock = (ROOT / 'results' / '.study.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Another study is running; no runs started.')
    control_failed = False
    was_interrupted = False
    try:
        for index, (layout, threads, repeat) in enumerate(schedule):
            run_one(base, index, layout, threads, repeat, a)
            if a.phase == 'matrix' and threads == 0:
                folder = base / f'{index:02d}-{layout}-DQN{threads}-{repeat}'
                control, _, seconds, _ = read_run(folder)
                if not control['valid'] or any(s['rt_failure_messages'] > a.max_rt_per_second for s in seconds):
                    control_failed = True
                    print('S0 control failed during matrix; stopping further conditions.', flush=True)
                    break
    except KeyboardInterrupt:
        was_interrupted = True
        print('Interrupted; preserving failed and unattempted conditions.', flush=True)
    finally:
        if a.phase == 'baseline':
            gate = baseline_gate(base)
            dump(base / 'baseline-gate.json', gate)
            print(json.dumps(gate, indent=2), flush=True)
        subprocess.run([sys.executable, str(ROOT / 'analysis/analyze_study.py'), str(base)], check=True)
        lock.close()
    if was_interrupted:
        raise SystemExit(130)
    if control_failed:
        raise SystemExit('Matrix halted: S0 control failed; inspect quality report.')
    if a.phase == 'baseline' and not gate['passed']:
        raise SystemExit('Baseline FAILED. Do not add DQN conditions. Diagnose and retain all ten attempts.')

if __name__ == '__main__':
    main()
