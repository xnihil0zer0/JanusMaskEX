---
name: newmodule-oracle-fix-and-trust-core-approval
description: newmodule_oracle_acceptance LANDED (JM 098fc0e); trust-core files need an operator decision file even under auto_approve_sensitive_harness; re-plan requires evicting blocked task
metadata: 
  node_type: memory
  type: project
  originSessionId: ae16acba-9ad9-45c6-989f-a8c880d79cef
---

✅ **newmodule_oracle_acceptance LANDED 2026-06-15 (JM `098fc0e`, oracle master `97159a7`, verify 14/14 exit0).** `_auto_commit_accepted` now ACCEPTS a `test_authoring` RED-by-absence oracle whose `mutation_target` module is absent on disk (bypasses the vcmd-exit-0 + mutant gates for that case only via helper `_new_module_red_by_absence`); ALSO `_run_wire_up_gate` now exempts pytest test files by NAME (`test_*.py`/`*_test.py`), not just by `tests/` directory. **This breaks the bootstrap catch-22 → the factory authors new-module RED oracles itself; no more hand-committed RED oracles for new modules.** Builds on [[spec-only-pipeline-augment-agents]].

**★ TRUST-CORE OPERATOR CHECKPOINT (the real blocker, not the gates):** `harness/orchestrator.py` is on `_NEVER_AUTO_APPROVE` (orchestrator.py:2137) — with `agent_jail.py`, `git_integration.py`, `dbus_proxy.py`, `paths.py`, `interceptors.py`, `selfheal.py`, `autowork_daemon.py`, `services/**`. Edits to these CANNOT auto-commit even with `meta_task_type=harness_self_fix` + `auto_approve_sensitive_harness:true` (`_auto_approve_sensitive_eligible` returns False on the deny-list match). They require an EXPLICIT operator decision file: `state/control/decisions/<task_id>.json` = `{"decision":"approve"}` (read by `_apply_approval_granted`, sets `_approval_ok=True` at orchestrator.py:2633, which overrides the never-auto-approve list in scope). Symptom when missing: `auto_commit_failed` with NO verification/orphan/mutant/toctou event row, and worker-only log `apply-path scope violation`. This is the designed human checkpoint — owner must authorize per-fix.

**★ RE-PLAN GOTCHA:** after editing a brief, deleting only the `blocked/<tid>.json` record is NOT enough — `_retry_blocked_tasks` (budget 3) re-runs the STALE spec ahead of any brief re-plan (telemetry `extract … retry_blocked attempts=N`). To force a fresh re-plan you must evict ALL `<tid>` artifacts (blocked json+retry, output sidecar/.py, sessions, test_results baseline, running pid) so there's nothing to retry.

**★ decode_check ok:False is a RED HERRING** for `__JANUSMASK_PATCHES__` emissions — `autocompiler.decode_submission` only parses JSON, so it always rejects a Python patch block; it's telemetry, not a gate.

**★ Large-function reproduction is NOT the bottleneck on opus** — it reproduced the 730-line `_auto_commit_accepted` verbatim (parses, 3 correct patch entries). The verification gate is encoding-independent and catches incomplete fixes (HEAD never moved through 3 bad attempts). Owner-approved next capability when reproduction DOES fail (>~150-line symbols): a sentinel-free `anchor` patch generalizing the existing `region` patch (git_integration.py:1257) — deterministic splice, no whole-body reproduction; land via pipeline.

NEXT: Leaf 5 (`srcdrive_leaf5_confirm`) RESUMED — factory authors oracle+impl for `ngv2/sink_instrument.py` + `ngv2/loopback_listener.py` (new modules, NOT trust-core → no operator approval). Then Leaf 6/7/8.
