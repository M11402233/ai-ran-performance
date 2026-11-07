"""Deterministic CPU-only arithmetic load; not stress-ng or AI."""
import argparse, time, json
p=argparse.ArgumentParser();p.add_argument('--duty',type=float,default=1);a=p.parse_args()
x=1;n=0;t=time.monotonic()
try:
 while True:
  start=time.monotonic()
  while time.monotonic()-start < .05*a.duty:
   for _ in range(2000):x=(1664525*x+1013904223)&0xffffffff
   n+=2000
  time.sleep(max(0,.05-(time.monotonic()-start)))
except KeyboardInterrupt:
 print(json.dumps({'iterations':n,'seconds':time.monotonic()-t,'duty':a.duty}),flush=True)
