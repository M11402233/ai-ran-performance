#!/usr/bin/env python3
"""Plot measured per-run perf values only; write one aggregate CSV."""
import argparse
import csv
import json
import os
from pathlib import Path
os.environ.setdefault('MPLCONFIGDIR','/tmp/ai-ran-matplotlib')
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

p=argparse.ArgumentParser()
p.add_argument('run',type=Path)
p.add_argument('--out',type=Path,default=Path('deliverables'))
a=p.parse_args()
rows=[]
for path in sorted(a.run.glob('*/run.json')):
    m=json.loads(path.read_text())
    if m.get('status')=='ok' and m.get('perf'):
        rows.append({'run':path.parent.name,'condition':m['condition'],'repeat':m['repeat'],**m['perf']})
if not rows:
    raise SystemExit('No successful perf measurements; cache result plots cannot be generated.')
a.out.mkdir(parents=True,exist_ok=True)
with (a.out/'cache-summary.csv').open('w',newline='') as f:
    w=csv.DictWriter(f,fieldnames=list(rows[0]));w.writeheader();w.writerows(rows)
order=[c for c in ['S0','S1','S2','CPU_BG_PIN'] if any(r['condition']==c for r in rows)]
fig,axes=plt.subplots(1,3,figsize=(13,4))
for ax,key,label in zip(axes,['cache_miss_rate_pct','cache_mpki','ipc'],['Cache misses / references (%)','Cache misses / 1,000 instructions','Instructions / cycle']):
    for i,c in enumerate(order):
        vals=[r[key] for r in rows if r['condition']==c]
        ax.scatter([i+(j-(len(vals)-1)/2)*.05 for j in range(len(vals))],vals)
    ax.set_xticks(range(len(order)),[f'{c}\n(n={sum(r["condition"]==c for r in rows)})' for c in order])
    ax.set_ylabel(label);ax.grid(axis='y',alpha=.25)
fig.suptitle('perf stat: DU process and threads (generic hardware cache events)')
fig.tight_layout();fig.savefig(a.out/'cache-results.png',dpi=180);plt.close(fig)
print(a.out/'cache-results.png')
