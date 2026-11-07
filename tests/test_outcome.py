"""Fast postprocessing tests; no gNB, DQN, rendering or stress workers."""
import copy
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'analysis'))
from build_outcome import acceptance, audit_threads, compare, build


class OutcomeTest(unittest.TestCase):
    def fixture(self):
        context = {'collector': 'perf', 'max_rt_per_second': 0}
        stages = [{'phase': 'baseline', 'layout': layout, 'accepted': True, 'context': context} for layout in ['shared', 'split']]
        rows = []
        for repeat in range(5):
            for threads in [0, 1, 2, 4]:
                for layout in ['shared', 'split']:
                    rows.append({'phase': 'matrix', 'layout': layout, 'threads': threads, 'repeat': repeat,
                                 'attempted': True, 'valid': True, 'rt_max_per_second': 0,
                                 'median_interval_avg_us': 100 if layout == 'shared' else 80,
                                 'dqn_steps_per_second': 0 if not threads else 200})
        stages.append({'number': 3, 'phase': 'matrix', 'rows': rows, 'context': context})
        return stages, rows

    def test_completed_paired_comparison_and_baselines(self):
        stages, rows = self.fixture()
        comparison = compare(stages)
        self.assertEqual(comparison[1]['valid_pairs'], 5)
        self.assertAlmostEqual(comparison[1]['median_paired_delay_change_pct'], -20)
        self.assertTrue(all(r['passed'] for r in acceptance({}, stages, rows, comparison, True)))

    def test_gate_failure_cannot_be_hidden_by_complete_matrix(self):
        stages, rows = self.fixture()
        stages[0]['accepted'] = False
        checks = acceptance({}, stages, rows, compare(stages), True)
        self.assertTrue(checks[0]['passed'])  # At least one baseline passes.
        self.assertFalse(checks[2]['passed'])  # Both are required for a formal comparison.

    def test_missing_and_invalid_runs_remain_failures(self):
        stages, rows = self.fixture()
        for row in rows:
            if row['layout'] == 'split' and row['threads'] == 4 and row['repeat'] < 3:
                row['valid'] = False
        self.assertFalse(acceptance({}, stages, rows, compare(stages), True)[2]['passed'])
        stages, rows = self.fixture()
        rows[0]['attempted'] = False
        self.assertFalse(acceptance({}, stages, rows, compare(stages), True)[2]['passed'])

    def test_baseline_only_is_not_a_dqn_comparison(self):
        stages, rows = self.fixture()
        checks = acceptance({}, stages[:2], rows[:1], [], False)
        self.assertTrue(checks[0]['passed'])
        self.assertFalse(checks[2]['passed'])
        self.assertFalse(checks[3]['passed'])

    def test_end_to_end_baseline_report_does_not_claim_matrix_or_figure(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp); base = root / 'baseline'; session = root / 'session'
            base.mkdir(); session.mkdir()
            context = {'collector': 'proc', 'effect_pct': 20, 'max_rt_per_second': 0}
            schedule = [('shared', 0, i) for i in range(10)]
            (base / 'protocol.json').write_text(json.dumps({'phase': 'baseline', 'layout': 'shared', 'context': context, 'schedule': schedule}))
            for i in range(10):
                folder = base / f'{i:02d}-shared-DQN0-{i}'; folder.mkdir()
                meta = {'status': 'ok', 'layout': 'shared', 'threads': 0, 'affinity_verified': True,
                        'rt_verified': True, 'sample_start_epoch': 100, 'sample_end_epoch': 110}
                (folder / 'run.json').write_text(json.dumps(meta))
                lines = []
                for second in range(101, 110):
                    stamp = dt.datetime.fromtimestamp(second, dt.timezone.utc).replace(tzinfo=None).isoformat()
                    lines.append(f'{stamp} Executor metrics "pusch_dec_exec": nof_executes=2 nof_defers=1 enqueue_avg=100 enqueue_max=200')
                (folder / 'gnb.log').write_text('\n'.join(lines))
                snapshots = [{'epoch': second + .01, 'du': [{'cpus': list(range(8)), 'policy': 1,
                              'rt_priority': 96, 'name': 'main_pool#0'}]} for second in range(100, 110)]
                (folder / 'threads.jsonl').write_text('\n'.join(json.dumps(s) for s in snapshots))
            (session / 'status.json').write_text(json.dumps({'status': 'stopped', 'stages': [
                {'phase': 'baseline', 'layout': 'shared', 'rt_ceiling': 0, 'results': str(base)}]}))
            checks = build(session, render=False)
            self.assertEqual([c['passed'] for c in checks], [True, True, False, False])
            self.assertTrue((session / 'completion.md').exists())
            self.assertTrue((session / 'all-runs.csv').exists())
            self.assertFalse((session / 'overview.png').exists())

    def test_thread_evidence_requires_full_coverage_and_separation(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            meta = {'sample_start_epoch': 100, 'sample_end_epoch': 102, 'layout': 'split', 'threads': 1}
            du = {'cpus': [0, 1, 2, 3], 'policy': 1, 'rt_priority': 96, 'name': 'main_pool#0'}
            ai = {'cpus': [4, 5, 6, 7], 'policy': 0}
            records = [{'epoch': s + .01, 'du': [copy.deepcopy(du)], 'dqn': [copy.deepcopy(ai)]} for s in [100, 101]]
            path = folder / 'threads.jsonl'
            path.write_text('\n'.join(json.dumps(r) for r in records))
            self.assertTrue(audit_threads(folder, meta))
            path.write_text(json.dumps(records[0]))
            self.assertFalse(audit_threads(folder, meta))
            records[1]['du'][0]['cpus'] = [0, 4]
            path.write_text('\n'.join(json.dumps(r) for r in records))
            self.assertFalse(audit_threads(folder, meta))


if __name__ == '__main__':
    unittest.main()
