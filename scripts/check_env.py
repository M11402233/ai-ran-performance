#!/usr/bin/env python3
"""Read-only host inventory and suitability check for the DU/AI co-location study.

Run without sudo first; sudo adds RT-priority and debugfs checks. Never changes the system.
  python3 scripts/check_env.py [--perf-seconds 3] [--json results/env/<host>.json]
"""
import argparse
import datetime as dt
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import time

SYS = Path('/sys/devices/system')
results = []


def note(level, item, detail):
    results.append({'level': level, 'item': item, 'detail': detail})
    print(f'[{level:4}] {item}: {detail}')


def read(path, default=''):
    try:
        return Path(path).read_text().strip()
    except OSError:
        return default


def run(cmd, timeout=20):
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, p.stdout + p.stderr
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, str(exc)


def parse_list(text):
    cpus = set()
    for part in filter(None, text.split(',')):
        a, _, b = part.partition('-')
        cpus.update(range(int(a), int(b or a) + 1))
    return cpus


def topology():
    cpus = sorted(parse_list(read(SYS / 'cpu/online')))
    rows = []
    for c in cpus:
        t = SYS / f'cpu/cpu{c}/topology'
        node = next((int(n.name[4:]) for n in (SYS / f'cpu/cpu{c}').glob('node*')), 0)
        rows.append({'cpu': c, 'core': int(read(t / 'core_id', c)), 'package': int(read(t / 'physical_package_id', 0)),
                     'node': node, 'siblings': sorted(parse_list(read(t / 'thread_siblings_list', str(c))))})
    return rows


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument('--perf-seconds', type=float, default=3)
    ap.add_argument('--rt-seconds', type=int, default=30, help='cyclictest duration when run as root')
    ap.add_argument('--json', type=Path)
    a = ap.parse_args()
    root = os.geteuid() == 0
    print(f'== Host {platform.node()}  {dt.datetime.now(dt.timezone.utc):%Y-%m-%d %H:%M UTC}  root={root}\n')

    # --- Platform -----------------------------------------------------------------------------
    cpuinfo = read('/proc/cpuinfo')
    model = next((l.split(':', 1)[1].strip() for l in cpuinfo.splitlines() if l.startswith('model name')), '?')
    flags = set(next((l.split(':', 1)[1].split() for l in cpuinfo.splitlines() if l.startswith('flags')), []))
    note('INFO', 'CPU model', model)
    note('INFO', 'Kernel', platform.release() + ('  (PREEMPT_RT)' if 'PREEMPT_RT' in read('/proc/version') or
                                                 read('/sys/kernel/realtime') == '1' else ''))
    _, virt = run(['systemd-detect-virt'])
    virt = virt.strip() or 'unknown'
    note('OK' if virt == 'none' else 'WARN', 'Virtualization',
         virt + ('' if virt == 'none' else ' -> guest: ask for dedicated (non-overcommitted) pinned pCPUs; watch steal'))
    mem_kb = int(re.search(r'MemTotal:\s+(\d+)', read('/proc/meminfo')).group(1))
    note('OK' if mem_kb > 15e6 else 'WARN', 'RAM', f'{mem_kb / 1048576:.1f} GiB (>=16 GiB recommended for gNB build + PyTorch)')
    for f in ('avx2', 'avx512f', 'fma'):
        if f == 'avx2' and f not in flags:
            note('FAIL', 'ISA', 'no AVX2: srsRAN PHY will be slow/unsupported')
    note('INFO', 'ISA', ' '.join(f for f in ('sse4_1', 'avx2', 'fma', 'avx512f', 'avx512bw') if f in flags))

    # --- Topology -----------------------------------------------------------------------------
    topo = topology()
    phys = {(r['package'], r['core']) for r in topo}
    nodes = sorted({r['node'] for r in topo})
    smt = max(len(r['siblings']) for r in topo)
    note('INFO', 'Logical CPUs', f'{len(topo)} online; affinity of this shell: {len(os.sched_getaffinity(0))}')
    note('OK' if len(phys) >= 8 else 'FAIL', 'Physical cores',
         f'{len(phys)} (v4 needs >=8 physical: 1 housekeeping, 1 RU, 3 workers, 1 spare, 2 AI; 10+ preferred)')
    note('WARN' if smt > 1 else 'OK', 'SMT', f'{smt} threads/core ' + read(SYS / 'cpu/smt/control', '') +
         (' -> make_layout.py uses one thread per core and leaves siblings idle' if smt > 1 else ''))
    note('OK' if len(nodes) == 1 else 'WARN', 'NUMA nodes', f'{nodes} ' +
         ('' if len(nodes) == 1 else '-> keep DU, AI and GPU on one node (make_layout.py --node)'))
    cmdline = read('/proc/cmdline')
    iso = {k: v for k, v in re.findall(r'\b(isolcpus|nohz_full|rcu_nocbs|irqaffinity)=(\S+)', cmdline)}
    note('INFO', 'Kernel isolation', iso or 'none (allowed; study protocol does not require boot options)')

    # --- Frequency / power ----------------------------------------------------------------------
    govs = {read(SYS / f'cpu/cpu{r["cpu"]}/cpufreq/scaling_governor') for r in topo} - {''}
    if govs:
        note('OK' if govs == {'performance'} else 'WARN', 'CPU governor',
             f'{sorted(govs)}' + ('' if govs == {'performance'} else ' -> set performance before baselines'))
    else:
        note('INFO', 'CPU governor', 'no cpufreq (VM or firmware-controlled)')
    boost = read(SYS / 'cpu/cpufreq/boost') or read(SYS / 'cpu/intel_pstate/no_turbo')
    if boost:
        note('INFO', 'Turbo/boost', f'boost={read(SYS / "cpu/cpufreq/boost", "?")} no_turbo={read(SYS / "cpu/intel_pstate/no_turbo", "?")} (record; keep fixed across runs)')
    idle = sorted({read(p) for p in SYS.glob('cpu/cpu0/cpuidle/state*/name')})
    note('INFO', 'C-states (cpu0)', idle or 'none exposed')

    # --- RT / scheduler -------------------------------------------------------------------------
    rt = read('/proc/sys/kernel/sched_rt_runtime_us'), read('/proc/sys/kernel/sched_rt_period_us')
    note('INFO', 'RT throttling', f'runtime={rt[0]} period={rt[1]} (protocol keeps default 950000/1000000)')
    if root:
        code, out = run(['chrt', '-f', '50', 'true'])
        note('OK' if code == 0 else 'FAIL', 'SCHED_FIFO', 'available as root' if code == 0 else out.strip())
    else:
        note('INFO', 'SCHED_FIFO', 'rerun with sudo to test RT priority')

    if root and shutil.which('cyclictest'):
        cpus = ','.join(str(r['cpu']) for r in topo[1:min(len(topo), 6)])
        code, out = run(['cyclictest', '-m', '-q', '-p', '95', '-i', '200', '-D', str(a.rt_seconds),
                         '-a', cpus, '-t', str(len(cpus.split(',')))], timeout=a.rt_seconds + 30)
        worst = max(map(int, re.findall(r'Max:\s+(\d+)', out)), default=None)
        level = 'FAIL' if worst is None or worst >= 200 else 'WARN' if worst >= 50 else 'OK'
        note(level, f'RT latency cyclictest {a.rt_seconds}s cpus {cpus}',
             f'worst {worst} us (OK<50, WARN<200; 1 ms slots need low tens of us)' if worst is not None else out[-200:])
    else:
        note('INFO', 'RT latency', 'rerun with sudo and rt-tests installed (cyclictest) to measure wake-up latency')

    # --- PMU / perf -----------------------------------------------------------------------------
    para = read('/proc/sys/kernel/perf_event_paranoid')
    note('INFO', 'perf_event_paranoid', f'{para} (study sets 1 temporarily)')
    if shutil.which('perf') and not root and para not in ('-1', '0', '1'):
        note('INFO', 'Hardware PMU', 'paranoid>1 for non-root; rerun with sudo to test PMU events')
    elif shutil.which('perf'):
        code, out = run(['perf', 'stat', '-x;', '-e', 'cycles,instructions,cache-references,cache-misses',
                         'sleep', str(a.perf_seconds)], timeout=a.perf_seconds + 15)
        bad = [l for l in out.splitlines() if '<not' in l]
        note('OK' if code == 0 and not bad else 'WARN', 'Hardware PMU',
             'cycles/instructions/cache events counted' if code == 0 and not bad else (bad or out.strip().splitlines()[-1:]))
    else:
        note('FAIL', 'perf', 'missing: install linux-tools-$(uname -r)')

    # --- Background noise / steal ---------------------------------------------------------------
    def stat():
        return {l.split()[0]: list(map(int, l.split()[1:9])) for l in read('/proc/stat').splitlines() if re.match(r'cpu\d', l)}
    s0 = stat(); time.sleep(3); s1 = stat()
    busy, steal = {}, 0.
    for c in s0:
        d = [y - x for x, y in zip(s0[c], s1[c])]; tot = sum(d) or 1
        busy[c] = 100 * (tot - d[3] - d[4]) / tot; steal = max(steal, 100 * d[7] / tot)
    noisy = {c: round(v) for c, v in busy.items() if v > 5}
    note('OK' if not noisy else 'WARN', 'Idle background (3 s)', 'all CPUs <5% busy' if not noisy else f'busy CPUs {noisy}')
    note('OK' if steal < 0.5 else 'WARN', 'Steal (3 s)', f'max {steal:.2f}%')
    load = read('/proc/loadavg')
    note('INFO', 'Load average', load)

    # --- GPU ------------------------------------------------------------------------------------
    if shutil.which('nvidia-smi'):
        _, out = run(['nvidia-smi', '--query-gpu=name,driver_version,memory.total,pcie.link.gen.max,pcie.link.width.max',
                      '--format=csv,noheader'])
        note('OK', 'GPU', out.strip())
        _, topo_out = run(['nvidia-smi', 'topo', '-m'])
        aff = re.search(r'GPU0\s.*?\s(\d[\d,\-]*)\s+(\d+|N/A)\s*$', topo_out, re.M)
        note('INFO', 'GPU CPU/NUMA affinity', f'cpus={aff.group(1)} node={aff.group(2)}' if aff else topo_out.strip()[-300:])
        _, cuda = run(['nvidia-smi'])
        m = re.search(r'CUDA Version:\s*([\d.]+)', cuda)
        note('INFO', 'Driver CUDA version', m.group(1) if m else '?')
    else:
        _, lspci = run(['lspci'])
        gpus = [l for l in lspci.splitlines() if re.search(r'VGA|3D|NVIDIA', l)]
        note('WARN', 'GPU', f'nvidia-smi missing; PCI: {gpus or "none found"}')

    # --- Toolchain ------------------------------------------------------------------------------
    for tool in ('gcc', 'g++', 'cmake', 'make', 'git', 'python3', 'tmux', 'taskset', 'chrt', 'perf', 'pidstat', 'mpstat'):
        path = shutil.which(tool)
        version = run([tool, '--version'])[1].splitlines()[0] if path and tool in ('gcc', 'cmake', 'python3') else ''
        note('OK' if path else ('WARN' if tool in ('pidstat', 'mpstat') else 'FAIL'), f'tool {tool}', version or path or 'missing')
    libs = {'fftw3f': 'libfftw3f.so', 'mbedtls': 'libmbedtls.so', 'sctp': 'libsctp.so', 'yaml-cpp': 'libyaml-cpp.so'}
    _, ldc = run(['ldconfig', '-p'])
    for name, so in libs.items():
        note('OK' if so in ldc else 'FAIL', f'lib {name}', 'found' if so in ldc else 'missing (-dev package)')

    # --- Verdict --------------------------------------------------------------------------------
    fails = [r for r in results if r['level'] == 'FAIL']
    warns = [r for r in results if r['level'] == 'WARN']
    print(f'\n== {len(fails)} FAIL, {len(warns)} WARN. ' +
          ('Fix FAILs before building/measuring.' if fails else 'Suitable to build; next: scripts/make_layout.py'))
    report = {'host': platform.node(), 'utc': dt.datetime.now(dt.timezone.utc).isoformat(), 'root': root,
              'topology': topo, 'results': results}
    out = a.json or Path(__file__).resolve().parents[1] / 'results/env' / f'{platform.node()}-{dt.datetime.now(dt.timezone.utc):%Y%m%dT%H%M%SZ}.json'
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, indent=2))
    print(f'Saved {out}')


if __name__ == '__main__':
    main()
