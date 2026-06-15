---
interfaces: "rewrites harness/autowork_parallelism.py so can_run_parallel serializes two tasks whose resolved working_dir lands in the SAME isolated external root (exact resolved-path membership in a new module-level _ISOLATED_EXTERNAL_DIRS = frozenset({'/home/xnihil0zer0/NobleGreedv2'}), via a new top-level helper _get_project_dir) while JM self-tasks (no working_dir, or a working_dir resolving inside this repo) remain fully parallelizable — making the committed oracle tests/test_autowork_parallelism.py GREEN"
---

# Title

harness/autowork_parallelism.py — add external-project isolation to `can_run_parallel`: two tasks whose resolved `working_dir` lands in the SAME isolated external root (exact resolved-path membership in `_ISOLATED_EXTERNAL_DIRS`, never a substring test) serialize; JM self-tasks stay fully parallelizable.

# Scope

EDIT the EXISTING module harness/autowork_parallelism.py (JM self task — no working_dir). CONTRACT (owner-settled 2026-06-11): two tasks whose resolved `working_dir` lands in the SAME external root serialize — they share one mutable repo root whose EXTERNAL_DIRTY_GATE reads shared state (empirically: multiple `worker_crash_orphan` blocks from dirty-root races during the bounty-FSM epic). JM self-tasks (no `working_dir`, or a `working_dir` resolving inside this repo) are EXEMPT — they are fully worktree-isolated already, so both-`working_dir`-absent ⇒ parallelize. Isolation membership is decided by EXACT resolved-path comparison against a module-level `_ISOLATED_EXTERNAL_DIRS = frozenset({'/home/xnihil0zer0/NobleGreedv2'})`, tested on `_get_project_dir`'s resolved output — NEVER a substring test (a substring match would isolate/exempt ANY path containing "NobleGreedv2" anywhere, e.g. a fixtures dir named `NobleGreedv2-samples` inside JM).

⚠️ The staged baseline of this file (working-tree content) contains an INVERTED draft of this feature (it serializes same-project tasks generally and exempts paths CONTAINING the substring "NobleGreedv2"). That draft is WRONG on both counts — do not preserve its `if "NobleGreedv2" not in proj_a` logic or its `wd_a or wd_b` precondition. Replace the file with the EXACT corrected content pinned in the DISPATCH DIRECTIVE below.

`_files_overlap`, `transitive_deps`, `_normalize_path`, and all the existing `can_run_parallel` checks (same-task-id, conservative missing files_touched, file overlap, transitive dependency edges) are UNCHANGED — the external-isolation check is inserted immediately after the same-task-id check and before the files_touched logic. `_get_project_dir` is a NEW top-level helper (present in the staged baseline — keep its body exactly as pinned below). `import pathlib` moves to the module top (the staged baseline has it mid-file).

DISPATCH DIRECTIVE — PATCH FORMAT (MANDATORY — WHOLE-FILE): this change adds a NEW top-level symbol (`_get_project_dir`) plus a module-level constant, and new-symbol + symbol-patch is a known auto_commit_failed shape. Emit the COMPLETE replacement file for `harness/autowork_parallelism.py` (whole-file emission — NEVER a `__JANUSMASK_PATCHES__` symbol patch, never a manifest, never a dotted qualname). The file is 92 lines — reproduce it BYTE-FOR-BYTE exactly as follows:

    from __future__ import annotations

    import pathlib

    # External roots whose tasks must serialize: tasks resolving to the SAME root in
    # this set share one mutable repo whose EXTERNAL_DIRTY_GATE reads shared state.
    # Membership is EXACT resolved-path comparison — never a substring test.
    _ISOLATED_EXTERNAL_DIRS = frozenset({'/home/xnihil0zer0/NobleGreedv2'})

    def _files_overlap(a_files: list[str], b_files: list[str]) -> bool:
        a_norm = [_normalize_path(p) for p in a_files]
        b_norm = [_normalize_path(p) for p in b_files]
        for ai, ai_is_dir in a_norm:
            for bj, bj_is_dir in b_norm:
                if ai == bj:
                    return True
                if ai_is_dir and bj.startswith(ai):
                    return True
                if bj_is_dir and ai.startswith(bj):
                    return True
        return False

    def transitive_deps(task_id: str, all_tasks: list[dict]) -> set[str]:
        idx = {t['task_id']: t for t in all_tasks if isinstance(t.get('task_id'), str)}
        if task_id not in idx:
            return set()
        visited: set[str] = {task_id}
        result: set[str] = set()
        queue: list[str] = list(idx[task_id].get('dependencies') or [])
        while queue:
            dep = queue.pop(0)
            if dep in visited:
                continue
            visited.add(dep)
            result.add(dep)
            if dep in idx:
                for next_dep in idx[dep].get('dependencies') or []:
                    if next_dep not in visited:
                        queue.append(next_dep)
        return result

    def _get_project_dir(task: dict) -> str:
        wd = task.get('working_dir')
        repo_root = pathlib.Path(__file__).resolve().parent.parent
        if not wd:
            return str(repo_root.resolve())
        try:
            resolved = pathlib.Path(wd).resolve()
            repo_root_resolved = repo_root.resolve()
            if resolved == repo_root_resolved or repo_root_resolved in resolved.parents or resolved in repo_root_resolved.parents:
                return str(repo_root_resolved)
            return str(resolved)
        except Exception:
            return str(repo_root.resolve())

    def can_run_parallel(task_a: dict, task_b: dict, all_tasks: list[dict] | None=None, *, conservative_missing_files: bool=True) -> bool:
        if task_a.get('task_id') == task_b.get('task_id'):
            return False

        # External-project isolation: two tasks resolving to the SAME isolated
        # external root serialize. JM self-tasks (no working_dir, or a working_dir
        # resolving inside this repo) are exempt — they are worktree-isolated.
        proj_a = _get_project_dir(task_a)
        proj_b = _get_project_dir(task_b)
        if proj_a == proj_b and proj_a in _ISOLATED_EXTERNAL_DIRS:
            return False

        a_files = task_a.get('files_touched')
        b_files = task_b.get('files_touched')
        if conservative_missing_files:
            if not isinstance(a_files, list) or not a_files or (not isinstance(b_files, list)) or (not b_files):
                return False
        if isinstance(a_files, list) and isinstance(b_files, list):
            if _files_overlap(a_files, b_files):
                return False
        if all_tasks is not None:
            a_id = task_a.get('task_id')
            b_id = task_b.get('task_id')
            if a_id in transitive_deps(b_id, all_tasks):
                return False
            if b_id in transitive_deps(a_id, all_tasks):
                return False
        return True

    def _normalize_path(p: str) -> tuple[str, bool]:
        is_dir = p.endswith('/')
        stripped = p.rstrip('/') if is_dir else p
        canonical = str(pathlib.Path(stripped).resolve())
        return (canonical + '/', True) if is_dir else (canonical, False)

POST-EMIT SELF-CHECK (mandatory): your emitted file must contain exactly FOUR top-level `def`s (`_files_overlap`, `transitive_deps`, `_get_project_dir`, `can_run_parallel`, plus `_normalize_path` — five total), ONE module-level constant `_ISOLATED_EXTERNAL_DIRS`, `import pathlib` at the top, NO occurrence of the substring test `"NobleGreedv2" not in`, and the exact line `if proj_a == proj_b and proj_a in _ISOLATED_EXTERNAL_DIRS:`.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle and the operator decision file are keyed to it): `task_id`: `concurrency_isolation`. meta_task_type=`harness_self_fix` (production harness edit — bypass_fuzzer + skip_smoke_gates per META_TASK_POLICY; the operator decision file at state/control/decisions/concurrency_isolation.json authorizes the harness/** write). priority: high. dependencies: []. working_dir: ABSENT (JM self task — do NOT set it). files_touched: `["harness/autowork_parallelism.py"]` ONLY. partial_edit semantics: WHOLE-FILE single-file emission per the DISPATCH DIRECTIVE — the DISPATCH DIRECTIVE — PATCH FORMAT paragraph above (including the full pinned file content) MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python3 -m pytest -q tests/test_autowork_parallelism.py`. The committed RED oracle tests/test_autowork_parallelism.py (JM commit d574679) is the authoritative acceptance contract — make it GREEN (9 tests); do NOT author new tests. `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle (plan descriptors referencing committed tests — this does NOT authorize authoring new tests), so every `spec.edge_cases` entry is reflected per the validator's edge-case rule (e.g. `test_project_isolation`, `test_project_isolation_exact_path`, `test_transitive_deps_cycle`).

# Non-Goals

Do NOT touch harness/config.yaml (`parallel_cap` stays 5 — owner decision: JM self-task serialization REJECTED; per-project serialization of worktree-isolated self-tasks is strictly more pessimistic than the existing protections). Do NOT touch harness/autowork_daemon.py, harness/orchestrator.py, harness/git_integration.py, or any other module. Do NOT author or modify any test — the oracle is committed and authoritative. Do NOT implement general same-project serialization (only exact membership in `_ISOLATED_EXTERNAL_DIRS` isolates). Do NOT use substring matching on paths. Do NOT add new dependencies, network, wall-clock, randomness, or logging. Do NOT change the signatures of `can_run_parallel`, `transitive_deps`, `_files_overlap`, or `_normalize_path`. Integration/e2e testing is out of scope — verified solely by the committed unit oracle.

# Inputs

The committed authoritative oracle tests/test_autowork_parallelism.py (JM commit d574679; currently RED on the staged baseline: `test_project_isolation` and `test_project_isolation_exact_path` fail). It pins: (i) two tasks with `working_dir: '/home/xnihil0zer0/NobleGreedv2'` (disjoint files) ⇒ `can_run_parallel` False; (ii) both-`working_dir`-absent, disjoint files ⇒ True; (iii) one external + one bare self-task ⇒ True; JM-repo-root `working_dir` on both ⇒ True; (iv) `test_project_isolation_exact_path`: two tasks sharing `working_dir: '/home/xnihil0zer0/JanusMaskJR/fixtures/NobleGreedv2-samples'` ⇒ True, and two tasks sharing `working_dir: '/home/xnihil0zer0/NobleGreedv2-other'` ⇒ True (substring-containing paths are NOT isolated); (v) all pre-existing file-overlap / dependency / conservative-missing-files cases unchanged and green. The staged baseline (read-only at `{WORK_DIR}/inbox/targets/harness/autowork_parallelism.py`) already contains `_get_project_dir` with the exact body pinned above; its `can_run_parallel` isolation block and mid-file `import pathlib` are the parts being corrected. stdlib only (`pathlib`).

# Deliverables

Rewritten harness/autowork_parallelism.py exactly as pinned in the DISPATCH DIRECTIVE: module-level `_ISOLATED_EXTERNAL_DIRS = frozenset({'/home/xnihil0zer0/NobleGreedv2'})`, top-level `_get_project_dir`, and a `can_run_parallel` whose external-isolation check serializes only exact-resolved-path matches inside `_ISOLATED_EXTERNAL_DIRS` while leaving every other admission rule byte-identical. Verified GREEN by `python3 -m pytest -q tests/test_autowork_parallelism.py` (9 passed).
