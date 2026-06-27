#!/usr/bin/env python3
"""ATTACK E2 -- does running the PoC as root-in-userns (--uid 0) on the shared path
broaden file access vs the legacy path (host uid)? The ro-binds are identical, but
uid 0 in the userns maps to the HOST uid (1000) for file-permission checks, so it
should NOT read root-only host files. Verify against /etc/shadow and host-only files."""
import os, sys, tempfile
sys.path.insert(0, "/tmp/p13_adv_wt")
from ngv2.poc_runner_live import run_jailed_poc_with_loopback, build_detonation_jail_argv
import subprocess

POC = r'''
import os
out=[]
def t(p):
    try:
        d=open(p,"rb").read(32); out.append("READ_OK %s (%d bytes)"%(p,len(d)))
    except OSError as e: out.append("READ_FAIL %s errno=%d"%(p,e.errno))
print("UID", os.getuid(), "EUID", os.geteuid())
# root-only host files (should be DENIED -- uid0-in-userns maps to host uid 1000)
t("/etc/shadow")
t("/etc/sudoers")
# host user creds (NOT bound, so should be absent entirely)
t(os.path.expanduser("~/.gemini"))
t("/home/xnihil0zer0/.claude.json")
# can we even SEE /home? (not in ro-binds)
out.append("HOME_LIST %s"%(os.listdir("/home") if os.path.exists("/home") else "NO /home"))
print("__E2__")
for l in out: print(l)
'''
with tempfile.TemporaryDirectory() as tmp:
    wd=os.path.join(tmp,"w");os.makedirs(wd)
    pp=os.path.join(wd,"poc.py");open(pp,"w").write(POC)
    res=run_jailed_poc_with_loopback(["python3",pp],repo_root=None,work_dir=wd,extra_ro=[],
        child_env={"PATH":"/usr/bin:/bin:/usr/local/bin","HOME":"/tmp","LANG":"C.UTF-8"},
        timeout_s=20.0,fs_signature="",callback_env_keys=("NGV2_SSRF_CALLBACK",),poc_path=pp)
    print(res.get("stdout"))
    print("STDERR:", (res.get("stderr") or "")[:300])
