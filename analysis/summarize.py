#!/usr/bin/env python3
import datetime,json,re,sys,os
os.environ.setdefault("MPLCONFIGDIR","/tmp/ai-ran-matplotlib")
from pathlib import Path
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
root=Path(__file__).resolve().parents[1]
base=Path(sys.argv[1]) if len(sys.argv)>1 else sorted((root/'results/raw').glob('pilot-*'))[-1]
out=root/'results/processed'/base.name;out.mkdir(parents=True,exist_ok=True)
rows=[]
for d in sorted(base.iterdir()):
 if not (d/'run.json').exists():continue
 m=json.loads((d/'run.json').read_text())
 if m['status']!='ok':continue
 lo=datetime.datetime.fromisoformat(m['sample_start']);hi=datetime.datetime.fromisoformat(m['sample_end'])
 for line in (d/'gnb.log').read_text(errors='replace').splitlines():
  match=re.search(r'^([0-9T:.\-]+).*Executor metrics "([^"]+)": (.*)',line)
  if not match:continue
  ts=datetime.datetime.fromisoformat(match[1]).replace(tzinfo=datetime.timezone.utc)
  # Drop first interval crossing workload start; retain only full intervals.
  if not lo+datetime.timedelta(seconds=1)<=ts<=hi:continue
  vals=dict(re.findall(r'(\w+)=([0-9.]+)',match[3]))
  rows.append({'run':d.name,'condition':m['condition'],'repeat':m['repeat'],'timestamp':ts.isoformat(),'executor':match[2],**{k:float(v) for k,v in vals.items()}})
f=pd.DataFrame(rows)
if f.empty:raise SystemExit('No sampled executor metrics; no plots generated')
f.to_csv(out/'executor-intervals.csv',index=False)
quality=[]
for run,group in f.groupby('run'):
 dec=group[group.executor=='pusch_dec_exec']
 active=int(((dec.nof_defers+dec.nof_executes)>0).sum())
 log=(base/run/'gnb.log').read_text(errors='replace')
 meta=json.loads((base/run/'run.json').read_text())
 lo=datetime.datetime.fromisoformat(meta['sample_start']);hi=datetime.datetime.fromisoformat(meta['sample_end'])
 sampled=[]
 for line in log.splitlines():
  try:ts=datetime.datetime.fromisoformat(line.split()[0]).replace(tzinfo=datetime.timezone.utc)
  except (ValueError,IndexError):continue
  if lo<=ts<=hi:sampled.append(line)
 samplelog='\n'.join(sampled)
 quality.append({'sample_rt_warning_messages':samplelog.count('Real-time failure'),'sample_skipped_slot_messages':samplelog.count('Skipped slot'),'run':run,'condition':group.condition.iloc[0],'decoder_intervals':len(dec),'active_decoder_intervals':active,'valid_activity':len(dec)>0 and active==len(dec),'rt_warning_messages_whole_run':log.count('Real-time failure'),'skipped_slot_messages_whole_run':log.count('Skipped slot')})
q=pd.DataFrame(quality);q.to_csv(out/'run-quality.csv',index=False)
f=f[f.run.isin(q.loc[q.valid_activity,'run'])]
if f.empty:raise SystemExit('All runs failed active PHY validation')
g=f.groupby(['run','condition','repeat','executor']).agg(intervals=('enqueue_avg','size'),enqueue_interval_mean_us=('enqueue_avg','mean'),enqueue_interval_max_us=('enqueue_max','max'),task_interval_mean_us=('task_avg','mean'),task_interval_max_us=('task_max','max'),vol_switches=('nof_vol_ctxt_switch','sum'),invol_switches=('nof_invol_ctxt_switch','sum'),defers=('nof_defers','sum')).reset_index();g.to_csv(out/'per-run.csv',index=False)
summary=g.groupby(['condition','executor']).agg(runs=('run','size'),enqueue_mean_us=('enqueue_interval_mean_us','mean'),enqueue_sd_us=('enqueue_interval_mean_us','std'),enqueue_median_us=('enqueue_interval_mean_us','median'),max_observed_enqueue_us=('enqueue_interval_max_us','max')).reset_index();summary.to_csv(out/'summary.csv',index=False)
# Preselect one busy PHY executor; retain full table for all executors.
z=g[g.executor=='pusch_dec_exec'];order=['S0','S1','S2','CPU_BG_PIN']
for name,col,title,ylabel in [('01-enqueue','enqueue_interval_mean_us','Pilot: PUSCH decoder enqueue delay','Mean of interval averages (us)'),('02-context','invol_switches','Pilot: decoder involuntary context switches','Sum over retained intervals'),('03-background-pinning','enqueue_interval_max_us','Pilot: maximum decoder enqueue delay','Maximum reported interval maximum (us)')]:
 fig,ax=plt.subplots(figsize=(8,4))
 for i,c in enumerate(order):
  vals=z.loc[z.condition==c,col].to_numpy();ax.scatter([i+(j-(len(vals)-1)/2)*.045 for j in range(len(vals))],vals,label=c)
 ax.set_xticks(range(len(order)),[f'{c} (n={int((z.condition==c).sum())})' for c in order]);ax.set_ylabel(ylabel);ax.set_title(title);ax.grid(axis='y',alpha=.25);fig.tight_layout();fig.savefig(out/(name+'.png'),dpi=160);plt.close(fig)
print(out)
print(summary[summary.executor=='pusch_dec_exec'].to_string(index=False))
