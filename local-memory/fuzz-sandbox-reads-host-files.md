---
name: fuzz-sandbox-reads-host-files
description: VERIFIED unfixed gap — the diff-fuzz sandbox (sandbox.py) is a plain Popen with no mount namespace; a fuzzed candidate can read host files incl. credentials
metadata: 
  node_type: memory
  type: project
  originSessionId: 338e4423-bfd9-4794-bb78-0b22aede768f
---

🔓 The differential-fuzz sandbox is NOT filesystem-isolated. `harness/sandbox.py` launches
candidates via a **plain `subprocess.Popen`** (`sandbox.py:892`, comment at `:138` "plain
subprocess") with **no bwrap / unshare / chroot / mount namespace**. Its seccomp deny-set is
**network + process-creation only** (`socket/connect/bind/.../fork/execve`); **all file-read
syscalls (`open/openat/read/stat/…`) are permitted**. EMPIRICALLY PROVEN 2026-06-19: the real
`Sandbox.execute` ran `def leak(): return open(...).read()` and read `/etc/hostname` AND a planted
credential-shaped file (returned the sentinel token). Re-running the SAME candidate through the
existing `agent_jail.build_jail_argv` (`bind_credentials=False, --unshare-net`) BLOCKED the
credential read.

**Fix (cheap, highest-value §3 item): wrap the fuzz `Popen` in the in-repo cred-free `bwrap` seam.**
★2026-06-19 RE-AUDIT (waves 3+4, 4 agents each, scripts under `AI-Data/Research-JanusMask/_adversarial_audit{3,4}/r02/`):
(1) there are **THREE** un-jailed Popen sites, not one — `sandbox.py:892`, `:1077` (batch pool), `:1281`
(worker pool); a fix must cover all three. (2) The correct seam is `agent_jail.build_jail_argv(bind_credentials=False)`
— **execution-proven to BLOCK** the cred read (drove the offending read through it → `FileNotFound` on all
three cred paths; argv has only `--ro-bind ~/.nvm`, no `~/.gemini`/`~/.claude`, + `--unshare-net/ipc`). This
seam is ALREADY the production narrow-fuzz/external-verify path (5 files incl. `narrow_fuzz/validation.py:292`,
`orchestrator.py:2969/3072/3104/3126`) — BUT the G7-vulnerable `diff_fuzzer.py`→`sandbox.py` Popen is a
**SEPARATE seam with zero jail routing** (only a stale docstring), so the fix ADDS the routing. (A prior
round-2 audit's "use build_detonation_jail_argv NOT agent_jail" claim was WRONG — only the *default*
`bind_credentials=True` path binds creds.) "~3.3 ms/spawn" remains UNVERIFIED (no in-repo benchmark). NOT
Firecracker/gVisor. Note: `/etc/hostname` stays readable inside the jail by design.

Evidence: `/home/xnihil0zer0/AI-Data/Research-JanusMask/methodology_eval/wave2/microservices/`
(`h1_fs_isolation_hole.py`, `h5_seccomp_audit.py`). Part of the methodology-doc evidence-backed
rewrite (`JanusMaskJR_methodology_analysis.md`). Companion corrected claims from the same pass: the
git commit lock is BOUNDED (60s `LOCK_NB`, NOT "indefinite") and the fsync ledger is NOT a
bottleneck (~0.04 rows/s real vs ~328/s capacity). If fixing via the pipeline, this writes
`harness/sandbox.py` → `harness_self_fix`, and sandbox.py is in the `_NEVER_AUTO_APPROVE`-adjacent
sensitive set so pre-author a decision file. See [[ngv2-detonation-jail-loopback-ssrf]].
