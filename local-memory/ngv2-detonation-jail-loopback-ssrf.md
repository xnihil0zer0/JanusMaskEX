---
name: ngv2-detonation-jail-loopback-ssrf
description: "NGv2 detonation jail is bwrap --unshare-net (no off-host net, but loopback WORKS); FS-snapshot oracle covers RCE/path-trav/SQLi/code-injection; SSRF-via-loopback is viable in-jail but LoopbackListener is unwired"
metadata: 
  node_type: memory
  type: project
  originSessionId: ae16acba-9ad9-45c6-989f-a8c880d79cef
---

VERIFIED 2026-06-15 (real-jail test, not assumption).

NGv2 detonates PoCs in `ngv2/poc_runner_live.py:82`:
`bwrap --die-with-parent --unshare-net --unshare-ipc --unshare-pid --new-session
--proc /proc --dev /dev --tmpfs /tmp`. The confirmation oracle is a **filesystem
snapshot/diff** (`snapshot_tree`/`diff_snapshots` → `fs_snapshot_diff` matched
against `expected_fs_signature`); `detonation_evidence_gate.classify_detonation_evidence`
only allows `confirmed` when `ran_target AND observed_runtime_effect` (= the FS
effect). No network is needed for this — by design (un-exfiltratable).

★ bwrap `--unshare-net` BRINGS LOOPBACK UP: external blocked (OSError), but
127.0.0.1 bind+connect WORKS (proven directly). So:
- RCE (CWE-78, proven confirmed), code-injection (94), path-traversal (22),
  SQLi (89) — all local + FS-observable → the no-network jail does NOT impede them.
- **SSRF (CWE-918) / blind OOB exfil** is the only class whose proof is a network
  callback. It IS viable in-jail via an IN-JAIL `LoopbackListener` (the detonating
  target can reach 127.0.0.1 in the same netns; a HOST-side listener cannot —
  separate netns). The gap is purely that `ngv2/loopback_listener.py`
  (`LoopbackListener`, binds `http.server.HTTPServer((127.0.0.1, port))`) is BUILT
  but NOT wired into poc_runner_live / poc_repair_loop / the evidence gate. This is
  the substance of finishing Leaf 5 (`sink_instrument` + `loopback_listener`) and
  is why some eligible SSRF leads (mlflow/litellm) aren't yet confirmable.
- To wire: run the listener inside the detonation bwrap netns (same invocation),
  OR detect SSRF via an attempted connect() syscall instead of a completed request.

This is SEPARATE from the JanusMask factory verification jail (also --unshare-net):
that only affects BUILDING tooling; see [[red-gate-silently-stuck-every-harness-fix]].
