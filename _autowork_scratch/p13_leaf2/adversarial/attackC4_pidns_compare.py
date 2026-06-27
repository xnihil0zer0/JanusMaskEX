#!/usr/bin/env python3
"""ATTACK C4 -- quantify the --unshare-pid REGRESSION. Run the SAME enumeration PoC
through (legacy --unshare-pid path) vs (shared-loopback path, pid-ns shared) and
diff what host process info each leaks."""
import os, sys, tempfile, subprocess
sys.path.insert(0, "/tmp/p13_adv_wt")
from ngv2.poc_runner_live import build_detonation_jail_argv

POC = r'''
import os
pids=[p for p in os.listdir("/proc") if p.isdigit()]
print("PIDNS", os.readlink("/proc/self/ns/pid"))
print("VISIBLE_PIDS", len(pids))
# is pid 1 the host init or the jail's first proc?
try: print("PID1_CMDLINE", open("/proc/1/cmdline","rb").read().replace(b"\0",b" ").decode()[:60])
except OSError as e: print("PID1_ERR", e.errno)
# can we signal pid 1?
try: os.kill(1,0); print("CAN_SIGNAL_PID1 YES")
except OSError as e: print("CAN_SIGNAL_PID1 NO", e.errno)
'''
def run(shared):
    with tempfile.TemporaryDirectory() as wd:
        pp=os.path.join(wd,"poc.py"); open(pp,"w").write(POC)
        argv=build_detonation_jail_argv(["python3",pp],repo_root=None,work_dir=wd,extra_ro=[],
                                        shared_loopback_netns=shared)
        env={"PATH":"/usr/bin:/bin:/usr/local/bin","HOME":"/tmp","LANG":"C.UTF-8"}
        r=subprocess.run(argv,cwd=wd,env=env,capture_output=True,text=True,timeout=20)
        return r.stdout.strip(), r.stderr.strip()[:200]

print("=== LEGACY PATH (--unshare-pid present) ===")
o,e=run(False); print(o); 
if e: print("ERR:",e)
print("\n=== SHARED-LOOPBACK PATH (--unshare-pid DROPPED) ===")
o,e=run(True); print(o)
if e: print("ERR:",e)
print("\nHOST init pid-ns for reference:", os.readlink("/proc/self/ns/pid"))
