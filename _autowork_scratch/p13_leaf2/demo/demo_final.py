#!/usr/bin/env python3
"""P1.3 leaf-2 FINAL DEMONSTRATION (post --unshare-pid fix).

Exercises the REAL production shared-loopback-netns detonation path
(``ngv2.poc_runner_live.run_jailed_poc_with_loopback`` /
``ngv2.workers._runner._make_detonation_seam``) -- NO injected mock -- and asserts
ALL of (a)-(f). A pass here means a real bwrap-jailed PoC actually talks to the
in-netns listener while outbound stays blocked AND the private pid-ns isolates the
jail from host processes (the fix being verified).

  (a) POSITIVE       : real jailed PoC fetches the nonce callback -> hit in listener,
                       absent from a no-callback baseline.
  (b) OUTBOUND BLOCKED: raw-IP connect to TEST-NET 192.0.2.1:80 AND 1.1.1.1:80 fails.
  (c) FS-ORACLE       : a path-write CWE still confirms via the FS snapshot diff;
                        no _loopback_cfg.json pollution in the diff.
  (d) NO-CALLBACK NEG : a PoC that calls back with the WRONG nonce does NOT confirm.
  (e) FAIL-CLOSED     : a forced namespace/listener setup failure raises
                        LiveRunnerError, and the FINAL argv never contains --share-net.
  (f) PID-NS ISOLATION: with --unshare-pid retained, the jailed PoC sees only a SMALL
                        number of PIDs (private pid-ns), CANNOT find a host sentinel by
                        cmdline, and CANNOT signal an arbitrary host PID.

Run:  PYTHONPATH=<ngv2-parent> python3 demo_final.py
"""
from __future__ import annotations
import os
import signal
import subprocess
import sys
import tempfile
import time
import traceback

import ngv2.poc_runner_live as prl
from ngv2.poc_runner_live import (
    LiveRunnerError,
    bwrap_available,
    build_detonation_jail_argv,
    run_jailed_poc_with_loopback,
)

RESULTS: list[tuple[str, bool, str]] = []


def record(name: str, ok: bool, detail: str = "") -> None:
    RESULTS.append((name, ok, detail))
    flag = "PASS" if ok else "FAIL"
    print(f"[{flag}] {name}: {detail}")


def _write_poc(work_dir: str, body: str, name: str = "poc.py") -> str:
    p = os.path.join(work_dir, name)
    with open(p, "w", encoding="utf-8") as fh:
        fh.write(body)
    return p


def _child_env() -> dict:
    return {
        "PATH": "/usr/bin:/bin:/usr/local/bin",
        "HOME": "/tmp",
        "LANG": "C.UTF-8",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


# --------------------------------------------------------------------------- (a)+(b)
def assertion_a_b_positive_and_outbound(tmp: str) -> None:
    nonce = "ssrf_F_demo_pos"
    body = (
        "import urllib.request, socket\n"
        "try:\n"
        "    urllib.request.urlopen('http://127.0.0.1:<<PORT>>/" + nonce + "', timeout=4).read()\n"
        "    print('LOOPBACK_OK')\n"
        "except Exception as e:\n"
        "    print('LOOPBACK_ERR', e)\n"
        "for ip in ('192.0.2.1', '1.1.1.1'):\n"
        "    try:\n"
        "        s = socket.socket(); s.settimeout(3); s.connect((ip, 80)); s.close()\n"
        "        print('OUTBOUND_OPEN', ip)\n"
        "    except OSError as e:\n"
        "        print('OUTBOUND_BLOCKED', ip, type(e).__name__)\n"
    )
    work_dir = os.path.join(tmp, "pos")
    os.makedirs(work_dir, exist_ok=True)
    poc_path = _write_poc(work_dir, body)
    res = run_jailed_poc_with_loopback(
        ["python3", poc_path], repo_root=None, work_dir=work_dir, extra_ro=[],
        child_env=_child_env(), timeout_s=25.0, fs_signature="",
        callback_env_keys=("NGV2_SSRF_CALLBACK",), poc_path=poc_path,
    )
    hits = res.get("hits") or []
    stdout = res.get("stdout") or ""
    nonce_hit = any(nonce in str(h) for h in hits)
    record("(a) POSITIVE: nonce callback reaches in-netns listener",
           nonce_hit and "LOOPBACK_OK" in stdout, f"hits={hits} stdout={stdout!r}")
    outbound_open = "OUTBOUND_OPEN" in stdout
    both_blocked = stdout.count("OUTBOUND_BLOCKED") == 2 and not outbound_open
    record("(b) OUTBOUND BLOCKED: raw-IP 192.0.2.1 & 1.1.1.1 refused",
           both_blocked, f"stdout={stdout!r}")

    base_dir = os.path.join(tmp, "baseline")
    os.makedirs(base_dir, exist_ok=True)
    base_path = _write_poc(base_dir, "print('NO_CALLBACK')\n")
    base = run_jailed_poc_with_loopback(
        ["python3", base_path], repo_root=None, work_dir=base_dir, extra_ro=[],
        child_env=_child_env(), timeout_s=20.0, fs_signature="",
        callback_env_keys=("NGV2_SSRF_CALLBACK",), poc_path=base_path,
    )
    base_hits = base.get("hits") or []
    record("(a) BASELINE: nonce absent when PoC does not call back",
           not any(nonce in str(h) for h in base_hits), f"baseline_hits={base_hits}")


# --------------------------------------------------------------------------- (c)
def assertion_c_fs_oracle(tmp: str) -> None:
    from ngv2.workers._runner import _make_detonation_seam
    seam = _make_detonation_seam()
    if seam is None:
        record("(c) FS-ORACLE no-regression", False, "seam unavailable")
        return
    poc = "print('VULNERABLE')\nopen('pwned_marker', 'w').write('x')\n"
    finding = {"id": "F-demo-rce", "cwe": "CWE-78", "expected_fs_signature": "A pwned_marker"}
    res = seam(poc=poc, finding=finding)
    diff = res.get("fs_snapshot_diff") or ""
    no_pollution = "_loopback_cfg.json" not in diff
    ok = (res.get("success") is True and res.get("verdict") == "confirmed"
          and "A pwned_marker" in diff and no_pollution)
    record("(c) FS-ORACLE no-regression: path-write CWE confirms, no cfg pollution",
           ok, f"verdict={res.get('verdict')} diff={diff!r} success={res.get('success')}")


# --------------------------------------------------------------------------- (d)
def assertion_d_no_callback_negative(tmp: str) -> None:
    from ngv2.workers._runner import _make_detonation_seam
    seam = _make_detonation_seam()
    if seam is None:
        record("(d) NO-CALLBACK negative", False, "seam unavailable")
        return
    poc = (
        "import urllib.request\n"
        "try:\n"
        "    urllib.request.urlopen('http://127.0.0.1:<<PORT>>/totally_wrong_path', timeout=4).read()\n"
        "except Exception:\n"
        "    pass\n"
    )
    finding = {"id": "F-demo-neg", "cwe": "CWE-918"}
    res = seam(poc=poc, finding=finding)
    ssrf = res.get("ssrf_channel") or {}
    ok = (ssrf.get("success") is False and res.get("success") is False
          and res.get("reproduced") is False)
    record("(d) NO-CALLBACK negative: wrong nonce does NOT confirm via ssrf_channel",
           ok, f"ssrf_channel={ssrf} success={res.get('success')}")


# --------------------------------------------------------------------------- (e)
def assertion_e_fail_closed(tmp: str) -> None:
    import ngv2.poc_runner_live as m

    # (e1) bootstrap module missing -> no sentinel -> raise.
    work_dir = os.path.join(tmp, "failclosed")
    os.makedirs(work_dir, exist_ok=True)
    poc_path = _write_poc(work_dir, "print('should never matter')\n")
    saved = m._LOOPBACK_BOOTSTRAP_MODULE
    raised = False
    err_msg = ""
    try:
        m._LOOPBACK_BOOTSTRAP_MODULE = "ngv2._loopback_netns_DOES_NOT_EXIST"
        try:
            run_jailed_poc_with_loopback(
                ["python3", poc_path], repo_root=None, work_dir=work_dir, extra_ro=[],
                child_env=_child_env(), timeout_s=15.0, fs_signature="",
                callback_env_keys=("NGV2_SSRF_CALLBACK",), poc_path=poc_path)
        except LiveRunnerError as e:
            raised = True
            err_msg = str(e)
        except Exception as e:
            err_msg = f"unexpected {type(e).__name__}: {e}"
    finally:
        m._LOOPBACK_BOOTSTRAP_MODULE = saved
    record("(e) FAIL-CLOSED: setup failure raises LiveRunnerError, no host-netns fallback",
           raised, f"raised={raised} msg={err_msg[:160]!r}")

    # (e-argv) The production shared-loopback argv NEVER contains --share-net / share_net.
    sample_dir = os.path.join(tmp, "argv_grep")
    os.makedirs(sample_dir, exist_ok=True)
    sp = _write_poc(sample_dir, "print('x')\n")
    argv = build_detonation_jail_argv(["python3", sp], repo_root=None,
                                      work_dir=sample_dir, extra_ro=[],
                                      shared_loopback_netns=True)
    argv_str = " ".join(argv)
    no_share = ("--share-net" not in argv) and ("share_net" not in argv_str)
    # Also grep the live-runner source for any --share-net emission.
    import inspect
    src = inspect.getsource(m)
    src_clean = "--share-net" not in src and "'--share-net'" not in src
    record("(e) NO --share-net in final argv or source",
           no_share and src_clean,
           f"argv_has_share_net={'--share-net' in argv} src_has_share_net={not src_clean} argv_head={argv[:13]}")

    # (e2) lo cannot come up (CAP_NET_ADMIN stripped) -> no sentinel -> raise.
    work_dir2 = os.path.join(tmp, "failclosed_nocap")
    os.makedirs(work_dir2, exist_ok=True)
    poc2 = _write_poc(work_dir2, "print('x')\n")
    saved_argv = m.build_detonation_jail_argv
    raised2 = False
    msg2 = ""

    def _argv_without_cap(cmd, *, repo_root, work_dir, extra_ro=(), shared_loopback_netns=False):
        argv = saved_argv(cmd, repo_root=repo_root, work_dir=work_dir, extra_ro=extra_ro,
                          shared_loopback_netns=shared_loopback_netns)
        out, i = [], 0
        while i < len(argv):
            if argv[i] == "--cap-add" and i + 1 < len(argv):
                i += 2
                continue
            out.append(argv[i]); i += 1
        return out

    try:
        m.build_detonation_jail_argv = _argv_without_cap
        try:
            run_jailed_poc_with_loopback(
                ["python3", poc2], repo_root=None, work_dir=work_dir2, extra_ro=[],
                child_env=_child_env(), timeout_s=15.0, fs_signature="",
                callback_env_keys=("NGV2_SSRF_CALLBACK",), poc_path=poc2)
        except LiveRunnerError as e:
            raised2 = True; msg2 = str(e)
        except Exception as e:
            msg2 = f"unexpected {type(e).__name__}: {e}"
    finally:
        m.build_detonation_jail_argv = saved_argv
    record("(e2) FAIL-CLOSED: lo cannot come up (no CAP_NET_ADMIN) -> raises, no fallback",
           raised2, f"raised={raised2} msg={msg2[:160]!r}")


# --------------------------------------------------------------------------- (f) NEW
def assertion_f_pidns_isolation(tmp: str) -> None:
    """The fix being verified. Spawn a host sentinel process with a unique cmdline.
    Assert the jailed PoC (i) sees a SMALL number of PIDs (private pid-ns), (ii) cannot
    find the sentinel by cmdline, (iii) cannot signal an arbitrary host PID."""
    sentinel_tag = "P13L2_SENTINEL_NONCE_7f3a"
    # A host process with a unique, greppable cmdline.
    sentinel = subprocess.Popen(["sleep", "9999", sentinel_tag],
                                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    try:
        time.sleep(0.3)
        host_pid = sentinel.pid
        host_total = len([p for p in os.listdir("/proc") if p.isdigit()])
        body = (
            "import os, glob\n"
            "out = []\n"
            "pids = [p for p in os.listdir('/proc') if p.isdigit()]\n"
            "out.append('VISIBLE_PIDS ' + str(len(pids)))\n"
            "out.append('MY_PIDNS ' + os.readlink('/proc/self/ns/pid'))\n"
            "# search for the host sentinel by cmdline\n"
            "found = False\n"
            "for p in pids:\n"
            "    try:\n"
            "        cl = open('/proc/' + p + '/cmdline','rb').read().replace(b'\\x00', b' ').decode('utf-8','replace')\n"
            "    except OSError:\n"
            "        continue\n"
            "    if '" + sentinel_tag + "' in cl:\n"
            "        found = True\n"
            "out.append('SENTINEL_FOUND ' + str(found))\n"
            "# try to signal the host sentinel pid by its HOST-pid number\n"
            "try:\n"
            "    os.kill(" + str(host_pid) + ", 0)\n"
            "    out.append('CAN_SIGNAL_HOST_PID YES')\n"
            "except ProcessLookupError:\n"
            "    out.append('CAN_SIGNAL_HOST_PID NO_PROC')\n"
            "except PermissionError:\n"
            "    out.append('CAN_SIGNAL_HOST_PID NO_PERM')\n"
            "except OSError as e:\n"
            "    out.append('CAN_SIGNAL_HOST_PID NO_OS ' + str(e.errno))\n"
            "print('__PIDNS__')\n"
            "for l in out: print(l)\n"
        )
        work_dir = os.path.join(tmp, "pidns")
        os.makedirs(work_dir, exist_ok=True)
        poc_path = _write_poc(work_dir, body)
        res = run_jailed_poc_with_loopback(
            ["python3", poc_path], repo_root=None, work_dir=work_dir, extra_ro=[],
            child_env=_child_env(), timeout_s=20.0, fs_signature="",
            callback_env_keys=("NGV2_SSRF_CALLBACK",), poc_path=poc_path,
        )
        out = res.get("stdout") or ""
        # parse
        vis = None
        for line in out.splitlines():
            if line.startswith("VISIBLE_PIDS "):
                vis = int(line.split()[1])
        small = vis is not None and vis <= 10
        not_found = "SENTINEL_FOUND False" in out
        cannot_signal = ("CAN_SIGNAL_HOST_PID NO_PROC" in out
                         or "CAN_SIGNAL_HOST_PID NO_PERM" in out)
        record("(f) PID-NS ISOLATION: jailed PoC in private pid-ns (small PID count)",
               small, f"visible_pids={vis} (host_total={host_total})")
        record("(f) PID-NS ISOLATION: cannot find host sentinel by cmdline",
               not_found, f"out={out!r}")
        record("(f) PID-NS ISOLATION: cannot signal arbitrary host PID",
               cannot_signal, f"host_sentinel_pid={host_pid} out_lines={[l for l in out.splitlines() if 'SIGNAL' in l]}")
    finally:
        try:
            sentinel.send_signal(signal.SIGKILL)
            sentinel.wait(timeout=5)
        except Exception:
            pass


def main() -> int:
    if not bwrap_available():
        print("BLOCKED: bwrap not on PATH; the live runner is fail-closed.")
        return 2
    with tempfile.TemporaryDirectory(prefix="p13l2-final-") as tmp:
        for fn in (
            assertion_a_b_positive_and_outbound,
            assertion_c_fs_oracle,
            assertion_d_no_callback_negative,
            assertion_e_fail_closed,
            assertion_f_pidns_isolation,
        ):
            try:
                fn(tmp)
            except Exception:
                record(fn.__name__, False, "EXCEPTION:\n" + traceback.format_exc())
    print("\n================ SUMMARY ================")
    all_ok = True
    for name, ok, _ in RESULTS:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}")
        all_ok = all_ok and ok
    print("========================================")
    print("VERDICT:", "WORKS (all assertions pass)" if all_ok else "RED (see above)")
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
