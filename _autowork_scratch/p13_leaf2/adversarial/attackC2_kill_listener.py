#!/usr/bin/env python3
"""ATTACK C2 -- can the PoC suppress a REAL callback by killing the listener
(false-negative DoS), and can it read the parent's open FDs (the bound listener
socket / nonce)? This drives the FULL seam to see if the verdict is subvertible."""
import os, sys, tempfile
sys.path.insert(0, "/tmp/p13_adv_wt")
from ngv2.poc_runner_live import run_jailed_poc_with_loopback

# PoC that: (1) reads parent fds/cmdline to learn the listener port+nonce, then
# (2) KILLS the parent (listener) BEFORE doing its own legit callback, to test
# whether it can suppress the channel. Also tries to read the parent's fd symlinks.
POC = r'''
import os, signal, glob, time, urllib.request
out=[]
def log(*a): out.append(" ".join(str(x) for x in a))
ppid=os.getppid()
# Inspect parent's open fds (the listener's bound socket lives here)
fds=[]
try:
    for f in os.listdir("/proc/%d/fd"%ppid):
        try: fds.append(os.readlink("/proc/%d/fd/%s"%(ppid,f)))
        except OSError: fds.append("?")
    log("PARENT_FDS", fds)
except OSError as e: log("PARENT_FDS_ERR", e.errno)
# Read parent cmdline (may contain the config path -> nonce/port leak)
try:
    log("PARENT_CMDLINE", open("/proc/%d/cmdline"%ppid,"rb").read().replace(b"\0",b" ").decode()[:200])
except OSError as e: log("PARENT_CMDLINE_ERR", e.errno)
# Read parent's environ (could contain the callback URL with the nonce)
try:
    env=open("/proc/%d/environ"%ppid,"rb").read().decode("utf-8","replace")
    log("PARENT_ENVIRON_READABLE", "NGV2" in env, len(env))
except OSError as e: log("PARENT_ENVIRON_ERR", e.errno)
# Now KILL the listener (parent) to suppress the channel
try:
    os.kill(ppid, signal.SIGKILL)
    log("KILLED_PARENT", "sent SIGKILL")
except OSError as e: log("KILL_FAIL", e.errno)
print("__ADV_C2__")
for l in out: print(l)
'''
with tempfile.TemporaryDirectory(prefix="advC2-") as tmp:
    wd=os.path.join(tmp,"w");os.makedirs(wd)
    pp=os.path.join(wd,"poc.py");open(pp,"w").write(POC)
    try:
        res=run_jailed_poc_with_loopback(["python3",pp],repo_root=None,work_dir=wd,extra_ro=[],
            child_env={"PATH":"/usr/bin:/bin:/usr/local/bin","HOME":"/tmp","LANG":"C.UTF-8"},
            timeout_s=20.0,fs_signature="",callback_env_keys=("NGV2_SSRF_CALLBACK",),poc_path=pp)
        print("RESULT:", res)
    except Exception as e:
        print("RAISED:", type(e).__name__, str(e)[:200])
