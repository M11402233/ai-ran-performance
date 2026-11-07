#!/usr/bin/env python3
"""Incrementally relink local gNB using existing objects; leave source/build untouched."""
from pathlib import Path
import difflib, hashlib, json, shlex, shutil, subprocess
root=Path(__file__).resolve().parents[1]
source=Path('/home/cindy2/oran-lab/srsRAN_Project')
build=source/'build'
out=root/'builds/worker-fix';out.mkdir(parents=True,exist_ok=True)
relative=Path('apps/services/worker_manager/worker_manager.cpp')
old=(source/relative).read_text()
needle='    nof_workers = worker_cfg.nof_main_pool_threads.value();'
assert old.count(needle)==1
new=old.replace(needle,'''    // Honor an explicit pool size; spare-CPU reservation applies only to auto sizing.
    return std::max(1U, std::min(worker_cfg.nof_main_pool_threads.value(), avail_cpus));''')
(out/'worker_manager.cpp').write_text(new)
(root/'docs/explicit-worker-count.patch').write_text(''.join(difflib.unified_diff(old.splitlines(True),new.splitlines(True),fromfile='a/'+str(relative),tofile='b/'+str(relative))))
flags=(build/'apps/services/worker_manager/CMakeFiles/srsran_worker_manager_app_service.dir/flags.make').read_text()
args=[]
for line in flags.splitlines():
 if line.startswith(('CXX_DEFINES =','CXX_INCLUDES =','CXX_FLAGS =')):args+=shlex.split(line.split('=',1)[1])
subprocess.run(['/usr/bin/c++',*args,'-I'+str((source/relative).parent),'-c',str(out/'worker_manager.cpp'),'-o',str(out/'worker_manager.cpp.o')],check=True)
archive=out/'libsrsran_worker_manager_app_service.a'
shutil.copy2(build/'apps/services/worker_manager'/archive.name,archive)
subprocess.run(['ar','r',str(archive),str(out/'worker_manager.cpp.o')],check=True)
subprocess.run(['ranlib',str(archive)],check=True)
command=shlex.split((build/'apps/gnb/CMakeFiles/gnb.dir/link.txt').read_text())
command[command.index('-o')+1]=str(root/'bin/gnb-worker-fixed')
command=[str(archive) if x=='../services/worker_manager/'+archive.name else x for x in command]
subprocess.run(command,cwd=build/'apps/gnb',check=True)
manifest={'method':'incremental relink with existing local objects; not a clean-source rebuild','source':str(source),'source_original_sha256':hashlib.sha256(old.encode()).hexdigest(),'binary_sha256':hashlib.sha256((root/'bin/gnb-worker-fixed').read_bytes()).hexdigest()}
(out/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
print(json.dumps(manifest,indent=2))
