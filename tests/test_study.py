import datetime as dt
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from study_metrics import baseline_gate, dump, read_run
from perf_cache import read_counts
from remote_study import fallback_allowed, RT_ONLY


class StudyTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.base = Path(self.tmp.name)
        self.start = 1800000000
        self.ctx = {'effect_pct': 20, 'max_rt_per_second': 0, 'collector': 'proc'}
        self.schedule = [('shared', 0, i) for i in range(10)]
        dump(self.base / 'protocol.json', {'phase': 'baseline', 'layout': 'shared', 'context': self.ctx, 'schedule': self.schedule})
        for i in range(10):
            folder = self.folder(i); folder.mkdir()
            dump(folder / 'run.json', {'status': 'ok', 'layout': 'shared', 'threads': 0, 'affinity_verified': True,
                                      'rt_verified': True, 'sample_start_epoch': self.start, 'sample_end_epoch': self.start + 10})
            (folder / 'gnb.log').write_text('\n'.join(self.metric(j, 100, 200) for j in range(1, 10)))

    def folder(self, i):
        return self.base / f'{i:02d}-shared-DQN0-{i}'

    def stamp(self, offset):
        return dt.datetime.fromtimestamp(self.start + offset, dt.timezone.utc).replace(tzinfo=None).isoformat()

    def metric(self, offset, avg, maximum, activity=2):
        return f'{self.stamp(offset)} [METRICS] Executor metrics "pusch_dec_exec": nof_executes={activity} nof_defers=1 enqueue_avg={avg} enqueue_max={maximum}'

    def test_gate_requires_all_ten_and_consistent_context(self):
        self.assertTrue(baseline_gate(self.base, self.ctx)['passed'])
        self.assertFalse(baseline_gate(self.base, {**self.ctx, 'effect_pct': 10})['passed'])
        (self.folder(9) / 'run.json').unlink()
        self.assertFalse(baseline_gate(self.base)['passed'])

    def test_outlier_and_invalid_runs_block_gate(self):
        (self.folder(9) / 'gnb.log').write_text('\n'.join(self.metric(j, 200, 400) for j in range(1, 10)))
        gate = baseline_gate(self.base)
        self.assertFalse(gate['passed'])
        self.assertGreater(gate['cv_pct']['median_interval_avg_us'], 5)
        m = json.loads((self.folder(9) / 'run.json').read_text()); m['status'] = 'failed'
        dump(self.folder(9) / 'run.json', m)
        self.assertEqual(baseline_gate(self.base)['invalid_runs'], 1)

    def test_warning_second_boundaries_and_baseline_ceiling(self):
        p = self.folder(0) / 'gnb.log'
        with p.open('a') as f:
            for offset in [-.1, 0, 1.9, 10]:
                f.write(f'\n{self.stamp(offset)} [FAPI] Real-time failure in FAPI')
        row, _, seconds, _ = read_run(self.folder(0))
        self.assertTrue(row['valid'])
        self.assertEqual(row['rt_failure_messages'], 2)
        self.assertEqual(seconds[0]['rt_failure_messages'], 1)
        self.assertFalse(baseline_gate(self.base)['passed'])

    def test_missing_activity_rt_privilege_and_dqn_coverage(self):
        p = self.folder(0) / 'gnb.log'
        p.write_text(self.metric(1, 100, 200))
        self.assertFalse(read_run(self.folder(0))[0]['valid'])
        (self.folder(1) / 'stdout.txt').write_text('Warning: Scheduling priority of thread main_pool not changed. Cause: Not enough privileges.')
        self.assertFalse(read_run(self.folder(1))[0]['valid'])
        p = self.folder(2) / 'run.json'; m = json.loads(p.read_text()); m['threads'] = 1; dump(p, m)
        self.assertIn('DQN', read_run(self.folder(2))[0]['invalid_reason'])

    def test_report_preserves_failed_and_unattempted(self):
        m = json.loads((self.folder(1) / 'run.json').read_text()); m['status'] = 'failed'; dump(self.folder(1) / 'run.json', m)
        (self.folder(9) / 'run.json').unlink()
        out = self.base / 'out'
        subprocess.run([sys.executable, str(ROOT / 'analysis/analyze_study.py'), str(self.base), '--out', str(out)], check=True, capture_output=True)
        import csv
        with (out / 'quality.csv').open() as f:
            quality = next(csv.DictReader(f))
        self.assertEqual(quality['invalid'], '1')
        self.assertEqual(quality['attempted'], '9')
        self.assertEqual(quality['not_attempted'], '1')
        self.assertTrue((out / '02-delay-distributions.png').exists())
        self.assertTrue((out / '03-du-ai-tradeoff.png').exists())
        self.assertIn('FAIL', (out / 'report.md').read_text())

    def test_fallback_is_predeclared_both_rt_only(self):
        rt = {'passed': False, 'attempts': 10, 'invalid_runs': 0, 'reasons': [RT_ONLY]}
        self.assertTrue(fallback_allowed([rt, rt]))
        self.assertFalse(fallback_allowed([rt, {**rt, 'passed': True, 'reasons': []}]))
        self.assertFalse(fallback_allowed([rt, {**rt, 'reasons': [RT_ONLY, 'unstable CV']}]))
        self.assertFalse(fallback_allowed([rt, {**rt, 'invalid_runs': 1}]))

    def test_perf_never_turns_unavailable_into_zero(self):
        p = self.base / 'perf.csv'
        def content(value='10', coverage='100.00'):
            return '\n'.join(f'{value};;{event};100;{coverage};;' for event in ['cache-references', 'cache-misses', 'instructions', 'cycles'])
        p.write_text(content()); self.assertEqual(read_counts(p)['cycles'], 10)
        for value, coverage in [('<not supported>', '100'), ('<not counted>', '100'), ('nan', '100'), ('10', '50')]:
            p.write_text(content(value, coverage))
            with self.assertRaises(RuntimeError):
                read_counts(p)


if __name__ == '__main__':
    unittest.main()
