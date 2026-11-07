#!/usr/bin/env python3
"""Evidence-backed four-item acceptance report for a single remote session.
This is postprocessing only: it never changes collection or baseline thresholds.
"""
import argparse
import csv
import json
import math
import os
from pathlib import Path
import statistics
import sys
import textwrap
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from study_metrics import baseline_gate, read_run


def save_csv(path, rows):
    if not rows:
        return
    keys = list(dict.fromkeys(k for r in rows for k in r))
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=keys)
        writer.writeheader(); writer.writerows(rows)


def audit_threads(folder, meta):
    """Check recorded evidence, rather than only trusting verified booleans."""
    source = folder / 'threads.jsonl'
    start, end = meta.get('sample_start_epoch'), meta.get('sample_end_epoch')
    if not source.exists() or start is None or end is None:
        return False
    expected = set(range(int(start), int(end)))
    seen = set()
    du_mask = set(range(8 if meta['layout'] == 'shared' else 4))
    ai_mask = set(range(8)) if meta['layout'] == 'shared' else set(range(4, 8))
    for line in source.read_text().splitlines():
        record = json.loads(line)
        second = int(record['epoch'])
        if second not in expected:
            continue
        du = record.get('du', [])
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


def collect(session):
    state = json.loads((session / 'status.json').read_text())
    stages, rows, errors = [], [], []
    for index, item in enumerate(state.get('stages', [])):
        raw = item.get('results')
        if not raw:
            log = session / f'{index + 1:02d}-{item["phase"]}-{item.get("layout") or "both"}-rt{item["rt_ceiling"]}.log'
            if log.exists():
                raw = next((s.removeprefix('Results: ').strip() for s in log.read_text().splitlines() if s.startswith('Results: ')), None)
        if not raw:
            errors.append(f'Stage {index + 1}: no measurement directory recorded')
            continue
        base = Path(raw)
        if not base.is_absolute():
            base = ROOT / base
        if not (base / 'protocol.json').exists():
            errors.append(f'Stage {index + 1}: protocol missing: {base}')
            continue
        protocol = json.loads((base / 'protocol.json').read_text())
        batch = {'number': index + 1, 'base': base, 'phase': protocol['phase'], 'layout': protocol['layout'],
                 'context': protocol['context'], 'planned': len(protocol['schedule']), 'rows': []}
        for i, (layout, threads, repeat) in enumerate(protocol['schedule']):
            folder = base / f'{i:02d}-{layout}-DQN{threads}-{repeat}'
            row = {'stage': index + 1, 'phase': protocol['phase'], 'layout': layout, 'threads': threads,
                   'repeat': repeat, 'run': folder.name, 'attempted': False, 'valid': False,
                   'raw': str(folder), 'rt_ceiling': protocol['context']['max_rt_per_second']}
            if (folder / 'run.json').exists():
                try:
                    values, intervals, seconds, _ = read_run(folder)
                    meta = json.loads((folder / 'run.json').read_text())
                    row.update(values, attempted=True, intervals=intervals, seconds=seconds)
                    row['thread_evidence_verified'] = audit_threads(folder, meta)
                    row['valid'] = values['valid'] and row['thread_evidence_verified']
                    row['duration_seconds'] = meta.get('sample_end_epoch', 0) - meta.get('sample_start_epoch', 0)
                    row['rt_max_per_second'] = max((s['rt_failure_messages'] for s in seconds), default=0)
                    row['perf'] = meta.get('perf', {})
                    row['perf_valid'] = row['valid'] and protocol['context']['collector'] == 'perf' and all(
                        math.isfinite(row['perf'].get(k, math.nan)) for k in ['cache_miss_rate_pct', 'cache_mpki', 'ipc'])
                    if values['valid'] and not row['thread_evidence_verified']:
                        row['invalid_reason'] = 'missing or inconsistent per-second affinity/RT policy evidence'
                except (ValueError, KeyError, OSError, RuntimeError) as exc:
                    row.update(attempted=True, valid=False, invalid_reason=f'Unreadable measurement evidence: {exc}')
            batch['rows'].append(row); rows.append(row)
        if batch['phase'] == 'baseline':
            try:
                batch['gate'] = baseline_gate(base)
                batch['accepted'] = batch['gate']['passed'] and len(batch['rows']) == 10 and all(r['valid'] for r in batch['rows'])
            except (ValueError, KeyError, OSError, RuntimeError) as exc:
                batch.update(gate={'passed': False, 'cv_pct': {}, 'reasons': [str(exc)]}, accepted=False)
        stages.append(batch)
    return state, stages, rows, errors


def compare(stages):
    """Compare repeat-matched runs only within the same matrix and context."""
    result = []
    for batch in stages:
        if batch['phase'] != 'matrix':
            continue
        lookup = {(r['layout'], r['threads'], r['repeat']): r for r in batch['rows'] if r['valid']}
        for threads in [0, 1, 2, 4]:
            pairs = []
            for repeat in sorted({r['repeat'] for r in batch['rows']}):
                shared = lookup.get(('shared', threads, repeat))
                split = lookup.get(('split', threads, repeat))
                if shared is None or split is None:
                    continue
                delta = 100 * (split['median_interval_avg_us'] / shared['median_interval_avg_us'] - 1) if shared['median_interval_avg_us'] else None
                pairs.append((shared, split, delta))
            values = [p[2] for p in pairs if p[2] is not None]
            result.append({'stage': batch['number'], 'threads': threads, 'valid_pairs': len(pairs),
                           'median_paired_delay_change_pct': statistics.median(values) if values else '',
                           'shared_median_updates_per_second': statistics.median(p[0]['dqn_steps_per_second'] for p in pairs) if pairs else '',
                           'split_median_updates_per_second': statistics.median(p[1]['dqn_steps_per_second'] for p in pairs) if pairs else '',
                           'minimum_three_pairs': len(pairs) >= 3})
    return result


def acceptance(state, stages, rows, comparisons, figure_ready=False):
    baselines = [b for b in stages if b['phase'] == 'baseline' and b.get('accepted')]
    matrix_ok = False
    for batch in stages:
        if batch['phase'] != 'matrix' or len(batch['rows']) != 40 or not all(r['attempted'] for r in batch['rows']):
            continue
        pairs = [r for r in comparisons if r['stage'] == batch['number']]
        both_baselines = all(any(b['layout'] == layout and b['context'] == batch['context'] for b in baselines) for layout in ['shared', 'split'])
        control_ok = all(r['valid'] and r['rt_max_per_second'] <= batch['context']['max_rt_per_second']
                         for r in batch['rows'] if r['threads'] == 0)
        if both_baselines and control_ok and len(pairs) == 4 and all(r['minimum_three_pairs'] for r in pairs):
            matrix_ok = True
    return [
        {'criterion': '至少一組具有可重現性的 DU-only baseline', 'passed': bool(baselines),
         'evidence': f'{len(baselines)} batches passed the unchanged ten-attempt baseline gate and recorded thread audit.'},
        {'criterion': '有效的 DU 工作負載及量測紀錄', 'passed': any(r['valid'] for r in rows),
         'evidence': f'{sum(r["valid"] for r in rows)} evidence-verified runs; decoder activity, complete interval logs, per-second CPU affinity and RT policy audited.'},
        {'criterion': '完成 shared / split CPU 資源配置比較', 'passed': matrix_ok,
         'evidence': 'Requires both matching baseline gates, all 40 matrix attempts, valid S0 controls, and >=3 repeat-matched valid pairs at each DQN thread level. Invalid fractions remain reported.'},
        {'criterion': '有一張能解釋觀察結果與限制的圖', 'passed': figure_ready and any(r['attempted'] for r in rows),
         'evidence': 'overview.png plus caption.md; valid/invalid counts, baseline gate, paired observations, metric and VM limitations.'}]


def plot_overview(session, state, stages, rows, comparisons, checks):
    os.environ.setdefault('MPLCONFIGDIR', '/tmp/ai-ran-matplotlib')
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(2, 3, figsize=(17, 10))
    baselines = [b for b in stages if b['phase'] == 'baseline']
    for batch in baselines:
        valid = [r for r in batch['rows'] if r['valid']]
        label = f'S{batch["number"]} {batch["layout"]} RT<={batch["context"]["max_rt_per_second"]} {"PASS" if batch.get("accepted") else "FAIL/pending"}'
        axes[0, 0].scatter([r['repeat'] + 1 for r in valid], [r['median_interval_avg_us'] for r in valid], label=label, alpha=.8)
    axes[0, 0].set(xlabel='S0 attempt number', ylabel='Median of 1s avg enqueue delay (us)', title='A. Baseline repeatability (fixed CV <=5%)')
    if baselines:
        axes[0, 0].legend(fontsize=7)
    for batch in stages:
        secs = [s['rt_failure_messages'] for r in batch['rows'] for s in r.get('seconds', [])]
        if secs:
            ordered = sorted(secs)
            axes[0, 1].step(ordered, [(i + 1) / len(ordered) for i in range(len(ordered))], where='post', label=f'S{batch["number"]} {batch["phase"]} {batch["layout"]}')
    axes[0, 1].set(xlabel='FAPI RT warning lines per second', ylabel='Fraction of sampled seconds', title='B. RT warnings (includes invalid sampled runs)')
    if axes[0, 1].lines:
        axes[0, 1].legend(fontsize=7)
    matrix = [r for r in rows if r['phase'] == 'matrix' and r['valid']]
    for layout, marker in [('shared', 'o'), ('split', '^')]:
        for threads in [0, 1, 2, 4]:
            vals = [r for r in matrix if r['layout'] == layout and r['threads'] == threads]
            if vals:
                axes[0, 2].scatter([r['dqn_steps_per_second'] for r in vals], [r['median_interval_avg_us'] for r in vals], marker=marker, label=f'{layout} DQN {threads}')
    axes[0, 2].set(xlabel='DQN optimizer updates/s', ylabel='Median of 1s avg enqueue delay (us)', title='C. DU / AI trade-off (one point per valid run)')
    if matrix:
        axes[0, 2].legend(fontsize=7)
    else:
        axes[0, 2].text(.5, .5, 'No valid DQN matrix observations\nBaseline-only results do not establish an AI trade-off.', ha='center', transform=axes[0, 2].transAxes)
    if comparisons:
        for item in comparisons:
            value = item['median_paired_delay_change_pct']
            if value != '':
                axes[1, 0].scatter(item['threads'], value, c='#287b8e' if item['minimum_three_pairs'] else '#b86b47')
                axes[1, 0].annotate(f'n={item["valid_pairs"]}', (item['threads'], value), xytext=(3, 5), textcoords='offset points')
    else:
        axes[1, 0].text(.5, .5, 'No repeat-matched matrix pairs\nCPU partition effects remain unestablished.', ha='center', transform=axes[1, 0].transAxes)
    axes[1, 0].axhline(0, color='gray', linewidth=1)
    axes[1, 0].set(xticks=[0, 1, 2, 4], xlabel='DQN intra-op threads', ylabel='Median paired split/shared change (%)', title='D. Matched-repeat delay change (negative = lower)')
    labels = [f'S{b["number"]}\n{b["phase"]}\n{b["layout"]}' for b in stages]
    for i, batch in enumerate(stages):
        valid = sum(r['valid'] for r in batch['rows'])
        invalid = sum(r['attempted'] and not r['valid'] for r in batch['rows'])
        missing = batch['planned'] - valid - invalid
        axes[1, 1].bar(i, valid, color='#438d72', label='Valid' if i == 0 else None)
        axes[1, 1].bar(i, invalid, bottom=valid, color='#ca6555', label='Invalid' if i == 0 else None)
        axes[1, 1].bar(i, missing, bottom=valid + invalid, color='#bbb', label='Unattempted' if i == 0 else None)
    axes[1, 1].set(xticks=range(len(labels)), xticklabels=labels, ylabel='Planned attempts', title='E. All outcomes retained')
    if stages:
        axes[1, 1].legend(fontsize=7)
    scopes = sorted({b['context']['collector'] for b in stages})
    axes[1, 2].axis('off')
    lines = [f'Session: {state.get("status", "unknown")}', f'Passing criteria: {sum(c["passed"] for c in checks)}/4',
             f'Collector: {", ".join(scopes) or "no measurements"}', '',
             'Limits:', '1s reported avg/max, not task median or P99.',
             'RT log lines are not unique missed slots.', 'vCPU affinity does not prove physical-core/cache isolation.',
             'DQN uses a synthetic control environment.', 'Paired medians are descriptive; no causal/significance claim.',
             'Failed gates block acceptance, even when valid data exist.']
    axes[1, 2].text(0, .98, '\n'.join(textwrap.fill(s, 49) for s in lines), va='top', fontsize=10)
    for ax in axes.flat[:5]:
        ax.grid(axis='y', alpha=.2)
    fig.suptitle('AI-RAN experiment outcome and limits | evidence-based acceptance', fontsize=16)
    fig.tight_layout(rect=(0, 0, 1, .96))
    fig.savefig(session / 'overview.png', dpi=160)
    plt.close(fig)
    perf = [r for r in rows if r.get('perf_valid')]
    if perf:
        fig, axes = plt.subplots(1, 3, figsize=(13, 4))
        for ax, key, title in zip(axes, ['cache_miss_rate_pct', 'cache_mpki', 'ipc'], ['Cache misses/references (%)', 'Cache misses per 1,000 instructions', 'Instructions/cycle']):
            for layout, marker in [('shared', 'o'), ('split', '^')]:
                vals = [r for r in perf if r['layout'] == layout]
                ax.scatter([r['stage'] for r in vals], [r['perf'][key] for r in vals], marker=marker, label=layout, alpha=.6)
            ax.set(xlabel='Stage (see perf-summary.csv for conditions)', ylabel=title); ax.legend(); ax.grid(alpha=.2)
        fig.suptitle('Valid measured DU perf counters; generic cache events do not identify L1/L2/LLC')
        fig.tight_layout(); fig.savefig(session / 'cache-overview.png', dpi=160); plt.close(fig)


def build(session, render=True):
    session = Path(session)
    state, stages, rows, errors = collect(session)
    comparisons = compare(stages)
    ready = False
    if render:
        try:
            preview_checks = acceptance(state, stages, rows, comparisons, figure_ready=True)
            plot_overview(session, state, stages, rows, comparisons, preview_checks)
            ready = (session / 'overview.png').exists()
        except Exception as exc:
            errors.append(f'Figure generation failed: {type(exc).__name__}: {exc}')
            if (session / 'overview.png').exists():
                (session / 'overview.png').unlink()
    checks = acceptance(state, stages, rows, comparisons, figure_ready=ready)
    save_csv(session / 'acceptance.csv', checks)
    save_csv(session / 'shared-split-comparison.csv', comparisons)
    save_csv(session / 'all-runs.csv', [{k: v for k, v in r.items() if k not in ['intervals', 'seconds', 'perf']} for r in rows])
    save_csv(session / 'perf-summary.csv', [{k: r[k] for k in ['stage', 'phase', 'layout', 'threads', 'repeat', 'run']} | r['perf'] for r in rows if r.get('perf_valid')])
    quality = []
    for batch in stages:
        for layout, threads in sorted({(r['layout'], r['threads']) for r in batch['rows']}):
            group = [r for r in batch['rows'] if (r['layout'], r['threads']) == (layout, threads)]
            attempted = sum(r['attempted'] for r in group)
            invalid = sum(r['attempted'] and not r['valid'] for r in group)
            quality.append({'stage': batch['number'], 'layout': layout, 'threads': threads, 'planned': len(group),
                            'attempted': attempted, 'invalid': invalid, 'not_attempted': len(group) - attempted,
                            'invalid_fraction_of_attempts': invalid / attempted if attempted else ''})
    save_csv(session / 'quality-summary.csv', quality)
    status = '全部通過' if all(c['passed'] for c in checks) else '部分完成／未通過；不得宣稱整輪完成'
    lines = ['# 本輪實驗驗收', '', f'狀態：**{status}**。遠端流程狀態：`{state.get("status")}`。', '',
             *[f'- [{"x" if c["passed"] else " "}] {c["criterion"]}' for c in checks], '',
             '## 驗收依據', '', *[f'- {c["criterion"]}：{c["evidence"]}' for c in checks], '',
             'baseline 通過表示同一批十次可重複，不是跨日期／跨主機重現的證明。',
             '比較的三組有效配對下限是交付完整性檢查，不是放寬 baseline CV 或 RT 門檻，也不是統計功效保證。', '',
             '## 觀察', '', f'計畫 {len(rows)} 次；已嘗試 {sum(r["attempted"] for r in rows)} 次；證據有效 {sum(r["valid"] for r in rows)} 次。']
    for batch in stages:
        if batch['phase'] == 'baseline':
            lines.append(f'- S{batch["number"]} {batch["layout"]} RT≤{batch["context"]["max_rt_per_second"]}：{"PASS" if batch.get("accepted") else "FAIL/pending"}；CV={batch["gate"].get("cv_pct")}；原因={batch["gate"].get("reasons")}。')
    for item in comparisons:
        lines.append(f'- DQN {item["threads"]} threads：有效配對 {item["valid_pairs"]}；split 相對 shared 延遲變化中位數 {item["median_paired_delay_change_pct"]}%。這是描述性觀測，不直接宣稱因果改善。')
    lines.extend(['', '## 圖與資料', '', '[總覽圖](overview.png)／[圖說](caption.md)／[完整性與無效比例](quality-summary.csv)／[所有 run](all-runs.csv)。',
                  '有硬體計數時另附 cache-overview.png 與 perf-summary.csv；沒有就不產生假 cache 數據。', '',
                  '## 未完成時的下一步', ''])
    if not checks[0]['passed']:
        lines.append('- 未取得通過 baseline：先依保留原因檢查 RT 權限、host 排程、有效 decoder 與固定工作量；不要事後調整門檻或挑成功 run。')
    if not checks[2]['passed']:
        lines.append('- shared/split 正式比較未完成：保留診斷圖；兩種 baseline 都過同一協定後，才補完整矩陣。')
    lines.extend(['- guest vCPU 分核不能排除 host 實體核心／SMT／LLC 競爭。每秒 avg/max 不是 task median/P99；RT 訊息不是唯一 deadline miss。',
                  '- 此 DQN 是可控制的合成環境訓練負載，非生產用 RAN 控制器。', *[f'- 分析缺件：{e}' for e in errors]])
    (session / 'completion.md').write_text('\n'.join(lines) + '\n')
    caption = ['# 圖說：觀察與限制', '',
               'A：每次 S0 的每秒平均延遲中位數，分批標示 gate 與 RT 上限，不把原批與備援混合。',
               'B：所有已採樣 run 的每秒 RT 訊息分布，包含無效 run；不是唯一 missed-slot 數。',
               'C：每個有效矩陣 run 的 DU 延遲與 DQN optimizer updates/s；沒有矩陣就明示未量到。',
               'D：相同 DQN threads／repeat 的 split 相對 shared 延遲變化，標 n；負數表示觀測延遲較低，不代表已證明分核的因果效應。',
               'E：每批有效、無效、未執行的絕對數；詳細 invalid/attempted 比例在 quality-summary.csv。',
               'F：驗收狀態、量測範圍與限制。圖中的每秒指標不是逐任務分布；不宣稱 P99 或 cache root cause。', '',
               f'本圖對應遠端狀態：{state.get("status")}；量測完成前的圖是進度快照，不是最終結論。']
    (session / 'caption.md').write_text('\n'.join(caption) + '\n')
    return checks


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('session', type=Path)
    a = p.parse_args()
    build(a.session)
