#!/usr/bin/env python3
"""Serial, randomized synthetic-DU CPU controls. perf cache counters for the DU process and its threads."""
import argparse,datetime,json,os,random,re,signal,subprocess,time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];os.chdir(ROOT)
from perf_cache import preflight, start_perf, finish_perf
p=argparse.ArgumentParser();p.add_argument('--collector',choices=['perf','proc'],default='perf');p.add_argument('--config',default='configs/du-smoke.yml');p.add_argument('--warmup',type=float,default=30);p.add_argument('--sample',type=float,default=60);p.add_argument('--repeats',type=int,default=5);p.add_argument('--seed',type=int,default=20261030);p.add_argument('--label',default='formal-cpu');p.add_argument('--conditions',nargs='+',choices=['S0','S1','S2','CPU_BG_PIN'],default=['S0','S1','S2','CPU_BG_PIN']);a=p.parse_args()
if a.warmup<0 or a.sample<=1 or a.repeats<1:p.error('Require warmup >= 0, sample > 1, repeats >= 1')
if a.collector=='perf':preflight()
base=ROOT/'results/raw'/f'{a.label}-{datetime.datetime.now(datetime.timezone.utc):%Y%m%dT%H%M%SZ}';base.mkdir(parents=True)
schedule=[(c,i) for i in range(a.repeats) for c in a.conditions];random.Random(a.seed).shuffle(schedule)
(base/'protocol.json').write_text(json.dumps({'args':vars(a),'schedule':schedule,'S1':'2 Python arithmetic workers duty 0.5','S2':'8 Python arithmetic workers duty 1','CPU_BG_PIN':'8 workers duty 1 pinned to vCPU 6,7; DU mask unchanged; NOT full isolation'},indent=2))
def stop(q):
 if q.poll() is None:
  q.send_signal(signal.SIGINT)
  try:q.wait(timeout=8)
  except subprocess.TimeoutExpired:q.kill();q.wait()
for idx,(condition,rep) in enumerate(schedule):
 d=base/f'{idx:02d}-{condition}-{rep}';d.mkdir();cfg=(ROOT/a.config).read_text().replace('results/raw/gnb.log',str(d/'gnb.log'));(d/'config.yml').write_text(cfg)
 meta={'condition':condition,'repeat':rep,'start':datetime.datetime.now(datetime.timezone.utc).isoformat(),'warmup':a.warmup,'sample':a.sample};children=[];handles=[];profiler=None
 print(f'{idx+1}/{len(schedule)} {d.name}',flush=True)
 try:
  f=(d/'stdout.txt').open('w');handles.append(f)
  du=subprocess.Popen([str(ROOT/'bin/gnb'),'-c',str(d/'config.yml'),'-c',str(ROOT/'configs/pucch-small.yml')],stdout=f,stderr=subprocess.STDOUT,stdin=subprocess.PIPE);children.append(du)
  ready_deadline=time.monotonic()+30
  while time.monotonic()<ready_deadline:
   if du.poll() is not None:raise RuntimeError('DU exited before active PHY readiness')
   log=(d/'gnb.log').read_text(errors='replace') if (d/'gnb.log').exists() else ''
   if re.search(r'"pusch_dec_exec": nof_executes=\d+ nof_defers=[1-9]\d*',log):break
   time.sleep(.5)
  else:raise RuntimeError('No active PUSCH decoder within 30 seconds; do not measure idle executor')
  meta['phy_ready']=datetime.datetime.now(datetime.timezone.utc).isoformat()
  time.sleep(a.warmup)
  if du.poll() is not None:raise RuntimeError(f'DU startup failed: {du.returncode}')
  count,duty={'S0':(0,0),'S1':(2,.5),'S2':(8,1),'CPU_BG_PIN':(8,1)}[condition]
  for worker in range(count):
   wf=(d/f'worker-{worker}.txt').open('w');handles.append(wf)
   cmd=['python3',str(ROOT/'workloads/cpu_stress.py'),'--duty',str(duty)]
   if condition=='CPU_BG_PIN':cmd=['taskset','-c','6,7']+cmd
   children.append(subprocess.Popen(cmd,stdout=wf,stderr=subprocess.STDOUT))
  meta['sample_start']=datetime.datetime.now(datetime.timezone.utc).isoformat()
  if a.collector=='perf':profiler=start_perf(du.pid,a.sample,d/'perf.csv')
  snapshots=[]
  until=time.monotonic()+a.sample
  while time.monotonic()<until:
   if du.poll() is not None:raise RuntimeError(f'DU exited during sampling: {du.returncode}')
   if profiler is not None and profiler.poll() not in (None,0):raise RuntimeError(f'perf exited during sampling; inspect {d / "perf.csv"}')
   if any(q.poll() is not None for q in children[1:]):raise RuntimeError('Background worker exited unexpectedly')
   masks={}
   for task in (Path('/proc')/str(du.pid)/'task').iterdir():
    try:masks[task.name]=next(l.strip() for l in (task/'status').read_text().splitlines() if l.startswith('Cpus_allowed_list:'))
    except (OSError,StopIteration):pass
   snapshots.append({'utc':datetime.datetime.now(datetime.timezone.utc).isoformat(),'cpu':Path('/proc/stat').read_text().splitlines()[0],'du_stat':(Path('/proc')/str(du.pid)/'stat').read_text(),'thread_masks':masks})
   time.sleep(min(1,max(0,until-time.monotonic())))
  if profiler is not None:meta['perf']=finish_perf(profiler,d/'perf.csv')
  meta['sample_end']=datetime.datetime.now(datetime.timezone.utc).isoformat();meta['status']='ok';(d/'proc.json').write_text(json.dumps(snapshots))
 except Exception as e:meta['status']='failed';meta['error']=str(e)
 finally:
  if profiler is not None:stop(profiler)
  for q in reversed(children):stop(q)
  meta['returncodes']=[q.returncode for q in children]
  for f in handles:f.close()
  (d/'run.json').write_text(json.dumps(meta,indent=2))
 if meta['status']!='ok':raise SystemExit(f'Failed; inspect {d}')
print(f'Completed: {base}',flush=True)
