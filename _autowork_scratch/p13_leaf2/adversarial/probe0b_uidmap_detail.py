#!/usr/bin/env python3
"""PROBE 0b: WHY does the parent-fork uid_map write fail, and does bwrap's own
--unshare-user path succeed? Distinguish 'host already in userns' (dev's claim)
from other causes. Also test the setgroups-ordering variant."""
import ctypes, os, errno, subprocess

CLONE_NEWUSER = 0x10000000
CLONE_NEWNET  = 0x40000000
libc = ctypes.CDLL("libc.so.6", use_errno=True)

def try_variant(name, write_setgroups, map_line):
    r, w = os.pipe()
    pid = os.fork()
    if pid == 0:
        os.close(r)
        rc = libc.unshare(CLONE_NEWUSER | CLONE_NEWNET)
        if rc != 0:
            os.write(w, f"unshare_fail {ctypes.get_errno()}".encode()); os._exit(10)
        if write_setgroups:
            try:
                with open("/proc/self/setgroups","w") as f: f.write("deny")
            except OSError as ex:
                os.write(w, f"setgroups_fail {ex.errno}".encode()); os._exit(11)
        try:
            with open("/proc/self/uid_map","w") as f: f.write(map_line)
            os.write(w, b"UIDMAP_OK")
        except OSError as ex:
            os.write(w, f"uidmap_fail errno={ex.errno} {errno.errorcode.get(ex.errno)}".encode())
        os._exit(0)
    os.close(w)
    msg = os.read(r,256).decode(); os.waitpid(pid,0)
    print(f"  {name}: {msg}")

print("== variants of the parent-fork uid_map write ==")
try_variant("setgroups=deny, '0 <uid> 1'", True, f"0 {os.getuid()} 1")
try_variant("no setgroups,   '0 <uid> 1'", False, f"0 {os.getuid()} 1")
try_variant("setgroups=deny, '0 0 4294967295' (full)", True, "0 0 4294967295")

print("\n== does bwrap --unshare-user actually work here? ==")
out = subprocess.run(["bwrap","--unshare-user","--uid","0","--gid","0","--unshare-net",
                      "--ro-bind","/usr","/usr","--ro-bind","/bin","/bin","--ro-bind","/lib","/lib",
                      "--ro-bind","/lib64","/lib64","--proc","/proc","--dev","/dev",
                      "--","/bin/sh","-c","id; cat /proc/self/uid_map"],
                     capture_output=True, text=True, timeout=15)
print("  bwrap rc:", out.returncode)
print("  bwrap stdout:", out.stdout.strip())
print("  bwrap stderr:", out.stderr.strip()[:300])
