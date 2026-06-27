#!/usr/bin/env python
"""Adversarial empirical probe for brief_hooks_g7_fuzz_jail_credfree.

Run from repo root with:  PYTHONPATH=. python _autowork_scratch/p01_adversarial_probe.py

Settles the GO/NO-GO question: when the diff-fuzz Popen argv is wrapped via
build_jail_argv(..., bind_credentials=False), does the CHILD's write to a
result file under work_dir propagate back to the PARENT (host)?  And is the
host credential genuinely unreadable from inside the jail?
"""
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[1])


def hr(t):
    print("\n" + "=" * 70)
    print(t)
    print("=" * 70)


def main():
    bwrap = shutil.which("bwrap")
    hr("ENVIRONMENT")
    print(f"bwrap on PATH: {bwrap!r}")
    print(f"repo_root: {REPO}")
    print(f"HOME: {os.environ.get('HOME')}")
    if not bwrap:
        print("\nbwrap ABSENT -> empirical question UNSETTLED on this host.")
        print("Fallback path would be a plain Popen (legacy un-jailed spawn).")
        return

    from harness.agent_jail import build_jail_argv, bwrap_available
    print(f"bwrap_available(): {bwrap_available()}")

    # This mirrors the proposed _jailed_popen wiring exactly: cmd is the same
    # argv shape the single-input Sandbox.execute site spawns, work_dir==cwd,
    # state_dir==work_dir, repo_root==JM repo, bind_credentials=False.
    def jailed_argv(cmd, cwd):
        return build_jail_argv(
            cmd,
            repo_root=REPO,
            work_dir=cwd,
            state_dir=cwd,
            bind_credentials=False,
        )

    # ------------------------------------------------------------------
    # TEST 1 — ROUND-TRIP (the GO/NO-GO)
    # ------------------------------------------------------------------
    hr("TEST 1: ROUND-TRIP (work_dir child-write -> host parent-read)")
    rt_pass = False
    captured_argv = None
    with tempfile.TemporaryDirectory(prefix="p01_rt_") as wd:
        wd = str(Path(wd).resolve())
        runner = Path(wd) / "_runner.py"
        result = Path(wd) / "_result.json"
        # Runner writes an ABSOLUTE result path under work_dir, exactly like
        # _RUNNER_TEMPLATE (open(result_path,"w")). Pass it as argv[1].
        runner.write_text(
            "import sys\n"
            "rp = sys.argv[1]\n"
            "open(rp, 'w').write('HELLO_42')\n"
            "print('child wrote', rp)\n"
        )
        cmd = [sys.executable, str(runner), str(result)]
        argv = jailed_argv(cmd, wd)
        captured_argv = argv
        # env mirrors sandbox_child_env's relevant keys
        env = os.environ.copy()
        env.update({"HOME": wd, "TMPDIR": wd, "PATH": os.environ.get("PATH", "/usr/bin:/bin")})
        proc = subprocess.run(
            argv, cwd=wd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, start_new_session=True, timeout=30,
        )
        print(f"child returncode: {proc.returncode}")
        print(f"child stdout: {proc.stdout.strip()!r}")
        print(f"child stderr: {proc.stderr.strip()[:400]!r}")
        # PARENT reads the host file back
        host_exists = result.exists()
        host_bytes = result.read_text() if host_exists else "<MISSING>"
        print(f"PARENT sees result file exists: {host_exists}")
        print(f"PARENT read-back value: {host_bytes!r}")
        rt_pass = host_exists and host_bytes == "HELLO_42"
    print(f"\n>>> ROUND-TRIP: {'PASS' if rt_pass else 'FAIL'} "
          f"(work_dir writes {'propagate to host' if rt_pass else 'DO NOT propagate'})")

    # ------------------------------------------------------------------
    # TEST 2 — CRED-BLOCK
    # ------------------------------------------------------------------
    hr("TEST 2: CRED-BLOCK (child cannot read host credentials)")
    home = os.environ.get("HOME", "/tmp")
    gemini = os.path.join(home, ".gemini", "oauth_creds.json")
    claude = os.path.join(home, ".claude", ".credentials.json")
    # pick a real host file under $HOME root NOT under ~/.nvm as the canary
    if os.path.exists(gemini):
        target = gemini
    elif os.path.exists(claude):
        target = claude
    else:
        # any real host file at $HOME root, not ~/.nvm
        cand = [os.path.join(home, ".bashrc"), os.path.join(home, ".claude.json")]
        target = next((c for c in cand if os.path.exists(c)), None)
    print(f"canary host file: {target!r}")
    cb_pass = None
    if target is None:
        print("No suitable host canary file found -> cred-block test SKIPPED")
    else:
        host_real = ""
        try:
            host_real = open(target, "rb").read().decode("utf-8", "replace")
        except OSError as e:
            print(f"(parent could not read canary: {e})")
        with tempfile.TemporaryDirectory(prefix="p01_cb_") as wd:
            wd = str(Path(wd).resolve())
            runner = Path(wd) / "_runner.py"
            out = Path(wd) / "_out.txt"
            runner.write_text(
                "import sys, os\n"
                "tgt = sys.argv[1]; outp = sys.argv[2]\n"
                "try:\n"
                "    data = open(tgt).read()\n"
                "    open(outp, 'w').write('READ_OK::' + data)\n"
                "except Exception as e:\n"
                "    open(outp, 'w').write('BLOCKED::' + type(e).__name__ + '::' + str(e))\n"
            )
            cmd = [sys.executable, str(runner), target, str(out)]
            argv = jailed_argv(cmd, wd)
            env = os.environ.copy()
            env.update({"HOME": wd, "TMPDIR": wd, "PATH": os.environ.get("PATH", "/usr/bin:/bin")})
            proc = subprocess.run(
                argv, cwd=wd, env=env, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, start_new_session=True, timeout=30,
            )
            print(f"child returncode: {proc.returncode}")
            print(f"child stderr: {proc.stderr.strip()[:400]!r}")
            child_out = out.read_text() if out.exists() else "<NO OUTPUT FILE>"
            print(f"child outcome: {child_out[:200]!r}")
            leaked = child_out.startswith("READ_OK::") and host_real and host_real in child_out
            cb_pass = not leaked
    print(f"\n>>> CRED-BLOCK: {'PASS' if cb_pass else ('SKIPPED' if cb_pass is None else 'FAIL')} "
          f"(host creds {'unreadable in jail' if cb_pass else 'LEAKED' if cb_pass is False else 'n/a'})")

    # ------------------------------------------------------------------
    # ARGV DUMP
    # ------------------------------------------------------------------
    hr("EXACT JAILED ARGV (build_jail_argv, bind_credentials=False)")
    for i, tok in enumerate(captured_argv):
        print(f"  [{i:02d}] {tok}")
    has_unshare_net = "--unshare-net" in captured_argv
    has_unshare_ipc = "--unshare-ipc" in captured_argv
    # check no home-root cred binds
    home_real = str(Path(home).resolve())
    cred_binds = []
    for i, tok in enumerate(captured_argv):
        if tok in ("--bind", "--ro-bind") and i + 1 < len(captured_argv):
            src = captured_argv[i + 1]
            if (src.startswith(os.path.join(home_real, ".gemini"))
                    or src.startswith(os.path.join(home_real, ".claude"))):
                cred_binds.append((tok, src))
    print(f"\n--unshare-net present: {has_unshare_net}")
    print(f"--unshare-ipc present: {has_unshare_ipc}")
    print(f"~/.gemini or ~/.claude binds: {cred_binds if cred_binds else 'NONE'}")

    hr("SUMMARY")
    print(f"ROUND-TRIP: {'PASS' if rt_pass else 'FAIL'}  (GO/NO-GO)")
    print(f"CRED-BLOCK: {'PASS' if cb_pass else ('SKIPPED' if cb_pass is None else 'FAIL')}")
    print(f"--unshare-net present: {has_unshare_net}")
    print(f"no cred binds: {not cred_binds}")


if __name__ == "__main__":
    main()
