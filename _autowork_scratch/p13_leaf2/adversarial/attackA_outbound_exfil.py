#!/usr/bin/env python3
"""ATTACK A -- OUTBOUND EXFIL (#1 invariant). Runs a REAL jailed PoC on the
shared-loopback-netns path (CAP_NET_ADMIN held in the jail's OWN userns) and tries
EVERY way to reach off-host or other host loopback services. Pass = all blocked."""
import os, sys, tempfile
sys.path.insert(0, "/tmp/p13_adv_wt")
from ngv2.poc_runner_live import run_jailed_poc_with_loopback

# The adversarial PoC. It runs WITH CAP_NET_ADMIN inside the jail's userns/netns.
POC = r'''
import socket, subprocess, os, struct, fcntl, errno
out = []
def log(*a): out.append(" ".join(str(x) for x in a))

# 0. Enumerate interfaces in the jail (pure-python via /sys, plus ioctl SIOCGIFCONF)
try:
    ifaces = sorted(os.listdir("/sys/class/net"))
    log("IFACES", ifaces)
except Exception as e:
    log("IFACES_ERR", e)

# Confirm we hold CAP_NET_ADMIN by reading /proc/self/status
try:
    for line in open("/proc/self/status"):
        if line.startswith("CapEff") or line.startswith("Uid") or line.startswith("Gid"):
            log("STATUS", line.strip())
except Exception as e: log("STATUS_ERR", e)

# 1. raw-IP outbound to RFC-5737 TEST-NET and a real public IP (expect failure)
for ip in ("192.0.2.1", "1.1.1.1", "8.8.8.8"):
    try:
        s=socket.socket(); s.settimeout(3); s.connect((ip,80)); s.close()
        log("OUTBOUND_OPEN", ip)
    except OSError as e:
        log("OUTBOUND_BLOCKED", ip, type(e).__name__, e.errno)

# 2. Try to ADD a default route via CAP_NET_ADMIN (netlink RTM_NEWROUTE).
#    If we could add a route to a gateway, exfil would open. Expect EPERM/ENETUNREACH.
try:
    import socket as sk
    nl = sk.socket(sk.AF_NETLINK, sk.SOCK_RAW, 0)  # NETLINK_ROUTE=0
    log("NETLINK_SOCKET", "created")
    nl.close()
except OSError as e:
    log("NETLINK_SOCKET_ERR", type(e).__name__, e.errno)

# 3. Try to CREATE a dummy/veth interface via `ip` if present (would need a peer in host netns)
for cmd in (["ip","link","add","dummy0","type","dummy"],
            ["ip","link","add","veth0","type","veth","peer","name","veth1"],
            ["ip","route","add","default","via","192.0.2.254"]):
    try:
        r=subprocess.run(cmd, capture_output=True, text=True, timeout=5)
        log("IPCMD", " ".join(cmd), "rc=%d"%r.returncode, (r.stderr.strip() or r.stdout.strip())[:120])
    except FileNotFoundError:
        log("IPCMD_NOBIN", cmd[0])
    except Exception as e:
        log("IPCMD_ERR", cmd[0], type(e).__name__, str(e)[:80])

# 4. Raw socket (needs CAP_NET_RAW; we only asked for NET_ADMIN). Try anyway.
try:
    rs = socket.socket(socket.AF_INET, socket.SOCK_RAW, socket.IPPROTO_TCP)
    log("RAW_SOCKET_OPEN")
    rs.close()
except OSError as e:
    log("RAW_SOCKET_BLOCKED", type(e).__name__, e.errno)

# 5. Try to reach a host loopback service. Pick a port likely open on the HOST
#    (e.g. 22 ssh, 631 cups). In a FRESH netns these are unreachable; if the jail
#    were sharing the HOST netns, 127.0.0.1:<svc> would connect.
for p in (22, 631, 5432, 3306, 8080):
    try:
        s=socket.socket(); s.settimeout(1); s.connect(("127.0.0.1",p)); s.close()
        log("HOST_LOOPBACK_REACHED", p)
    except OSError as e:
        log("HOST_LOOPBACK_BLOCKED", p, e.errno)

# 6. Try abstract-namespace unix socket to see other host services (shared netns? no)
print("__ADV_A__")
for ln in out: print(ln)
'''

with tempfile.TemporaryDirectory(prefix="advA-") as tmp:
    wd = os.path.join(tmp, "w"); os.makedirs(wd)
    pp = os.path.join(wd, "poc.py")
    open(pp,"w").write(POC)
    res = run_jailed_poc_with_loopback(["python3", pp], repo_root=None, work_dir=wd,
            extra_ro=[], child_env={"PATH":"/usr/bin:/bin:/usr/local/bin","HOME":"/tmp",
            "LANG":"C.UTF-8","PYTHONDONTWRITEBYTECODE":"1"}, timeout_s=30.0,
            fs_signature="", callback_env_keys=("NGV2_SSRF_CALLBACK",), poc_path=pp)
    print("=== JAILED POC STDOUT ===")
    print(res.get("stdout"))
    print("=== STDERR ===")
    print((res.get("stderr") or "")[:1000])
    print("=== exit_code:", res.get("exit_code"), "hits:", res.get("hits"))
