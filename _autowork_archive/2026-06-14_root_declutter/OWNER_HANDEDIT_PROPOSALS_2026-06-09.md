# Owner hand-edit proposals — irreducible-tier defects (HANDOFF §4)

**Authored:** 2026-06-09 session. Both targets are `_NEVER_AUTO_APPROVE` files — per the cardinal
rule these are **owner hand-edits only**; do not dispatch through the pipeline. Diagnoses verified
against the current tree at `32abe32`.

---

## §4a — CONFIRMED: BYPASS_FUZZER tasks get the patches prompt even when creating a NEW file

**Target:** `harness/orchestrator.py:1519` (inside `prepare_task_prompt`, `:1479`).

**Verified current code:**
```python
    files_touched = task.get('files_touched') or []
    mtt = task.get('meta_task_type') or task.get('constraints', {}).get('meta_task_type')
    use_manifest = _requires_verbatim_manifest(files_touched)
    # BYPASS_WHOLE_FILE (2026-05-28): fall back to partial_edit patches for fuzzer-bypassed tasks
    if (task.get('partial_edit') or mtt in BYPASS_FUZZER_TYPES) and not use_manifest:
```

The patches (`__JANUSMASK_PATCHES__`) dispatch is selected whenever the meta-type bypasses the
fuzzer, regardless of whether the target exists. Patches cannot CREATE a file
(`git_integration.py:~1400`), so a `harness_plumbing` task creating a new single file dead-ends at
`auto_commit_failed` (observed on `crossover_impl`, worked around via a loud whole-file brief
directive).

**Minimal patch** (one guard variable + one condition change; `Path` and `PROJECT_DIR`
(`from harness.paths import PROJECT_ROOT as PROJECT_DIR`, `:42`) are already imported):

```python
    files_touched = task.get('files_touched') or []
    mtt = task.get('meta_task_type') or task.get('constraints', {}).get('meta_task_type')
    use_manifest = _requires_verbatim_manifest(files_touched)
    _pe_candidates = files_touched if isinstance(files_touched, list) else [files_touched]
    _targets_exist = bool(_pe_candidates) and all(
        isinstance(p, str) and (Path(PROJECT_DIR) / p).exists() for p in _pe_candidates)
    # BYPASS_WHOLE_FILE (2026-05-28): fall back to partial_edit patches for fuzzer-bypassed tasks
    # NEW-FILE GUARD (2026-06-09): never offer patches when any target does not yet exist —
    # patches cannot create files; fall through to the whole-file prompt.
    if (task.get('partial_edit') or mtt in BYPASS_FUZZER_TYPES) and not use_manifest and _targets_exist:
```

**Caveat for external builds** (`working_dir`/NGv2): targets resolve against this repo, so an
external existing file looks absent → whole-file prompt. That is the SAFE direction (whole-file can
both create and replace); if you want exactness, resolve against the task's `working_dir` when
present.

**Suggested regression oracle (hand-authored test, allowed):** a `harness_plumbing` task with
`files_touched=["autocompiler/zz_new.py"]` (absent) gets NO `__JANUSMASK_PATCHES__` block in its
prompt; the same task pointed at an existing file still gets it.

---

## §4b — REVISED DIAGNOSIS: the stale 0-byte `git_commit.lock` is (now) mostly benign residue

The handoff describes the 0-byte lock as wedging the daemon. **Code inspection does not support
that for the current tree:**

- **Daemon side** (`autowork_daemon.py:1953` `_acquire_commit_lock_or_reclaim`): non-blocking
  `flock` retry loop bounded by `deadline_sec`, then probes the stamped owner PID; dead/absent/
  0-byte owner ⇒ reclaim. A dead holder's `flock` is auto-released by the kernel, so the first
  `LOCK_NB` simply succeeds. This path cannot wedge on a dead process.
- **Worker side** (`orchestrator.py:2928`): `with open(lock_path, 'a') as lock_fd:
  fcntl.flock(lock_fd, fcntl.LOCK_EX)` — **unbounded blocking** flock. A *dead* holder releases
  automatically, so the 0-byte file alone cannot block it either.
- No code path checks the lock file's *existence*; the file lingering on disk is cosmetic.

**Residual real risk:** a **live but hung** holder (e.g. a worker stuck in a verification
subprocess that was supposed to run unlocked but regressed, or a wedged push under
`_maybe_push_and_rebase_pin`) blocks the worker-side `LOCK_EX` **forever** — that is the one wedge
the current code still permits.

**Minimal patch if you want it closed:** bound the worker-side acquisition at
`orchestrator.py:2928-2929` the same way the daemon's is — `LOCK_NB` retry loop with a deadline
(e.g. 60 s), then fail the commit attempt cleanly as `auto_commit_failed` (it already has retry
machinery) instead of hanging the worker. Optionally stamp the PID (the daemon's `_stamp` idiom)
for observability.

**Recommendation:** treat §4b as LOW priority / observability-only. The historical wedges predate
`_acquire_commit_lock_or_reclaim`; this session's 0-byte lock was removed but would not have blocked
anything. Closing the live-hung-holder hole is a nice-to-have.

---

*Prepared per the cardinal rule: presented for owner hand-edit, not dispatched. The §1–§3 planner
fixes are being landed through the pipeline separately.*

---

## ✅ COMPLETED 2026-06-10 — both hand-edits applied with owner authorization

- **§4a APPLIED** — the NEW-FILE GUARD (`_targets_exist`) landed in
  `prepare_task_prompt` exactly as proposed. Regression oracle (hand-authored, allowed):
  `tests/adversarial/test_prompt_newfile_guard.py` (7 tests — absent target / `partial_edit` /
  existing target / mixed-multi-file / empty-list / wiring assertion). Three stale test fixtures
  that named absent paths (`a.py`, `harness/webui_control.py` → real path is
  `tools/webui_control.py`) were updated to existing files.
- **§4b APPLIED** (the nice-to-have closed) — worker-side acquisition is now the bounded
  `_acquire_git_commit_lock_bounded` (LOCK_NB retry, 60 s deadline via
  `_GIT_COMMIT_LOCK_DEADLINE_SEC`, PID stamp on acquire). On timeout the attempt fails cleanly:
  `git_commit_lock_timeout` ledger row + synthesized `{'committed': False, ...}` result routed
  through the existing not-committed handler (same idiom as the INV5 TOCTOU abort). Oracle:
  `tests/adversarial/test_commit_lock_bounded.py` (4 tests — acquire+stamp / live-holder bounded
  timeout / dead-holder no-block / wiring assertion that the bare blocking `LOCK_EX` is gone).

The 4 remaining `tests/test_orchestrator.py` BYPASS_WHOLE_FILE failures
(multi-file fixtures asserting patches) are **pre-existing baseline** — superseded by the
2026-06-08 manifest-routing fix (`8758270`), unrelated to §4a/§4b, verified identical against the
pre-edit tree.
