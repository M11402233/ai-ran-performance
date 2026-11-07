"""Regression checks for observer stalls and gate/acceptance disagreement."""
import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from run_study import check_sample_time, decoder_active
from study_metrics import audit_threads, read_run, baseline_gate
import test_study


class TimingTest(unittest.TestCase):
    def test_observer_stall_and_wall_clock_steps_are_rejected(self):
        check_sample_time(100, 10, 100.02, 10.02)
        for wall, mono in [(102.2479, 12.2479), (110.3419, 20.3419),
                           (101.02, 10.02), (99.02, 10.02), (100.02, 11.02)]:
            with self.subTest(wall=wall, mono=mono), self.assertRaises(RuntimeError):
                check_sample_time(100, 10, wall, mono)

    def test_decoder_requires_latest_actual_work_in_either_counter(self):
        def metric(executed, deferred):
            return f'Executor metrics "pusch_dec_exec": nof_executes={executed} nof_defers={deferred}'
        self.assertFalse(decoder_active(''))
        self.assertFalse(decoder_active(metric(0, 0)))
        self.assertTrue(decoder_active(metric(3, 0)))
        self.assertTrue(decoder_active(metric(0, 3)))
        self.assertFalse(decoder_active(metric(0, 3) + '\n' + metric(0, 0)))

    def test_thread_audit_rejects_duplicate_and_late_capture(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            meta = {'sample_start_epoch': 100, 'sample_end_epoch': 102, 'layout': 'split',
                    'threads': 0, 'main_pool_threads': 3, 'thread_audit_required': True}
            pool = [{'name': f'main_pool#{i}', 'policy': 1, 'rt_priority': 96, 'cpus': [0, 1, 2, 3]}
                    for i in range(3)]
            rows = [{'epoch': s + .01, 'completed_epoch': s + .02, 'scheduled_epoch': s,
                     'du': copy.deepcopy(pool)} for s in [100, 101]]
            path = folder / 'threads.jsonl'
            def write(records):
                path.write_text('\n'.join(json.dumps(r) for r in records))
            write(rows)
            self.assertTrue(audit_threads(folder, meta))
            write(rows + [rows[-1]])
            self.assertFalse(audit_threads(folder, meta))
            bad = copy.deepcopy(rows); bad[0]['completed_epoch'] = 101.1
            write(bad)
            self.assertFalse(audit_threads(folder, meta))
            bad = copy.deepcopy(rows); bad[0]['du'].pop()
            write(bad)
            self.assertFalse(audit_threads(folder, meta))


class GateEvidenceTest(unittest.TestCase):
    def test_runtime_validity_includes_thread_evidence_for_new_runs(self):
        # Reuse a complete interval fixture, then remove only the thread evidence.
        fixture = test_study.StudyTest(); fixture.setUp()
        try:
            folder = fixture.folder(0)
            meta = json.loads((folder / 'run.json').read_text())
            meta.update(thread_audit_required=True, main_pool_threads=3)
            (folder / 'run.json').write_text(json.dumps(meta))
            self.assertIn('per-second affinity/RT policy evidence', read_run(folder)[0]['invalid_reason'])
            records = [{'epoch': s + .01, 'completed_epoch': s + .02, 'scheduled_epoch': s,
                        'du': [{'name': f'main_pool#{i}', 'policy': 1, 'rt_priority': 96, 'cpus': list(range(8))}
                               for i in range(3)]} for s in range(fixture.start, fixture.start + 10)]
            (folder / 'threads.jsonl').write_text('\n'.join(json.dumps(r) for r in records))
            self.assertTrue(read_run(folder)[0]['valid'])
            self.assertTrue(baseline_gate(fixture.base)['passed'])
            records[3]['epoch'] += 2
            (folder / 'threads.jsonl').write_text('\n'.join(json.dumps(r) for r in records))
            self.assertFalse(read_run(folder)[0]['valid'])
            self.assertFalse(baseline_gate(fixture.base)['passed'])
        finally:
            fixture.doCleanups()


if __name__ == '__main__':
    unittest.main()
