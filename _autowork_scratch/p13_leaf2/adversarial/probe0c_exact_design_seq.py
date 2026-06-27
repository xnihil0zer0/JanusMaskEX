#!/usr/bin/env python3
"""PROBE 0c: the EXACT DESIGN.md §4 sequence: unshare(NEWUSER|NEWNET) -> setgroups deny
-> uid_map -> gid_map -> then bring lo up. Pinpoint which step fails."""
import ctypes, os, errno, fcntl, socket, struct
CLONE_NEWUSER=0x10000000; CLONE_NEWNET=0x40000000
libc=ctypes.CDLL("libc.so.6", use_errno=True)
r,w=os.pipe()
pid=os.fork()
if pid==0:
    os.close(r)
    def emit(s): os.write(w, s.encode())
    if libc.unshare(CLONE_NEWUSER|CLONE_NEWNET)!=0:
        emit(f"STEP unshare FAIL {ctypes.get_errno()}"); os._exit(1)
    emit("unshare=OK; ")
    try:
        open("/proc/self/setgroups","w").write("deny"); emit("setgroups=OK; ")
    except OSError as e: emit(f"setgroups FAIL {e.errno}; ")
    try:
        open("/proc/self/uid_map","w").write(f"0 {os.getuid()} 1"); emit("uid_map=OK; ")
    except OSError as e: emit(f"uid_map FAIL {e.errno}; "); os._exit(2)
    try:
        open("/proc/self/gid_map","w").write(f"0 {os.getgid()} 1"); emit("gid_map=OK; ")
    except OSError as e: emit(f"gid_map FAIL {e.errno}; ")
    emit(f"euid={os.geteuid()}; ")
    # try bring lo up (needs CAP_NET_ADMIN in the userns)
    s=socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        ifr=struct.pack("16sh", b"lo", 0)
        res=fcntl.ioctl(s.fileno(), 0x8913, ifr)
        flags=struct.unpack("16sh",res)[1] | 0x1 | 0x40
        fcntl.ioctl(s.fileno(), 0x8914, struct.pack("16sh", b"lo", flags))
        emit("LO_UP=OK")
    except OSError as e:
        emit(f"LO_UP FAIL {e.errno} {errno.errorcode.get(e.errno)}")
    os._exit(0)
os.close(w)
print("DESIGN_SEQ:", os.read(r,1024).decode())
os.waitpid(pid,0)
