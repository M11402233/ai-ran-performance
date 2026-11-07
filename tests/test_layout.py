"""Checks that RU/observer isolation is real and remains in evidence audit."""
import copy
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from study_layout import load_layout_plan, required_cpus, validate_du_roles
from study_metrics import audit_threads
from run_study import render_config


class LayoutTest(unittest.TestCase):
    def test_plan_reserves_observer_and_ru_in_both_layouts(self):
        plan = load_layout_plan(ROOT / 'configs/cpu-layout-v3.csv')
        self.assertEqual(required_cpus(plan), set(range(8)))
        for roles in plan['layouts'].values():
            self.assertEqual(roles['ru_cpus'], [0])
            self.assertEqual(roles['observer_cpus'], [6, 7])
            self.assertFalse(set(roles['main_pool_cpus']) & set(roles['ru_cpus']))
            self.assertFalse(set(roles['observer_cpus']) & (set(roles['du_cpus']) | set(roles['dqn_cpus'])))

    def test_invalid_observer_overlap_is_rejected_before_launch(self):
        with tempfile.TemporaryDirectory() as temp:
            with (ROOT / 'configs/cpu-layout-v3.csv').open() as f:
                rows = list(csv.DictReader(f))
            rows[0]['observer_cpus'] = '5,7'
            p = Path(temp) / 'plan.csv'
            with p.open('w', newline='') as f:
                writer = csv.DictWriter(f, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
            with self.assertRaises(ValueError):load_layout_plan(p)

    def test_generated_config_separates_ru_and_pool(self):
        plan = load_layout_plan(ROOT / 'configs/cpu-layout-v3.csv')
        config = render_config((ROOT / 'configs/du-uplink-only.yml').read_text(), '/tmp/test.log', plan['layouts']['split'])
        self.assertIn('main_pool_cpus: "1,2,3"', config)
        self.assertIn('ru_cpus: "0"', config)
        self.assertIn('nof_threads: 3', config)

    def test_recorded_role_leaks_or_observer_overlap_fail_audit(self):
        roles = load_layout_plan(ROOT / 'configs/cpu-layout-v3.csv')['layouts']['split']
        workers = [{'name': f'main_pool#{i}', 'policy': 1, 'rt_priority': 96, 'cpus': [1, 2, 3]} for i in range(3)]
        workers.append({'name': 'ru_dummy', 'policy': 1, 'rt_priority': 98, 'cpus': [0]})
        validate_du_roles(workers, roles)
        meta = {'sample_start_epoch': 100, 'sample_end_epoch': 102, 'layout': 'split', 'threads': 1,
                'main_pool_threads': 3, 'thread_audit_required': True, 'cpu_roles': roles}
        records = [{'epoch': s+.01, 'completed_epoch': s+.02, 'scheduled_epoch': s,
                    'du': copy.deepcopy(workers), 'observer': {'cpus': [6, 7], 'policy': 0},
                    'dqn': [{'cpus': [4, 5], 'policy': 0}]} for s in [100, 101]]
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / 'threads.jsonl'
            def write(rows):path.write_text('\n'.join(json.dumps(r) for r in rows))
            write(records); self.assertTrue(audit_threads(Path(temp), meta))
            for target, key, value in [('ru', 'cpus', [0, 1]), ('pool', 'cpus', [0, 1, 2, 3]),
                                       ('pool', 'policy', 0), ('observer', 'cpus', [0, 7]),
                                       ('dqn', 'cpus', [4, 5, 6])]:
                bad = copy.deepcopy(records)
                row = bad[0]['du'][3] if target == 'ru' else bad[0]['du'][0] if target == 'pool' else bad[0]['observer'] if target == 'observer' else bad[0]['dqn'][0]
                row[key] = value; write(bad)
                with self.subTest(target=target, key=key):self.assertFalse(audit_threads(Path(temp), meta))

    def test_legacy_masks_remain_available(self):
        plan = load_layout_plan()
        self.assertEqual(plan['layouts']['shared']['du_cpus'], list(range(8)))
        self.assertEqual(plan['layouts']['split']['dqn_cpus'], [4, 5, 6, 7])
        self.assertEqual(plan['layouts']['split']['observer_cpus'], [])


if __name__ == '__main__':unittest.main()
