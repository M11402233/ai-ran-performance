"""Per-CPU time split and stall windows from recorded per-second /proc/stat. Usage: analysis/cpu_time_diag.py BATCH_DIR..."""
import glob, json, sys, statistics as st
F = ['user','nice','system','idle','iowait','irq','softirq','steal']

def parse(text):
    out = {}
    for line in text.splitlines():
        if line.startswith('cpu') and line[3:4].isdigit():
            p = line.split(); out[int(p[0][3:])] = dict(zip(F, map(int, p[1:9])))
    return out

def delta(a, b):
    res = {}
    for c in a:
        d = {k: b[c][k] - a[c][k] for k in F}; tot = sum(d.values()) or 1
        res[c] = {k: 100 * v / tot for k, v in d.items()} | {'ticks': tot}
    return res

for base in sys.argv[1:]:
    print('\n==', base.split('/')[-1])
    agg = {}
    for run in sorted(glob.glob(base + '/*/threads.jsonl')):
        recs = [json.loads(l) for l in open(run)]
        snaps = [(r['monotonic'], parse(r['diagnostics']['cpu_stat'])) for r in recs]
        for (_, a), (_, b) in zip(snaps, snaps[1:]):
            for c, d in delta(a, b).items():
                agg.setdefault(c, []).append(d)
        folder = run.rsplit('/', 1)[0]
        meta = json.load(open(folder + '/run.json'))
        if meta['status'] != 'ok':
            after = json.load(open(folder + '/diagnostics-after.json'))
            gap = after['monotonic'] - snaps[-1][0]
            d = delta(snaps[-1][1], parse(after['cpu_stat']))
            print(f'  STALL {folder.split("/")[-1]}: {meta.get("error","")[:90]}')
            print(f'    last sample -> after: {gap:.2f}s; per-CPU % over that window:')
            for c, v in d.items():
                print(f'     cpu{c}: busy={100-v["idle"]-v["iowait"]-v["steal"]:5.1f} sys={v["system"]:5.1f} '
                      f'irq+si={v["irq"]+v["softirq"]:4.1f} steal={v["steal"]:5.2f} ticks={v["ticks"]}')
            print('    cpu_pressure after:', after['cpu_pressure'].splitlines()[0])
    print('  per-CPU mean over all sampled seconds (max steal second in brackets):')
    for c, rows in sorted(agg.items()):
        m = lambda k: st.mean(r[k] for r in rows)
        print(f'   cpu{c}: user={m("user"):5.1f} sys={m("system"):5.1f} irq+si={m("irq")+m("softirq"):4.1f} '
              f'idle={m("idle"):5.1f} steal={m("steal"):5.2f} [{max(r["steal"] for r in rows):5.1f}] '
              f'secs_steal>5%={sum(r["steal"]>5 for r in rows)}')
