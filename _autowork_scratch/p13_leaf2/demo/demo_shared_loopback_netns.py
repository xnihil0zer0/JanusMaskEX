#!/usr/bin/env python3
"""P1.3 leaf-2 DEMONSTRATION -- exercises the REAL production shared-loopback-netns
detonation path (NOT an injected mock) and asserts the five required properties.

Run:  PYTHONPATH=/tmp/p13_leaf2_wt python3 demo_shared_loopback_netns.py

Each assertion drives ``ngv2.poc_runner_live.run_jailed_poc_with_loopback`` /
``ngv2.workers._runner._make_detonation_seam`` over a REAL bwrap jail (the same code
path production uses), so a pass here means a real jailed PoC actually talks to the
in-netns listener while outbound stays blocked.

  (a) POSITIVE       : real jailed PoC fetches the nonce callback -> hit in listener,
                       absent from a no-callback baseline.
  (b) OUTBOUND BLOCKED: raw-IP connect to TEST-NET 192.0.2.1:80 AND 1.1.1.1:80 fails.
  (c) FS-ORACLE       : a path-write CWE still confirms via the FS snapshot diff.
  (d) NO-CALLBACK NEG : a PoC that never calls back (or wrong nonce) does NOT confirm
                        via ssrf_channel.
  (e) FAIL-CLOSED     : a forced namespace/listener setup failure raises the
                        live-runner error -- NEVER a host-netns / outbound-open run.
"""
from __future__ import annotations
import os
import sys
import traceback

import ngv2.poc_runner_live as prl
from ngv2.poc_runner_live import (
    LiveRunnerError,
    bwrap_available,
    run_jailed_poc_with_loopback,
)
from ngv2.contracts import PoC

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
    """A REAL jailed PoC that (1) hits the nonce callback and (2) attempts raw-IP
    outbound to two off-host addresses. Assert: nonce in hits; outbound both fail."""
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
        ["python3", poc_path],
        repo_root=None,
        work_dir=work_dir,
        extra_ro=[],
        child_env=_child_env(),
        timeout_s=25.0,
        fs_signature="",
        callback_env_keys=("NGV2_SSRF_CALLBACK",),
        poc_path=poc_path,
    )
    hits = res.get("hits") or []
    stdout = res.get("stdout") or ""
    nonce_hit = any(nonce in str(h) for h in hits)
    record(
        "(a) POSITIVE: nonce callback reaches in-netns listener",
        nonce_hit and "LOOPBACK_OK" in stdout,
        f"hits={hits} stdout={stdout!r}",
    )
    outbound_open = "OUTBOUND_OPEN" in stdout
    both_blocked = (
        stdout.count("OUTBOUND_BLOCKED") == 2 and not outbound_open
    )
    record(
        "(b) OUTBOUND BLOCKED: raw-IP 192.0.2.1 & 1.1.1.1 refused",
        both_blocked,
        f"stdout={stdout!r}",
    )

    # Baseline: same nonce, but a PoC that never calls back -> nonce NOT in hits.
    base_dir = os.path.join(tmp, "baseline")
    os.makedirs(base_dir, exist_ok=True)
    base_path = _write_poc(base_dir, "print('NO_CALLBACK')\n")
    base = run_jailed_poc_with_loopback(
        ["python3", base_path],
        repo_root=None,
        work_dir=base_dir,
        extra_ro=[],
        child_env=_child_env(),
        timeout_s=20.0,
        fs_signature="",
        callback_env_keys=("NGV2_SSRF_CALLBACK",),
        poc_path=base_path,
    )
    base_hits = base.get("hits") or []
    record(
        "(a) BASELINE: nonce absent when PoC does not call back",
        not any(nonce in str(h) for h in base_hits),
        f"baseline_hits={base_hits}",
    )


# --------------------------------------------------------------------------- (c)
def assertion_c_fs_oracle(tmp: str) -> None:
    """Drive the production seam (loopback=True, no injected runner) with a path-write
    CWE: the FS-snapshot detonation oracle must still confirm. Proves netns isolation
    is orthogonal to the mount namespace."""
    from ngv2.workers._runner import _make_detonation_seam

    seam = _make_detonation_seam()
    if seam is None:
        record("(c) FS-ORACLE no-regression", False, "seam unavailable")
        return
    # A real RCE-style PoC that writes the expected fs signature into the work_dir.
    poc = "print('VULNERABLE')\nopen('pwned_marker', 'w').write('x')\n"
    finding = {
        "id": "F-demo-rce",
        "cwe": "CWE-78",
        "expected_fs_signature": "A pwned_marker",
    }
    res = seam(poc=poc, finding=finding)
    ok = (
        res.get("success") is True
        and res.get("verdict") == "confirmed"
        and "A pwned_marker" in (res.get("fs_snapshot_diff") or "")
    )
    record(
        "(c) FS-ORACLE no-regression: path-write CWE confirms via snapshot diff",
        ok,
        f"verdict={res.get('verdict')} diff={res.get('fs_snapshot_diff')!r} success={res.get('success')}",
    )


# --------------------------------------------------------------------------- (d)
def assertion_d_no_callback_negative(tmp: str) -> None:
    """Production seam with a PoC that calls back with the WRONG nonce -> the real
    listener records a hit for a different path, so the ssrf_channel for OUR nonce
    does NOT confirm."""
    from ngv2.workers._runner import _make_detonation_seam

    seam = _make_detonation_seam()
    if seam is None:
        record("(d) NO-CALLBACK negative", False, "seam unavailable")
        return
    # PoC hits a DIFFERENT path than its own nonce -> our nonce never arrives.
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
    ok = (
        ssrf.get("success") is False
        and res.get("success") is False
        and res.get("reproduced") is False
    )
    record(
        "(d) NO-CALLBACK negative: wrong nonce does NOT confirm via ssrf_channel",
        ok,
        f"ssrf_channel={ssrf} success={res.get('success')}",
    )


# --------------------------------------------------------------------------- (e)
def assertion_e_fail_closed(tmp: str) -> None:
    """Force the in-jail setup to fail (bootstrap emits NO result sentinel) and assert
    ``run_jailed_poc_with_loopback`` RAISES ``LiveRunnerError`` -- never degrading to a
    host-netns / outbound-open run.

    We simulate the namespace/listener setup failure WITHOUT loosening isolation by
    pointing the bootstrap module at a non-existent name, so the jail's first process
    exits non-zero with no sentinel -- exactly the runtime signature of a netns/lo/bind
    failure on a locked-down host. The fail-closed contract is: no sentinel => raise.
    """
    import ngv2.poc_runner_live as m

    work_dir = os.path.join(tmp, "failclosed")
    os.makedirs(work_dir, exist_ok=True)
    poc_path = _write_poc(work_dir, "print('should never matter')\n")
    saved = m._LOOPBACK_BOOTSTRAP_MODULE
    raised = False
    degraded_outbound = False
    err_msg = ""
    try:
        m._LOOPBACK_BOOTSTRAP_MODULE = "ngv2._loopback_netns_DOES_NOT_EXIST"
        try:
            run_jailed_poc_with_loopback(
                ["python3", poc_path],
                repo_root=None,
                work_dir=work_dir,
                extra_ro=[],
                child_env=_child_env(),
                timeout_s=15.0,
                fs_signature="",
                callback_env_keys=("NGV2_SSRF_CALLBACK",),
                poc_path=poc_path,
            )
        except LiveRunnerError as e:
            raised = True
            err_msg = str(e)
        except Exception as e:  # any OTHER exception is a failure of the contract
            err_msg = f"unexpected {type(e).__name__}: {e}"
    finally:
        m._LOOPBACK_BOOTSTRAP_MODULE = saved
    # The contract: a setup failure RAISES (fail-closed). The function never returns a
    # result by running the PoC outside the shared netns, so no outbound path opens.
    record(
        "(e) FAIL-CLOSED: setup failure raises LiveRunnerError, no host-netns fallback",
        raised and not degraded_outbound,
        f"raised={raised} msg={err_msg[:160]!r}",
    )

    # (e2) A MORE AUTHENTIC namespace failure: drop CAP_NET_ADMIN from the jail so the
    # in-jail bootstrap CANNOT bring `lo` up (ioctl -> EPERM). The bootstrap then exits
    # non-zero with NO result sentinel, and the parent must STILL raise -- never run the
    # PoC with an open outbound path. This exercises the real lo-up failure mode.
    work_dir2 = os.path.join(tmp, "failclosed_nocap")
    os.makedirs(work_dir2, exist_ok=True)
    poc2 = _write_poc(work_dir2, "print('x')\n")
    saved_argv = m.build_detonation_jail_argv
    raised2 = False
    msg2 = ""

    def _argv_without_cap(cmd, *, repo_root, work_dir, extra_ro=(), shared_loopback_netns=False):
        argv = saved_argv(cmd, repo_root=repo_root, work_dir=work_dir, extra_ro=extra_ro, shared_loopback_netns=shared_loopback_netns)
        # Strip the `--cap-add CAP_NET_ADMIN` pair to simulate a locked-down host where
        # the netns cannot be configured -> lo stays DOWN -> bootstrap fails closed.
        out = []
        i = 0
        while i < len(argv):
            if argv[i] == "--cap-add" and i + 1 < len(argv):
                i += 2
                continue
            out.append(argv[i])
            i += 1
        return out

    try:
        m.build_detonation_jail_argv = _argv_without_cap
        try:
            run_jailed_poc_with_loopback(
                ["python3", poc2],
                repo_root=None,
                work_dir=work_dir2,
                extra_ro=[],
                child_env=_child_env(),
                timeout_s=15.0,
                fs_signature="",
                callback_env_keys=("NGV2_SSRF_CALLBACK",),
                poc_path=poc2,
            )
        except LiveRunnerError as e:
            raised2 = True
            msg2 = str(e)
        except Exception as e:
            msg2 = f"unexpected {type(e).__name__}: {e}"
    finally:
        m.build_detonation_jail_argv = saved_argv
    record(
        "(e2) FAIL-CLOSED: lo cannot come up (no CAP_NET_ADMIN) -> raises, no fallback",
        raised2,
        f"raised={raised2} msg={msg2[:160]!r}",
    )


def main() -> int:
    if not bwrap_available():
        print("BLOCKED: bwrap not on PATH; the live runner is fail-closed.")
        return 2
    import tempfile

    with tempfile.TemporaryDirectory(prefix="p13l2-demo-") as tmp:
        for fn in (
            assertion_a_b_positive_and_outbound,
            assertion_c_fs_oracle,
            assertion_d_no_callback_negative,
            assertion_e_fail_closed,
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
