#!/usr/bin/env python3
"""Read-only progress/PMU summary; safe during measurement."""
import json
from pathlib import Path
from perf_cache import read_counts
from study_metrics import read_run
ROOT=Path(__file__).resolve().parents[1]
sessions=sorted((ROOT/'results/processed').glob('remote-session-*/status.json'))
if not sessions:raise SystemExit('No session found')
source=sessions[-1];state=json.loads(source.read_text())
print('Session:',source.parent.name,'status:',state['status'])
for index,stage in enumerate(state.get('stages',[]),1):
 raw=stage.get('results')
 log=source.parent/f'{index:02d}-{stage["phase"]}-{stage.get("layout") or "both"}-rt{stage["rt_ceiling"]}.log'
 if not raw and log.exists():raw=next((line.removeprefix('Results: ').strip() for line in log.read_text().splitlines() if line.startswith('Results: ')),None)
 if not raw:continue
 batch=Path(raw);batch=batch if batch.is_absolute() else ROOT/batch
 if not (batch/'protocol.json').exists():continue
 protocol=json.loads((batch/'protocol.json').read_text())
 folders=sorted(p for p in batch.iterdir() if p.is_dir())
 complete=[p for p in folders if (p/'run.json').exists()]
 print(f'{stage["phase"]} {stage.get("layout")}: completed={len(complete)}/{len(protocol["schedule"])}')
 for folder in complete:
  meta=json.loads((folder/'run.json').read_text())
  row,_,seconds,_=read_run(folder)
  print(' ',folder.name,'valid=',row['valid'],'reason=',row.get('invalid_reason',''),'RT max/s=',max((s['rt_failure_messages'] for s in seconds),default=0))
  if (folder/'perf.csv').exists():
   try:
    counts=read_counts(folder/'perf.csv')
    print('   PMU:',counts,'miss%=',round(100*counts['cache-misses']/counts['cache-references'],3),'IPC=',round(counts['instructions']/counts['cycles'],3))
   except RuntimeError as exc:print('   PMU unavailable:',exc)
  evidence=folder/'threads.jsonl'
  if evidence.exists():
   records=[json.loads(line) for line in evidence.read_text().splitlines()]
   print('   main_pool counts:',sorted({sum(t['name'].startswith('main_pool#') for t in r['du']) for r in records}))
 for folder in folders:
  if folder not in complete:print(' ',folder.name,'in progress; counters not finalized')
 gate=batch/'baseline-gate.json'
 if gate.exists():print(' Gate:',json.loads(gate.read_text()))
if state.get('reason'):print('Reason:',state['reason'])
