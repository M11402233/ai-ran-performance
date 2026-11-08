#!/usr/bin/env python3
"""Unattended host study with a fixed, predeclared retry rule."""
import argparse
import datetime as dt
import fcntl
import json
import os
import signal
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from study_metrics import baseline_gate, dump

RT_ONLY = 'baseline RT failure messages exceed declared per-second ceiling'
PLAN = {'effect_pct': 20, 'cv_limit_pct': 5, 'warmup_seconds': 30, 'sample_seconds': 60,
        'baseline_attempts_per_layout': 10, 'matrix_repeats': 5, 'collector': 'perf',
        'primary_max_rt_per_second': 0, 'fallback_max_rt_per_second': 1,
        'fallback_rule': 'Retry both complete baselines once only if BOTH fail exclusively the RT warning ceiling; never retry invalid/unstable runs into acceptance.',
        'matrix_rule': 'Start only when both baselines pass under the same ceiling. Stop on a failing in-matrix S0 control.',
        'no_further_relaxation': True}


def fallback_allowed(gates):
    return len(gates) == 2 and all(not g['passed'] and g['attempts'] == 10 and g['invalid_runs'] == 0
                                 and g['reasons'] == [RT_ONLY] for g in gates)


def main():
    os.chdir(ROOT)
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--config', default='configs/du-reduced.yml')
    parser.add_argument('--layout-plan', type=Path)
    args = parser.parse_args()
    if not (ROOT / args.config).is_file():
        raise SystemExit('Study configuration does not exist.')
    from study_layout import load_layout_plan
    cpu_plan = load_layout_plan(args.layout_plan)
    session_plan = {**PLAN, 'config': args.config, 'thread_audit_version': 3,
                    'cpu_layout_plan': cpu_plan,
                    'startup_timeout_seconds': 30, 'main_pool_threads': 3,
                    'sampling_clock': 'monotonic deadlines with complete wall-second evidence; no catch-up'}
    if cpu_plan.get('version', 3) >= 4:
        session_plan.update(
            gate_version=4, gated_cv=['median_interval_avg_us', 'median_interval_max_us'],
            reported_only_cv=['max_interval_max_us'], startup_replacement_cap=3,
            v4_rationale=('Declared before any v4 measurement and independent of results: the run maximum of 60 '
                          'per-second maxima is an extreme-of-extremes statistic and is reported, not gated; a '
                          'launch that never reaches active PHY yields no sample, so it is recorded and relaunched '
                          'within a fixed cap. All v3 batches keep their original FAIL verdict.'))
    def interrupted(*_):
        raise KeyboardInterrupt
    signal.signal(signal.SIGTERM, interrupted)
    signal.signal(signal.SIGHUP, interrupted)
    if os.geteuid() != 0 or 'NoNewPrivs:\t1' in Path('/proc/self/status').read_text():
        raise SystemExit('Requires sudo in an ordinary host terminal. No experiments started.')
    lock = (ROOT / 'results/.remote-study.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Another remote study is active.')
    session = ROOT / 'results/processed' / f'remote-session-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}'
    session.mkdir(parents=True)
    dump(session / 'predeclared-plan.json', session_plan)
    (session / 'plan.md').write_text('# Predeclared unattended study plan\n\nRecorded before any new measurement.\n\n' +
                                    '\n'.join(f'- {key}: {value}' for key, value in session_plan.items()) + '\n')
    print(f'Session: {session}', flush=True)
    old_paranoid = Path('/proc/sys/kernel/perf_event_paranoid').read_text().strip()
    state = {'status': 'preflight', 'plan': session_plan, 'stages': []}
    state_path = session / 'status.json'

    def stage(phase, ceiling, layout=None, baselines=None):
        command = [sys.executable, str(ROOT / 'scripts/run_study.py'), phase, '--collector', 'perf',
                   '--config', args.config, '--effect-pct', '20', '--warmup', '30', '--sample', '60', '--max-rt-per-second', str(ceiling)]
        if args.layout_plan:
            command.extend(['--layout-plan', str(args.layout_plan)])
        if layout:
            command.extend(['--layout', layout])
        if baselines:
            command.extend(['--baseline-shared', str(baselines[0]), '--baseline-split', str(baselines[1]), '--repeats', '5'])
        record = {'phase': phase, 'layout': layout, 'rt_ceiling': ceiling, 'command': command}
        state['stages'].append(record); dump(state_path, state)
        name = f'{len(state["stages"]):02d}-{phase}-{layout or "both"}-rt{ceiling}.log'
        result_dir = None
        with (session / name).open('w', buffering=1) as log:
            process = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1, start_new_session=True)
            try:
                for line in process.stdout:
                    log.write(line); print(line, end='', flush=True)
                    if line.startswith('Results: '):
                        result_dir = Path(line.removeprefix('Results: ').strip())
                code = process.wait()
            except BaseException:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                try:
                    process.wait(timeout=45)
                except subprocess.TimeoutExpired:
                    process.kill(); process.wait()
                raise
        record.update(returncode=code, results=str(result_dir) if result_dir else None)
        dump(state_path, state)
        if result_dir is None:
            raise RuntimeError(f'Infrastructure/preflight failed; see {session / name}')
        if phase == 'baseline':
            gate = baseline_gate(result_dir)
            record['gate'] = gate; dump(state_path, state)
            return result_dir, gate
        if code:
            raise RuntimeError(f'Matrix incomplete (exit {code}); no further conditions will be started.')
        return result_dir

    try:
        subprocess.run(['sysctl', '-w', 'kernel.perf_event_paranoid=1'], check=True)
        # Validate actual hardware events before spending time on either baseline.
        from perf_cache import preflight
        preflight()
        import torch
        import matplotlib
        state.update(status='primary-baselines', torch=torch.__version__); dump(state_path, state)
        primary = [stage('baseline', 0, layout) for layout in ['shared', 'split']]
        baselines = [item[0] for item in primary]
        gates = [item[1] for item in primary]
        ceiling = 0
        if not all(g['passed'] for g in gates):
            if not fallback_allowed(gates):
                raise RuntimeError('Primary baselines failed outside the predeclared BOTH-RT-only retry rule. Stop; diagnose without relaxing thresholds.')
            ceiling = 1
            state['status'] = 'predeclared-rt1-baselines'; dump(state_path, state)
            retry = [stage('baseline', 1, layout) for layout in ['shared', 'split']]
            baselines = [item[0] for item in retry]
            if not all(item[1]['passed'] for item in retry):
                raise RuntimeError('Predeclared RT<=1 retry failed. No matrix, no further relaxation.')
        state.update(status='matrix', accepted_ceiling=ceiling); dump(state_path, state)
        stage('matrix', ceiling, baselines=baselines)
        state['status'] = 'complete'
    except BaseException as exc:
        state.update(status='stopped', reason=f'{type(exc).__name__}: {exc}')
        print(f'STOPPED: {state["reason"]}', flush=True)
    finally:
        restore = subprocess.run(['sysctl', '-w', f'kernel.perf_event_paranoid={old_paranoid}'], check=False)
        state['paranoid_restored'] = restore.returncode == 0
        state['original_paranoid'] = old_paranoid
        dump(state_path, state)
        (session / 'status.md').write_text('# Session status\n\n' + '\n'.join(f'- {key}: {value}' for key, value in state.items() if key != 'plan') + '\n')
        subprocess.run([sys.executable, str(ROOT / 'scripts/package_study.py')], check=False)
        lock.close()
    if state['status'] != 'complete':
        raise SystemExit(1)


if __name__ == '__main__':
    main()
