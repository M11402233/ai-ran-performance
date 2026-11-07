#!/usr/bin/env python3
"""Short worker-count smoke check, not a baseline or RT qualification."""
from pathlib import Path
import json, os, signal, subprocess, time
root=Path(__file__).resolve().parents[1]
output=root/'builds/worker-fix/smoke';output.mkdir(parents=True,exist_ok=True)
results=[]
for binary,layout,mask,expected in [('gnb-original-20261030','shared','0-7',3),('gnb-original-20261030','split','0-3',1),('gnb-worker-fixed','shared','0-7',3),('gnb-worker-fixed','split','0-3',3)]:
 folder=output/(binary+'-'+layout);folder.mkdir(exist_ok=True)
 cpus='0,1,2,3,4,5,6,7' if layout=='shared' else '0,1,2,3'
 cfg=(root/'configs/du-reduced.yml').read_text().replace('results/raw/gnb.log',str(folder/'gnb.log'))
 cfg+='\nexpert_execution:\n  affinities:\n    main_pool_cpus: "'+cpus+'"\n    main_pool_pinning: mask\n  cell_affinities:\n    - ru_cpus: "'+cpus+'"\n      ru_pinning: mask\n  threads:\n    main_pool:\n      nof_threads: 3\n'
 (folder/'config.yml').write_text(cfg)
 with (folder/'stdout.txt').open('w') as log:
  process=subprocess.Popen(['taskset','-c',mask,str(root/'bin'/binary),'-c',str(folder/'config.yml'),'-c',str(root/'configs/pucch-small.yml')],stdin=subprocess.PIPE,stdout=log,stderr=subprocess.STDOUT)
  samples=[]
  try:
   for i in range(40):
    time.sleep(.25)
    if process.poll() is not None:break
    threads=[]
    try:
     for task in (Path('/proc')/str(process.pid)/'task').iterdir():
      name=(task/'comm').read_text().strip()
      if name.startswith('main_pool#'):threads.append({'name':name,'mask':sorted(os.sched_getaffinity(int(task.name)))})
    except FileNotFoundError:continue
    if threads:samples.append(threads)
    if len(samples)>=5:break
  finally:
   if process.poll() is None:
    process.send_signal(signal.SIGINT)
    try:process.wait(timeout=10)
    except subprocess.TimeoutExpired:process.kill();process.wait()
 row={'binary':binary,'layout':layout,'expected':expected,'samples':samples,'passed':len(samples)==5 and all(len(s)==expected for s in samples),'qualification':'worker count only; no RT or baseline qualification'}
 results.append(row);print(binary,layout,row['passed'],[len(s) for s in samples],flush=True)
(output/'results.json').write_text(json.dumps(results,indent=2)+'\n')
assert all(r['passed'] for r in results), 'See smoke logs'
