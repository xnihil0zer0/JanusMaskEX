#!/usr/bin/env python3
"""ATTACK E -- REGRESSION. (1) FS-oracle confirms a path-write CWE with a CLEAN diff
(the _loopback_cfg.json artifact must NOT pollute it). (2) NO new credential binds
(~/.gemini/~/.claude/$HOME) in the bwrap argv. (3) host parent network preserved."""
import os, sys, socket, tempfile
sys.path.insert(0, "/tmp/p13_adv_wt")
import ngv2.poc_runner_live as prl
from ngv2.poc_runner_live import build_detonation_jail_argv
from ngv2.workers._runner import _make_detonation_seam

# (1) FS-oracle clean diff: confirm the loopback config file does NOT appear in diff.
print("=== E1: FS-snapshot oracle, config artifact excluded ===")
seam=_make_detonation_seam()
poc="print('VULNERABLE')\nopen('real_effect','w').write('x')\n"
finding={"id":"F-e1","cwe":"CWE-78","expected_fs_signature":"A real_effect"}
r=seam(poc=poc, finding=finding)
diff=r.get("fs_snapshot_diff") or ""
print("verdict:", r.get("verdict"), "| diff:", repr(diff))
clean = ("_loopback_cfg.json" not in diff) and (prl.LOOPBACK_CFG_FILENAME not in diff) and ("real_effect" in diff)
print("CLEAN_DIFF (no cfg pollution, real effect present):", clean)

# (2) credential bind audit: dump the EXACT bwrap argv for the shared-loopback path.
print("\n=== E2: bwrap argv credential-bind audit (shared-loopback path) ===")
with tempfile.TemporaryDirectory() as wd:
    argv = build_detonation_jail_argv(["python3","-c","pass"], repo_root=None, work_dir=wd,
                                      extra_ro=[], shared_loopback_netns=True)
    print("ARGV:", " ".join(argv))
    binds=[argv[i+1] for i in range(len(argv)-1) if argv[i] in ("--bind","--ro-bind")]
    print("BIND TARGETS:", binds)
    cred_leak = any(("gemini" in b.lower() or ".claude" in b.lower() or b==os.path.expanduser("~")) for b in binds)
    home_bind = any(b==os.path.expanduser("~") for b in binds)
    print("CREDENTIAL_OR_HOME_BIND_PRESENT:", cred_leak, "| home_bind:", home_bind)
    # Compare to legacy path -- bind set must be identical except the net flags.
    argv_legacy = build_detonation_jail_argv(["python3","-c","pass"], repo_root=None, work_dir=wd, extra_ro=[])
    binds_legacy=[argv_legacy[i+1] for i in range(len(argv_legacy)-1) if argv_legacy[i] in ("--bind","--ro-bind")]
    print("BINDS IDENTICAL TO LEGACY:", sorted(binds)==sorted(binds_legacy))

# (3) host parent network preserved AFTER a detonation (pip fallback needs it).
print("\n=== E3: host parent network preserved ===")
def host_net_ok():
    try:
        s=socket.socket(); s.settimeout(2); s.connect(("1.1.1.1",80)); s.close(); return True
    except OSError: 
        # may be offline; check route table presence instead
        try: return bool(open("/proc/net/route").read().count("\n")>1)
        except OSError: return None
before=host_net_ok()
seam(poc="print('VULNERABLE')\nopen('m','w').write('x')\n",
     finding={"id":"F-e3","cwe":"CWE-78","expected_fs_signature":"A m"})
after=host_net_ok()
print("PARENT_NET_BEFORE:", before, "AFTER:", after, "| PRESERVED:", before==after)
