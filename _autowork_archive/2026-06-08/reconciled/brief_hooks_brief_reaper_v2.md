---
interfaces: "tools/brief_reaper.py: reap_for_task(repo_root, task_id, *, stamp, archive=True) -> list[str]. Rewrite the reaper to decide 'integrated' from GROUND-TRUTH ledger evidence (never by re-running verification_command). Public signature unchanged. Stdlib only. Fully fail-safe."
meta_task_type: data_model
---

# Title

tools/brief_reaper.py

# ⚠️ WHOLE-FILE SUBMISSION — MODIFY ONLY reap_for_task, ADD NEW-NAMED HELPERS

`tools/brief_reaper.py` ALREADY EXISTS. Submit the COMPLETE file (whole-file
submission, NOT a `__JANUSMASK_PATCHES__` block). The auto-commit AST merge
PRESERVES any top-level symbol you omit and REJECTS a submission that modifies
MORE THAN ONE existing top-level function (`whole_file_drift` guard,
`git_integration.py:777`). Therefore:

- The ONLY existing top-level function you may change is **`reap_for_task`**.
- Put ALL new logic in **NEW helper functions with NEW names**. Do NOT redefine
  the existing helpers `_is_epic`, `_all_green`, `_distinct_commands`, `_move`
  (leave them as-is; they become unused — that is fine and expected).
- Keep the existing module constants `_FRONTMATTER_RE` and `_EPIC_RE`.
- Use distinct new names such as `_brief_is_epic`, `_plan_is_epic`,
  `_integrated_task_ids`, `_load_plan`, `_plan_task_ids`,
  `_find_brief_paired_plan`, `_move_no_clobber`.

# Scope — REBUILD the reaper on ground-truth integration evidence

The v1 reaper decided "the plan is integrated" by RE-RUNNING every distinct
`verification_command` via `subprocess.run(cmd, shell=True)` on the worker's hot
accept path. The 2026-06-08 adversarial review found this is wrong and dangerous:
a green-but-unbuilt sibling task triggers a PREMATURE archive; command
side-effects re-run at commit time; arbitrary `shell=True` injection surface; a
shared `task_id` archives the WRONG brief; the `no_diff` DONE class is missed;
destination collisions silently overwrite. Replace the heuristic with
ground-truth evidence.

## `reap_for_task(repo_root, task_id, *, stamp, archive=True) -> list[str]`

Archive a task's `brief_hooks_<slug>.md` + `plan_hooks_<slug>.json` from the
repo root IFF the brief's WHOLE plan is now integrated. NEVER execute a plan's
`verification_command` (no subprocess of plan data, no `shell=True`). A task is
"integrated" iff EITHER:

1. it is the `task_id` argument itself (it is being reaped because it just got
   accepted, so it counts implicitly); OR
2. `<repo_root>/state/impl_progress.jsonl` carries a terminal row for that
   task_id with `phase == 'accepted'` (an auto_commit integrate) or
   `event == 'no_diff'` (the brief was already satisfied — genuinely DONE).

Reap rules:
- Find the `plan_hooks_<slug>.json` whose `tasks` contain `task_id` AND that has
  a paired `brief_hooks_<slug>.md`. If there is not EXACTLY ONE such plan
  (zero, or an ambiguous shared task_id across several brief-paired plans),
  return `[]` — never archive the wrong brief.
- If the brief declares `epic: true` in frontmatter, OR the plan declares
  `plan_kind == 'epic'` / top-level `epic: true` (a decomposition record),
  return `[]` — epics and decomposition records are NEVER reaped.
- A plan with NO paired brief is not this function's concern -> `[]`
  (orphan-plan archival lives in the brief_status sweep).
- Reap IFF EVERY task_id in the plan is integrated per the rule above; if any
  sibling task is not yet integrated, return `[]` (no premature archive).
  - `archive=True`  -> move brief+plan into
    `repo_root/_autowork_archive/<stamp>/reconciled/`, REFUSING to overwrite an
    existing destination file (no silent clobber), and return `[slug]`.
  - `archive=False` -> classify only (return `[slug]`, move nothing).
- Fail-safe: wrap the whole body so ANY error returns `[]` and NEVER raises.

For the move helper: prefer `git mv` for a tracked source; for an untracked
source fall back to `shutil.move` then a best-effort `git add` of the
destination so the working tree stays git-consistent (the v1 silent-untracked-
move was a data-integrity gap). If the destination already exists, skip the move
(do not overwrite).

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose):
- meta_task_type: data_model
- files_touched: ["tools/brief_reaper.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/tools/test_brief_reaper.py -q"
- spec_author: null
- IMPL-only: the oracle `tests/tools/test_brief_reaper.py` is a PRE-COMMITTED
  precondition — author/edit NO test; touch no other file.
- The task spec.non_goals MUST contain the literal word "integration".
- test_spec MUST carry >=2 regression_tests reflecting the edge cases below.

# Inputs

The contract is the committed oracle `tests/tools/test_brief_reaper.py`. It seeds
a throwaway repo under tmp_path with brief+plan pairs and writes the integration
ledger `state/impl_progress.jsonl` directly. READ it as the source of truth.

# Non-Goals

INTEGRATION is out of scope — do NOT import from `harness/**`, do NOT read
config, do NOT spawn a real build, and do NOT run any plan's
`verification_command`. Stdlib only (json, re, shutil, subprocess, pathlib).
No network, no global state, no module-level side effects. Touch no file other
than `tools/brief_reaper.py`. The ONLY subprocess calls allowed are `git mv` /
`git add` for the move helper (arg-list, never `shell=True`).

# Edge Cases

- Single-task plan: the just-accepted task counts implicitly -> archived
  (regression test).
- Two-task plan, only one integrated: NOT archived (no premature archive)
  (regression test).
- Two-task plan, sibling integrated via ledger (`phase==accepted` or
  `event==no_diff`): archived.
- Epic brief / `plan_kind==epic` record: never reaped.
- Shared task_id across two brief-paired plans: ambiguous -> `[]`.
- Reaper NEVER executes a plan's verification_command (a side-effecting command
  must not run).
- Destination collision: existing archived file is not overwritten.
- archive=False: classify only, move nothing.
- Orphan plan with no brief: `[]`.
- Malformed plan JSON / missing repo: `[]`, never raises.

# Deliverables

`tools/brief_reaper.py`, GREEN under
`python -m pytest tests/tools/test_brief_reaper.py -q` (14/14), with ONLY
`reap_for_task` changed among existing functions and all new logic in
new-named helpers.
