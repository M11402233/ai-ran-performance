#!/usr/bin/env python3
"""Generate a v4 CPU role plan from this host's real topology (one logical CPU per physical core).

  python3 scripts/make_layout.py                 # writes configs/cpu-layout-v4-<host>.csv
  python3 scripts/make_layout.py --node 1 --housekeeping 2
Roles: housekeeping(+observer) | RU | 3 workers | 1 spare | AI x2 (shared: on workers, split: own cores).
Never overwrites configs/cpu-layout-v4.csv (the old-VM plan). Review the output before freezing it.
"""
import argparse
import csv
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
from check_env import topology  # noqa: E402
from study_layout import load_layout_plan  # noqa: E402


def gpu_node():
    if not shutil.which('nvidia-smi'):
        return None
    out = subprocess.run(['nvidia-smi', 'topo', '-m'], capture_output=True, text=True).stdout
    m = re.search(r'^GPU0\s.*\s(\d+)\s*$', out, re.M)
    return int(m.group(1)) if m else None


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--node', type=int, help='NUMA node (default: GPU0 node, else 0)')
    ap.add_argument('--housekeeping', type=int, help='physical cores for OS/IRQ/observer (default 1, or 2 with >=10 cores)')
    ap.add_argument('--out', type=Path)
    a = ap.parse_args()
    topo = topology()
    node = a.node if a.node is not None else (gpu_node() or 0)
    cores = {}
    for r in topo:
        if r['node'] == node:
            cores.setdefault((r['package'], r['core']), sorted(r['siblings']))
    ordered = sorted(cores.values(), key=lambda s: s[0])
    hk = a.housekeeping or (2 if len(ordered) >= 10 else 1)
    need = hk + 7
    if len(ordered) < need:
        raise SystemExit(f'Node {node} has {len(ordered)} physical cores; v4 needs {need}. '
                         'Use another --node, fewer --housekeeping, or revise the protocol before measuring.')
    first = [s[0] for s in ordered]
    house = sorted(c for s in ordered[:hk] for c in s)          # housekeeping keeps its SMT siblings
    ru, pool, spare, split_ai = [first[hk]], first[hk + 1:hk + 4], [first[hk + 4]], first[hk + 5:hk + 7]
    du = sorted(ru + pool + spare)
    roles = {'housekeeping_cpus': house, 'du_cpus': du, 'ru_cpus': ru, 'main_pool_cpus': pool,
             'spare_cpus': spare, 'observer_cpus': [house[0]]}
    rows = [{'layout': 'shared', **roles, 'dqn_cpus': pool[1:3]}, {'layout': 'split', **roles, 'dqn_cpus': split_ai}]
    out = a.out or ROOT / 'configs' / f'cpu-layout-v4-{platform.node()}.csv'
    if out.resolve() == (ROOT / 'configs/cpu-layout-v4.csv').resolve():
        raise SystemExit('Refusing to overwrite the old-VM plan configs/cpu-layout-v4.csv')
    fields = ['layout', 'housekeeping_cpus', 'du_cpus', 'ru_cpus', 'main_pool_cpus', 'spare_cpus', 'dqn_cpus', 'observer_cpus']
    with out.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=fields); w.writeheader()
        for row in rows:
            w.writerow({k: ','.join(map(str, v)) if isinstance(v, list) else v for k, v in row.items()})
    load_layout_plan(out)  # same validation the study uses
    used = {c for row in rows for k, v in row.items() if k != 'layout' for c in v}
    idle_siblings = sorted(c for s in ordered[hk:hk + 7] for c in s[1:])
    unused = sorted({r['cpu'] for r in topo} - used - set(idle_siblings))
    print(out.read_text())
    print(f'NUMA node {node}; {len(ordered)} physical cores on node; housekeeping cores={hk}')
    if idle_siblings:
        print(f'SMT siblings of DU/AI cores left unassigned: {idle_siblings}. The OS can still run work there and it '
              'shares the core with RT threads; prefer SMT off (BIOS or /sys/devices/system/cpu/smt/control).')
    if unused:
        print(f'Other CPUs not in the plan: {unused} (other processes may run there; keep the host quiet).')
    shown = out.resolve().relative_to(ROOT) if out.resolve().is_relative_to(ROOT) else out
    print(f'Validated. Freeze it, then: sudo LAYOUT_PLAN={shown} bash scripts/start_baseline_v4.sh')


if __name__ == '__main__':
    main()
