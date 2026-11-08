"""v4 protocol: identical DU across layouts, startup replacement cap, max-of-max reported only."""
import csv
import json
from pathlib import Path
import sys
import tempfile
import unittest
import unittest.mock
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from study_layout import load_layout_plan
from study_metrics import baseline_gate, dump
from run_study import render_config
import test_study


def write_plan(rows, folder):
    path = Path(folder) / 'plan.csv'
    with path.open('w', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys()); writer.writeheader(); writer.writerows(rows)
    return path


class LayoutV4Test(unittest.TestCase):
    def rows(self):
        with (ROOT / 'configs/cpu-layout-v4.csv').open() as f:
            return list(csv.DictReader(f))

    def test_only_ai_placement_differs(self):
        plan = load_layout_plan(ROOT / 'configs/cpu-layout-v4.csv')
        self.assertEqual(plan['version'], 4)
        shared, split = plan['layouts']['shared'], plan['layouts']['split']
        for key in shared:
            if key != 'dqn_cpus':
                self.assertEqual(shared[key], split[key], key)
        self.assertEqual(len(shared['dqn_cpus']), len(split['dqn_cpus']))
        self.assertTrue(set(shared['dqn_cpus']) <= set(shared['main_pool_cpus']))
        self.assertFalse(set(split['dqn_cpus']) & set(split['du_cpus']))
        self.assertNotIn(0, shared['du_cpus'])
        self.assertEqual(shared['spare_cpus'], [5])

    def test_config_has_three_workers_off_cpu0(self):
        roles = load_layout_plan(ROOT / 'configs/cpu-layout-v4.csv')['layouts']['split']
        cfg = render_config((ROOT / 'configs/du-uplink-only.yml').read_text(), '/tmp/x.log', roles)
        self.assertIn('main_pool_cpus: "2,3,4"', cfg)
        self.assertIn('ru_cpus: "1"', cfg)
        self.assertIn('nof_threads: 3', cfg)

    def test_invalid_v4_plans_rejected(self):
        mutations = [(1, 'du_cpus', '1,2,3,4', 'spare_cpus', ''),  # DU differs and no spare
                     (0, 'spare_cpus', '4', None, None),          # spare overlaps pool
                     (1, 'dqn_cpus', '5,6', None, None),          # split AI on spare/DU
                     (0, 'dqn_cpus', '3', None, None),            # AI CPU count differs
                     (0, 'housekeeping_cpus', '1', None, None)]   # housekeeping inside DU
        for index, key, value, key2, value2 in mutations:
            rows = self.rows(); rows[index][key] = value
            if key2:
                rows[index][key2] = value2 or '9'
            with self.subTest(key=key, value=value), tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(ValueError):
                    load_layout_plan(write_plan(rows, temp))


class GateV4Test(test_study.StudyTest):
    def setUp(self):
        super().setUp()
        self.ctx = {**self.ctx, 'gate_version': 4, 'startup_replacement_cap': 3}
        dump(self.base / 'protocol.json', {'phase': 'baseline', 'layout': 'shared', 'context': self.ctx,
                                          'schedule': self.schedule})

    def add_startup_failure(self, name):
        folder = self.base / name; folder.mkdir()
        dump(folder / 'run.json', {'status': 'failed', 'layout': 'shared', 'threads': 0, 'startup_failure': True,
                                   'error': 'No active decoder within 30 seconds'})

    def test_startup_failures_within_cap_do_not_block(self):
        for i in range(3):
            self.add_startup_failure(f'1{i}-shared-DQN0-x')
        gate = baseline_gate(self.base)
        self.assertTrue(gate['passed'], gate)
        self.assertEqual((gate['startup_failures'], gate['launches']), (3, 13))
        self.add_startup_failure('13-shared-DQN0-x')
        self.assertFalse(baseline_gate(self.base)['passed'])

    def test_sampling_failure_still_invalidates(self):
        m = json.loads((self.folder(3) / 'run.json').read_text()); m['status'] = 'failed'
        dump(self.folder(3) / 'run.json', m)
        self.assertFalse(baseline_gate(self.base)['passed'])

    def test_max_of_max_reported_not_gated(self):
        (self.folder(9) / 'gnb.log').write_text('\n'.join(
            self.metric(j, 100, 5000 if j == 5 else 200) for j in range(1, 10)))
        gate = baseline_gate(self.base)
        self.assertGreater(gate['cv_pct']['max_interval_max_us'], 5)
        self.assertTrue(gate['passed'], gate)
        dump(self.base / 'protocol.json', {'phase': 'baseline', 'layout': 'shared',
                                          'context': {**self.ctx, 'gate_version': 3}, 'schedule': self.schedule})
        self.assertFalse(baseline_gate(self.base)['passed'])

    def test_gate_requires_all_ten_and_consistent_context(self):
        self.assertTrue(baseline_gate(self.base, self.ctx)['passed'])


if __name__ == '__main__':
    unittest.main()


class MakeLayoutTest(unittest.TestCase):
    def test_smt_two_node_host(self):
        import make_layout
        # 2 nodes x 8 cores, SMT2: cpu c and c+16 are siblings; node0 = cores 0-7.
        topo = [{'cpu': c, 'core': c % 16, 'package': (c % 16) // 8, 'node': (c % 16) // 8,
                 'siblings': [c % 16, c % 16 + 16]} for c in range(32)]
        with tempfile.TemporaryDirectory() as temp, \
                unittest.mock.patch.object(make_layout, 'topology', return_value=topo), \
                unittest.mock.patch.object(make_layout, 'gpu_node', return_value=1), \
                unittest.mock.patch.object(sys, 'argv', ['x', '--out', str(Path(temp) / 'p.csv')]):
            make_layout.main()
            plan = load_layout_plan(Path(temp) / 'p.csv')['layouts']
        self.assertEqual(plan['split']['housekeeping_cpus'], [8, 24])   # GPU node, sibling kept
        self.assertEqual(plan['split']['du_cpus'], [9, 10, 11, 12, 13])
        self.assertEqual(plan['split']['dqn_cpus'], [14, 15])
        self.assertEqual(plan['shared']['dqn_cpus'], [11, 12])
        used = {c for r in plan['split'].values() for c in r}
        self.assertFalse(used & set(range(25, 32)))                       # no RT-core siblings used
