#!/usr/bin/env python3
"""PROBE 0: Is the DESIGN.md parent-fork model (unshare(CLONE_NEWUSER|CLONE_NEWNET)
+ write uid_map) actually infeasible on THIS host? The whole deviation rationale
(bwrap-owns-userns instead) rests on the claim that the host is already inside a
userns so a nested uid_map write returns EPERM."""
import ctypes, os, sys, errno

CLONE_NEWUSER = 0x10000000
CLONE_NEWNET  = 0x40000000

print("== context ==")
print("uid_map:", open("/proc/self/uid_map").read().strip())
print("euid:", os.geteuid())

libc = ctypes.CDLL("libc.so.6", use_errno=True)

# Fork a child; in child, unshare userns+netns, then try to write uid_map (the
# DESIGN.md §4 mechanism). Report whether it succeeds.
r, w = os.pipe()
pid = os.fork()
if pid == 0:
    os.close(r)
    rc = libc.unshare(CLONE_NEWUSER | CLONE_NEWNET)
    if rc != 0:
        e = ctypes.get_errno()
        os.write(w, f"UNSHARE_FAIL errno={e} {errno.errorcode.get(e)}".encode())
        os._exit(10)
    # write setgroups deny + uid_map/gid_map (the design's mechanism)
    try:
        with open("/proc/self/setgroups", "w") as f:
            f.write("deny")
    except OSError as ex:
        os.write(w, f"SETGROUPS_FAIL {ex}".encode()); os._exit(11)
    try:
        with open("/proc/self/uid_map", "w") as f:
            f.write(f"0 {os.getuid()} 1")
        with open("/proc/self/gid_map", "w") as f:
            f.write(f"0 {os.getgid()} 1")
    except OSError as ex:
        os.write(w, f"UIDMAP_WRITE_FAIL errno={ex.errno} {errno.errorcode.get(ex.errno)} {ex}".encode())
        os._exit(12)
    # success: we are root-in-userns with a fresh netns
    os.write(w, f"PARENTFORK_OK euid={os.geteuid()} netns_ok=1".encode())
    os._exit(0)
else:
    os.close(w)
    msg = os.read(r, 4096).decode()
    _, st = os.waitpid(pid, 0)
    print("CHILD_MSG:", msg)
    print("CHILD_EXIT:", os.waitstatus_to_exitcode(st))
