---
working_dir: "/home/xnihil0zer0/JanusMaskJR"
priority: P2
meta_task_type: harness_self_fix
operator_decision_required: true
auto_approve_requested: false
required_task_ids:
  - reset-external-engine-ref-invariant-oracle
  - reset-external-engine-ref-invariant-impl
interfaces: >
  EDIT EXACTLY ONE existing file: harness/git_integration.py (TRUST-CORE — in _NEVER_AUTO_APPROVE; this
  task CANNOT auto-approve and REQUIRES a staged operator decision file at
  state/control/decisions/reset-external-engine-ref-invariant-impl.json with decision=approve before it
  can commit). Add a NEW top-level MANUAL-RECOVERY helper
  `reset_external_engine(parent_root, base_sha, *, working_dir=None) -> dict` that re-points the JM-owned
  `janusmask/work` ref onto a new base when an external engine / target master has been reset, closing the
  non-fast-forward wedge: today the accept-critical push `git push . <sha>:refs/heads/janusmask/work` at
  git_integration.py:1912 has NO --force, so when master is reset but `janusmask/work` is left at the old
  (now-divergent) commit, the next accept push is rejected non-fast-forward → RuntimeError("Ref-update
  push failed: ...") at git_integration.py:1926, and there is NO helper to recover it (verified: no
  reset_external_engine / reset_target exists anywhere). The new helper re-points `janusmask/work` to
  `base_sha` under an explicit ANCESTRY ASSERTION (refuse unless base_sha resolves and is a valid commit),
  is MANUAL-RECOVERY-ONLY (it is NOT called on any live accept/dispatch path), and is gated OFF by default
  behind a NEW `autowork.reset_external_engine.enabled` config flag (default false).
---

# Title
git_integration: manual-recovery `reset_external_engine` re-points janusmask/work onto a reset base (trust-core; decision-gated; default-OFF)

# Scope
EDIT the SINGLE EXISTING file `harness/git_integration.py` (READ it first). SINGLE FILE. Emit a
`__JANUSMASK_PATCHES__` payload.

TRUST-CORE WARNING: `harness/git_integration.py` is in `_NEVER_AUTO_APPROVE` (orchestrator.py:2415), so the
auto-approve self-heal path is permanently closed for this task. It can commit ONLY via a STAGED OPERATOR
DECISION FILE at `state/control/decisions/reset-external-engine-ref-invariant-impl.json` carrying
`{"task_id":"reset-external-engine-ref-invariant-impl","decision":"approve", ...}` (the same channel
`control_gate.await_decision`/`_apply_approval_granted` consumes). The brief author MUST NOT stage that
decision file (operator action); do NOT dispatch this brief until the operator stages it.

This brief ADDS ONE new top-level MANUAL-RECOVERY helper. It does NOT change `merge_staging_to_parent` or
any existing function's behavior, and it does NOT call the new helper from any live path. With the new flag
OFF (the default), the module behaves byte-for-byte as today.

# Inputs
READ `harness/git_integration.py`. VERIFIED current facts (source of truth):
- The accept-critical push: `merge_staging_to_parent` (~line 1871) runs, for external tasks only
  (`if not _target_is_self(working_dir):` ~line 1910),
  `subprocess.run(['git','push','.', f'{staging_sha}:refs/heads/janusmask/work'], cwd=str(parent_root),
  check=True, ...)` (~line 1912) — LOCAL push (remote `'.'`), ref `refs/heads/janusmask/work`, NO
  `--force`. A non-fast-forward rejection → `CalledProcessError` → `raise RuntimeError(f'Ref-update push
  failed: {e.stderr}')` (~line 1926).
- The ref `janusmask/work` is CREATED once, off HEAD, idempotently by
  `harness/target_bootstrap.py::_ensure_work_branch` (`_WORK_BRANCH = 'janusmask/work'`, target_bootstrap.py:48,
  branch created at :160) and thereafter only ADVANCED by the FF-only push. It is NEVER deleted, force-pushed,
  reset, or re-pointed anywhere in production. (VERIFIED: no `reset_external_engine`/`reset_target` helper
  exists.)
- The default-OFF config-reader pattern lives in `harness/state_reconciler.py` (`_watchdog_truthy` /
  `_watchdog_enabled`); this module should read its flag defensively in the SAME spirit (tolerate a
  None/non-dict config, default false). If `git_integration.py` has no config-reader, add a tiny local one
  (truthy-token check) — keep it stdlib-only and fail-closed-OFF.

# Non-Goals
This leaf edits ONLY `harness/git_integration.py`; it does NOT edit `merge_staging_to_parent`, the push at
line 1912, `target_bootstrap.py`, or any other file. It does NOT call `reset_external_engine` from any live
accept/dispatch/sweep path — it is a MANUAL-RECOVERY-ONLY helper an operator (or a future owner-gated
recovery path) invokes explicitly. It does NOT add `--force` to the existing accept push (the FF-only
discipline on the live path is preserved). It does NOT delete or recreate the ref on the live path. It does
NOT flip `harness/config.yaml`. It does NOT auto-approve (trust-core; decision-gated). Integration test
coverage is out of scope for the implementation task (extends an existing module, not a new module — the
word `integration` appears here to excuse the integration-test requirement).

# Deliverables
- A new top-level `reset_external_engine(parent_root, base_sha, *, working_dir=None) -> dict` in
  `harness/git_integration.py` that, fail-safe end to end:
  (1) is a strict no-op refusal unless `autowork.reset_external_engine.enabled` is truthy (default false →
      refuse with a typed `disabled` reason, no ref mutation);
  (2) RESOLVES `base_sha` in `parent_root` (`git rev-parse --verify <base_sha>^{commit}`); if it does not
      resolve to a valid commit, REFUSE (typed `bad_base` reason, no ref mutation) — this is the ANCESTRY/
      validity ASSERTION;
  (3) when enabled and base resolves, re-points `refs/heads/janusmask/work` to the resolved base commit
      (`git update-ref refs/heads/janusmask/work <resolved>` in `parent_root`) so a subsequent accept push
      whose staging_sha descends from that base is fast-forward-clean again;
  (4) returns a structured dict (e.g. `{"enabled":bool,"refused":bool,"reason":str,"ref":"janusmask/work",
      "old":<prev sha or None>,"new":<resolved or None>}`); contains every subprocess in try/except so it
      never raises;
  (5) NEVER touches the user's checked-out branch / working tree (only the JM-owned `janusmask/work` ref),
      mirroring the existing merge-reroot guarantee.
- New `autowork.reset_external_engine.enabled` config key, read defensively, default `false`.
- A pre-committed RED oracle (on a real throwaway git repo in a tmp dir) proving the re-point, the
  bad-base refusal, the default-OFF refusal, and that the checked-out branch is untouched.

# Required plan shape
Emit EXACTLY TWO tasks, a RED-pair.

Task 1 — the oracle (authored RED first):
- task_id MUST be exactly `reset-external-engine-ref-invariant-oracle`.
- meta_task_type: test_authoring
- mutation_target: harness.git_integration   (dotted MODULE only)
- files_touched: ["tests/harness/test_reset_external_engine_ref_invariant.py"]
- Submit the test file source directly (ordinary Python; no marker).
- verification_command: `python -m pytest tests/harness/test_reset_external_engine_ref_invariant.py -q`
- The oracle MUST build a REAL throwaway git repo in a tmp dir (`git init`, configure a user, commit a
  couple of commits, create a `janusmask/work` branch, simulate a master reset that leaves
  `janusmask/work` divergent), and with
  `cfg={"autowork":{"reset_external_engine":{"enabled":True}}}`, assert AT MINIMUM (all runtime/on-disk
  checks via `git rev-parse`/`git symbolic-ref`, never a scan of the test's own source):
  (a) RE-POINT: after `reset_external_engine(repo, base_sha, ...)` with a valid `base_sha`, `git rev-parse
      refs/heads/janusmask/work` equals the resolved `base_sha`, and the return indicates success; THEN a
      `git push . <descendant_sha>:refs/heads/janusmask/work` (descendant of base) SUCCEEDS (no
      non-fast-forward) — proving the wedge is cleared.
  (b) BAD-BASE REFUSE: with a bogus `base_sha` (e.g. `"deadbeef"*5` or a non-commit), the helper REFUSES
      (typed `bad_base`), the ref is UNCHANGED, nothing raises.
  (c) DEFAULT-OFF: with `config=None` (and separately `enabled` false), the helper REFUSES (typed
      `disabled`), the ref is UNCHANGED, nothing raises.
  (d) CHECKED-OUT BRANCH UNTOUCHED: the repo's currently checked-out branch ref and working tree are the
      same before and after the (enabled, valid) re-point.

Task 2 — the implementation:
- task_id MUST be exactly `reset-external-engine-ref-invariant-impl`.
- meta_task_type: harness_self_fix
- files_touched: ["harness/git_integration.py"]
- depends on `reset-external-engine-ref-invariant-oracle`.
- Emit a `__JANUSMASK_PATCHES__` (no manifest block).
- OMIT mutation_target. spec_author: null.
- verification_command:
  `python -m pytest tests/harness/test_reset_external_engine_ref_invariant.py tests/harness/test_merge_reroot.py -q`
  (the new test PLUS the existing merge-reroot regression exercising `merge_staging_to_parent`; scoped to
  the changed surface — NEVER the full adversarial suite).
- non_goals MUST contain the literal word `integration`. regression_tests >= 2.

# Required plan shape — wiring (acceptance)
`harness/git_integration.py` is already a live-reachable module; adding a top-level helper satisfies the
wire-up gate (orphan_unwired fires only for new MODULES). The helper is a manual-recovery utility and is
deliberately NOT wired into any live path. The apply CANNOT auto-approve (trust-core); it commits only with
the staged operator decision file named in `# Scope`.

# Implementation notes / hazards
- TRUST-CORE / DECISION FILE REQUIRED: `harness/git_integration.py` is in `_NEVER_AUTO_APPROVE`. Before
  dispatch, the OPERATOR must stage
  `state/control/decisions/reset-external-engine-ref-invariant-impl.json` with `"decision":"approve"`.
  Without it the apply is fail-closed (no commit). The brief author does NOT stage this.
- R-ANCHOR additive for the new top-level `reset_external_engine` symbol: reproduce an existing 1-part
  top-level anchor in `git_integration.py` byte-for-byte (e.g. `merge_staging_to_parent` — which you must
  leave behaviorally UNCHANGED) and append the new `def reset_external_engine(...)` as an allowed extra in
  the SAME patch entry; the new name must not collide.
- FF-ONLY LIVE PATH PRESERVED: do NOT add `--force` to the line 1912 push; the recovery helper uses
  `git update-ref` to re-point the ref, NOT a force-push, and only on the explicit manual-recovery call.
- DEFAULT-OFF FAIL-SAFE: `autowork.reset_external_engine.enabled` defaults false; disabled → refuse, no ref
  mutation. Contain every subprocess in try/except; never raise.
- NESTED-QUOTE HAZARD: emit `"""` (not `'''`) in any patched docstring; no backslash-escaped quotes.

# Sequencing note (do NOT act on this)
Do NOT add this brief's slug to `state/control/autowork/auto_promote.allowlist`. This brief is INDEPENDENT
of the purge briefs (different file/concern) but is LOWER priority (manual-recovery-only, edits trust-core).
Dispatch ONLY after: (1) the operator stages the decision file above, AND (2) the in-flight
`p11_build_evidence_perphase` work lands.
