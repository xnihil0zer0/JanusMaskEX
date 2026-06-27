#!/usr/bin/env python3
"""ATTACK B -- FAIL-CLOSED COMPLETENESS. Enumerate every setup failure mode and
confirm each RAISES LiveRunnerError (or returns timed_out) and NEVER runs the PoC
in the host netns / with outbound open. The one gap I'm probing: does a TIMEOUT
return a non-raising result that a caller could misread as 'ran but no callback'?"""
import os, sys, tempfile, importlib
sys.path.insert(0, "/tmp/p13_adv_wt")
import ngv2.poc_runner_live as prl
from ngv2.poc_runner_live import run_jailed_poc_with_loopback, LiveRunnerError

def call(wd, poc_body="print('x')\n", **over):
    pp=os.path.join(wd,"poc.py");open(pp,"w").write(poc_body)
    kw=dict(repo_root=None, work_dir=wd, extra_ro=[],
        child_env={"PATH":"/usr/bin:/bin:/usr/local/bin","HOME":"/tmp","LANG":"C.UTF-8"},
        timeout_s=10.0, fs_signature="", callback_env_keys=("NGV2_SSRF_CALLBACK",), poc_path=pp)
    kw.update(over)
    return run_jailed_poc_with_loopback(["python3", pp], **kw)

results=[]
def check(name, fn):
    try:
        r=fn(); results.append((name, "RETURNED", repr(r)[:200]))
    except LiveRunnerError as e:
        results.append((name, "RAISED_LiveRunnerError", str(e)[:140]))
    except Exception as e:
        results.append((name, "RAISED_OTHER:"+type(e).__name__, str(e)[:140]))

with tempfile.TemporaryDirectory() as t:
    # 1. bootstrap module missing -> no sentinel -> must RAISE
    def m1():
        wd=os.path.join(t,"m1");os.makedirs(wd)
        saved=prl._LOOPBACK_BOOTSTRAP_MODULE
        try:
            prl._LOOPBACK_BOOTSTRAP_MODULE="ngv2._NOPE"
            return call(wd)
        finally: prl._LOOPBACK_BOOTSTRAP_MODULE=saved
    check("bootstrap_module_missing", m1)

    # 2. CAP_NET_ADMIN stripped -> lo cannot come up -> no sentinel -> RAISE
    def m2():
        wd=os.path.join(t,"m2");os.makedirs(wd)
        saved=prl.build_detonation_jail_argv
        def strip(cmd,*,repo_root,work_dir,extra_ro=(),shared_loopback_netns=False):
            a=saved(cmd,repo_root=repo_root,work_dir=work_dir,extra_ro=extra_ro,shared_loopback_netns=shared_loopback_netns)
            o=[];i=0
            while i<len(a):
                if a[i]=="--cap-add": i+=2; continue
                o.append(a[i]); i+=1
            return o
        try:
            prl.build_detonation_jail_argv=strip
            return call(wd)
        finally: prl.build_detonation_jail_argv=saved
    check("cap_net_admin_stripped", m2)

    # 3. bwrap missing -> build_detonation_jail_argv raises LiveRunnerError up front
    def m3():
        wd=os.path.join(t,"m3");os.makedirs(wd)
        saved=prl.shutil.which
        try:
            prl.shutil.which=lambda n: None if n=="bwrap" else saved(n)
            return call(wd)
        finally: prl.shutil.which=saved
    check("bwrap_missing", m3)

    # 4. PoC times out (bootstrap never returns sentinel because PoC hangs PAST the
    #    bootstrap's own timeout but WITHIN the parent's timeout+5). The bootstrap
    #    runs the PoC with its OWN timeout, then emits sentinel with hits anyway.
    def m4():
        wd=os.path.join(t,"m4");os.makedirs(wd)
        return call(wd, poc_body="import time; time.sleep(30)\n", timeout_s=3.0)
    check("poc_hangs_within_parent_timeout", m4)

    # 5. bootstrap itself hangs forever (parent timeout fires) -> returns timed_out=True,
    #    hits=[] -- is that a SAFE non-confirm? (no host-netns run happened)
    def m5():
        wd=os.path.join(t,"m5");os.makedirs(wd)
        saved=prl._LOOPBACK_BOOTSTRAP_MODULE
        # point at a module that sleeps forever before emitting sentinel
        hang=os.path.join(t,"hangmod.py")
        # we can't easily inject a hanging -m module; instead simulate via a fake argv
        # that runs `python3 -c "import time;time.sleep(60)"` as the jail's first proc.
        savedargv=prl.build_detonation_jail_argv
        def hangargv(cmd,*,repo_root,work_dir,extra_ro=(),shared_loopback_netns=False):
            a=savedargv(cmd,repo_root=repo_root,work_dir=work_dir,extra_ro=extra_ro,shared_loopback_netns=shared_loopback_netns)
            # replace the trailing PoC cmd (after '--') with a sleeper
            idx=a.index("--")
            return a[:idx+1]+["python3","-c","import time;time.sleep(60)"]
        try:
            prl.build_detonation_jail_argv=hangargv
            return call(wd, timeout_s=3.0)
        finally:
            prl.build_detonation_jail_argv=savedargv
    check("bootstrap_hangs_parent_timeout", m5)

for n,outcome,detail in results:
    print(f"[{outcome}] {n}: {detail}")
