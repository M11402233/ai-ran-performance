#!/usr/bin/env python3
"""Export interval distributions, failures, invalid fractions and AI trade-offs."""
import argparse
import csv
import json
import os
from pathlib import Path
import statistics
import sys
os.environ.setdefault('MPLCONFIGDIR', '/tmp/ai-ran-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from study_metrics import read_run, baseline_gate, dump


def write_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader(); writer.writerows(rows)


def analyze(base, out):
    protocol = json.loads((base / 'protocol.json').read_text())
    out.mkdir(parents=True, exist_ok=True)
    runs, intervals, seconds = [], [], []
    for index, (layout, threads, repeat) in enumerate(protocol['schedule']):
        folder = base / f'{index:02d}-{layout}-DQN{threads}-{repeat}'
        if not (folder / 'run.json').exists():
            runs.append({'run': folder.name, 'layout': layout, 'threads': threads, 'attempted': False,
                         'valid': False, 'invalid_reason': 'not attempted or metadata not saved'})
            continue
        row, ivals, secs, dqn = read_run(folder)
        row['attempted'] = True
        runs.append(row)
        common = {k: row[k] for k in ['run', 'layout', 'threads', 'valid']}
        intervals.extend({**common, **v} for v in ivals)
        rates = {int(r['epoch_second']): float(r['steps_per_second']) for r in dqn}
        seconds.extend({**common, **v, 'dqn_steps_per_second': rates.get(v['epoch_second'], 0 if not threads else '')} for v in secs)
    write_csv(out / 'runs.csv', runs)
    write_csv(out / 'decoder-intervals.csv', intervals)
    write_csv(out / 'per-second.csv', seconds)
    groups = sorted({(r['layout'], r['threads']) for r in runs})
    quality = []
    for layout, threads in groups:
        group = [r for r in runs if (r['layout'], r['threads']) == (layout, threads)]
        attempted = [r for r in group if r['attempted']]
        invalid = sum(not r['valid'] for r in attempted)
        quality.append({'layout': layout, 'threads': threads, 'planned': len(group), 'attempted': len(attempted),
                        'not_attempted': len(group) - len(attempted), 'invalid': invalid,
                        'invalid_fraction_of_attempts': invalid / len(attempted) if attempted else '',
                        'incomplete_fraction_of_planned': sum(not r['valid'] for r in group) / len(group)})
    write_csv(out / 'quality.csv', quality)
    labels = [f'{layout}\nDQN {threads}' for layout, threads in groups]
    fig, ax = plt.subplots(figsize=(10, 4))
    ax.bar(range(len(groups)), [q['incomplete_fraction_of_planned'] for q in quality], color='#cc6655')
    ax.set_xticks(range(len(groups)), labels)
    ax.set_ylim(0, 1.12); ax.set_ylabel('Invalid or unattempted / planned')
    ax.set_title('Study completeness (see quality.csv for attempted-run invalid fractions)')
    for i, q in enumerate(quality):
        ax.text(i, .02, f'{q["invalid"]} invalid / {q["attempted"]} attempts\n{q["not_attempted"]} unattempted', ha='center', fontsize=8)
    fig.tight_layout(); fig.savefig(out / '01-quality.png', dpi=170); plt.close(fig)
    valid = [r for r in runs if r['valid']]
    if valid:
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        for i, group in enumerate(groups):
            vals = [v for v in intervals if v['valid'] and (v['layout'], v['threads']) == group]
            if not vals:
                continue
            for ax, field in zip(axes, ['enqueue_avg', 'enqueue_max']):
                values = sorted(v[field] for v in vals)
                ax.step(values, [(j + 1) / len(values) for j in range(len(values))], where='post', label=labels[i].replace('\n', ' '))
        for ax, title in zip(axes, ['One-second reported average enqueue delay (us)', 'One-second reported maximum enqueue delay (us)']):
            ax.set_xlabel(title); ax.set_ylabel('Fraction of retained one-second reports'); ax.grid(alpha=.2); ax.legend(fontsize=7)
        fig.suptitle('Valid runs only; pooled intervals are correlated within runs')
        fig.tight_layout(); fig.savefig(out / '02-delay-distributions.png', dpi=170); plt.close(fig)
        fig, axes = plt.subplots(1, 2, figsize=(12, 4))
        for layout in ['shared', 'split']:
            for threads in [0, 1, 2, 4]:
                group = [r for r in valid if (r['layout'], r['threads']) == (layout, threads)]
                if not group:
                    continue
                for ax, key in zip(axes, ['median_interval_avg_us', 'max_interval_max_us']):
                    ax.scatter([r['dqn_steps_per_second'] for r in group], [r[key] for r in group],
                               marker='o' if layout == 'shared' else '^', label=f'{layout} DQN {threads}')
        for ax, label in zip(axes, ['Median of one-second average delays (us)', 'Maximum of one-second maximum delays (us)']):
            ax.set_xlabel('DQN optimizer updates / second'); ax.set_ylabel(label); ax.grid(alpha=.2); ax.legend(fontsize=7)
        fig.suptitle('DU latency vs AI training throughput: one point per valid run')
        fig.tight_layout(); fig.savefig(out / '03-du-ai-tradeoff.png', dpi=170); plt.close(fig)
    # RT series includes invalid sampled runs and is never silently filtered.
    if seconds:
        fig, ax = plt.subplots(figsize=(11, 4))
        for row in runs:
            series = [r for r in seconds if r['run'] == row['run']]
            if not series:
                continue
            ax.plot(range(len(series)), [v['rt_failure_messages'] for v in series], alpha=.45,
                    linestyle='-' if row['valid'] else '--')
        ax.set_xlabel('Second within sample'); ax.set_ylabel('Real-time failure log messages / second')
        ax.set_title('Every sampled run, including invalid runs (dashed)')
        fig.tight_layout(); fig.savefig(out / '04-rt-failures.png', dpi=170); plt.close(fig)
    # Distribution summaries operate directly on interval reports, not run means.
    distribution = []
    for layout, threads in groups:
        vals = [v for v in intervals if v['valid'] and (v['layout'], v['threads']) == (layout, threads)]
        if vals:
            distribution.append({'layout': layout, 'threads': threads, 'intervals': len(vals),
                                 'median_interval_avg_us': statistics.median(v['enqueue_avg'] for v in vals),
                                 'median_interval_max_us': statistics.median(v['enqueue_max'] for v in vals),
                                 'max_interval_max_us': max(v['enqueue_max'] for v in vals)})
    write_csv(out / 'distribution-summary.csv', distribution)
    gate = baseline_gate(base) if protocol['phase'] == 'baseline' else None
    if gate is not None:
        dump(out / 'baseline-gate.json', gate)
        if valid:
            fig, axes = plt.subplots(1, 2, figsize=(11, 4))
            for ax, field in zip(axes, ['median_interval_avg_us', 'max_interval_max_us']):
                ax.scatter(range(1, len(valid) + 1), [r[field] for r in valid])
                ax.set_xlabel('Valid attempt order (see runs.csv)'); ax.set_ylabel(field); ax.grid(alpha=.2)
            fig.suptitle(f'Ten-attempt baseline gate: {"PASS" if gate["passed"] else "FAIL"}')
            fig.tight_layout(); fig.savefig(out / '05-baseline-stability.png', dpi=170); plt.close(fig)
    scope = 'Hardware perf counters requested; check per-run perf validity.' if protocol['context']['collector'] == 'perf' else 'Scheduling-level measurements only. No cache/IPC or hardware bottleneck claims.'
    report = [f'# {base.name}', '', scope, '', f'Planned {len(runs)}; attempted {sum(r["attempted"] for r in runs)}; valid {len(valid)}.',
              '', 'RT counts are observed FAPI warning messages, not unique missed slots. Message suppression may undercount physical failures.',
              'Latency values are distributions of one-second avg/max reports, not individual-task medians or P99.',
              'Invalid sampled runs remain in runs.csv/per-second.csv; valid-only distributions must be read with quality.csv.',
              'DQN steps are minibatch optimizer updates; the synthetic environment is a controlled workload, not a trained RAN application.',
              'CPU separation is verified guest vCPU affinity; host cores/cache isolation is not established.']
    if gate is not None:
        report.extend(['', f'Baseline gate: {"PASS" if gate["passed"] else "FAIL"}', f'CV limit: {gate["cv_limit_pct"]}%; minimum effect: {gate["minimum_effect_pct"]}%.',
                       json.dumps(gate['cv_pct']), *gate['reasons'], 'CV gate is an engineering acceptance criterion, not a statistical power calculation.'])
    report.extend(['', '## Reproduction context', '', *[f'- {key}: {value}' for key, value in protocol['context'].items()],
                   '', f'Baseline sources: {protocol.get("baselines", {})}'])
    (out / 'report.md').write_text('\n'.join(report) + '\n')
    print(out)


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('base', type=Path)
    p.add_argument('--out', type=Path)
    a = p.parse_args()
    analyze(a.base, a.out or ROOT / 'results/processed' / a.base.name)
