---
name: auto-commit-failed-multifile-rootcause
description: "THE systemic auto_commit_failed root cause (found+verified 2026-06-15): _auto_approve_sensitive_eligible requires EVERY file to be harness/**, so ANY multi-file task mixing harness/** impl + tests/** oracle (every test_authoring oracle + harness-fix-with-test) is denied auto-approve -> scope violation -> auto_commit_failed. Blocked ~15 tasks for days."
metadata:
  node_type: memory
  type: project
  originSessionId: ae16acba-9ad9-45c6-989f-a8c880d79cef
---

🚨🚨 ROOT CAUSE of the SYSTEMIC `auto_commit_failed` that silently blocked ~15
multi-file/oracle tasks for DAYS (factory-repair-feedback ×4, nm-oracle ×3,
ngv2-source-localize ×6, leaf-4a, sink-instrument, test-stageworker, tmux-worker,
fix-selfheal-parallel-isolation, ...). Found + verified live 2026-06-15.

★ THE BUG: `harness/orchestrator.py::_auto_approve_sensitive_eligible` per-rel loop
ended with `if not _matches_sensitive(rel, ('harness/**',)): return False` — i.e.
EVERY file in files_touched had to be a `harness/**` path. A multi-file task whose
files_touched mixes a `harness/**` impl with a `tests/**` oracle (the NORMAL shape
of every test_authoring oracle AND every harness-fix-bundled-with-its-test) is
therefore INELIGIBLE -> the orchestrator passes `approval_ok=False,
widened_auto_approve=True` to `commit_accepted_output` ->
`git_integration._enforce_apply_scope` rejects the `harness/**` file
(`ok_strict` needs approval_ok=True; `ok_widened` needs `widened AND approval_ok`
— line 84, BOTH paths need approval_ok) -> commit refused -> rolled back as
`auto_commit_failed`. SINGLE harness/** file tasks (ac5af72, c6b28e0) commit fine
because every rel is harness/**.

★ PROOF: vcmd PASSES on the manifest content (17/17 in a temp worktree) so it is
NOT a verify failure. `_parse_manifest` parses the submission fine. Direct probe:
`_auto_approve_sensitive_eligible(...,['harness/x.py','tests/test_x.py'],cfg)` ->
False; `(...,['harness/x.py'],cfg)` -> True. commit_accepted_output probe with
approval_ok=True -> committed=True; approval_ok=False (even widened=True) ->
"apply-path scope violation ... protected path".

★★ FIX LANDED + VERIFIED 2026-06-15 (JM `c555c5c`, single-file orchestrator.py edit +12/-3,
vcmd 17/17 green re-run at HEAD; 4-auditor consensus confirms it preserves every assertion in
all 5 test files incl the tricky tools/**->False & services/**->False edges): the per-rel loop
now requires AT LEAST ONE harness/** non-deny path (`saw_harness`), REJECTs sensitive-but-non-
harness (config/**, scripts/**, services/** via _SENSITIVE_APPLY_GLOBS), ALLOWs non-sensitive
(tests/**, docs) to ride along, with post-loop `if not saw_harness: return False`. Required an
OPERATOR DECISION FILE (orchestrator.py is _NEVER_AUTO_APPROVE). Unblocks ~15 stuck multi-file
tasks + the self-heal deadlock fix [[selfheal-deadlock-blocks-all-dispatch]].
★ MECHANISM CORRECTIONS (auditor 4, verified): the OPERATIVE blocker is the UNCONDITIONAL
harness/**-only loop, NOT the `harness_self_fix` requirement (that requirement is bypassed by
the `_widened` posture when autowork.enabled=True). The refusal is PRE-APPLY (commit refused
upfront), not a commit-then-rollback. And the operator-decision -> ok_strict bypass is ONLY
true for `harness_self_fix` meta_task_type (ok_strict = meta=='harness_self_fix' and approval_ok);
for OTHER meta types an operator approval alone does NOT satisfy ok_strict/ok_widened — those
rely on the saw_harness auto-approve path (approval_ok=True via _auto_approve_sensitive_eligible).

★ GOTCHA: `_requires_verbatim_manifest` forces WHOLE-FILE __JANUSMASK_MANIFEST__
for ANY multi-file task (len>1) — so you CANNOT co-edit orchestrator.py (4000 lines)
with a test file via patches; the orchestrator.py fix MUST be single-file patches.
Add a regression test for the mixed-eligible case via a SEPARATE tests/-only
test_authoring task afterward (tests/ is non-sensitive -> auto-approves single-file).
★ operator decision file = state/control/decisions/<task_id>.json {"decision":"approve"};
read by _apply_approval_granted, BYPASSES the buggy eligibility gate (sets
approval_ok=True -> ok_strict). See [[backup-detach-fixes-systemic-autocommit]]
(a DIFFERENT, already-fixed auto_commit_failed cause — lock contention).
