#!/usr/bin/env python3
"""Read-only checks of the current execution context, not the VM host."""
import ctypes,json,os,socket,subprocess
from pathlib import Path
out={}
for cmd in [['lscpu'],['free','-h'],['df','-h','.'],['uname','-a'],['id'],['sh','-c','command -v perf; command -v nvidia-smi; command -v stress-ng']]:
 p=subprocess.run(cmd,capture_output=True,text=True);out[' '.join(cmd)]={'stdout':p.stdout,'stderr':p.stderr,'rc':p.returncode}
class Attr(ctypes.Structure):
 _fields_=[('type',ctypes.c_uint),('size',ctypes.c_uint),('config',ctypes.c_ulonglong),('period',ctypes.c_ulonglong),('sample_type',ctypes.c_ulonglong),('read_format',ctypes.c_ulonglong),('flags',ctypes.c_ulonglong)]
lib=ctypes.CDLL(None,use_errno=True)
for typ,name in [(0,'cycles'),(1,'cpu-clock')]:
 a=Attr();a.type=typ;a.size=ctypes.sizeof(a);a.flags=(1<<5)|(1<<6)
 fd=lib.syscall(298,ctypes.byref(a),0,-1,-1,0)
 out['perf_event_open_'+name]={'fd':fd,'error':os.strerror(ctypes.get_errno()) if fd<0 else None}
 if fd>=0:os.close(fd)
for host in ['github.com','gitlab.com','archive.ubuntu.com']:
 try:out['dns_'+host]=socket.getaddrinfo(host,443)[0][4][0]
 except OSError as e:out['dns_'+host]=str(e)
try:
 with socket.socket(socket.AF_INET,socket.SOCK_DGRAM) as s:s.bind(('127.0.0.1',0));out['loopback_udp']='ok'
except OSError as e:out['loopback_udp']=str(e)
for p in ['/proc/self/status','/proc/self/cgroup','/proc/sys/kernel/perf_event_paranoid','/proc/mounts']:
 out[p]=Path(p).read_text()
print(json.dumps(out,indent=2))
