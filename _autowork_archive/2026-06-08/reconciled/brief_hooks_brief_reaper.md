---
interfaces: "tools/brief_reaper.py: reap_for_task(repo_root, task_id, *, stamp, archive=True) -> list[str]. Pure-stdlib, single-file, self-contained. Returns the list of archived brief slugs (0 or 1). NEVER raises."
meta_task_type: data_model
---

# Title

tools/brief_reaper.py

# ⚠️ NEW FILE — WHOLE-FILE SUBMISSION REQUIRED

`tools/brief_reaper.py` DOES NOT EXIST YET. Submit the COMPLETE file as a single
self-contained Python module: a module docstring, then ALL imports at the TOP of
the file (`json`, `re`, `shutil`, `subprocess`, `sys`, `from pathlib import
Path`), then the `def reap_for_task(...)` definition (plus any small private
top-level helpers you want). Do NOT emit a `__JANUSMASK_PATCHES__` block, and do
NOT bury the imports inside the function body — a patch block / symbol patch is
ONLY for editing an existing large file, and this file does not exist, so a
symbol patch cannot create it. Write the whole module.

# Scope

CREATE a NEW single-file, whole-file, stdlib-only module `tools/brief_reaper.py`
exposing ONE public function:

    reap_for_task(repo_root, task_id, *, stamp, archive=True) -> list[str]

This is the targeted half of "archive-on-integrate": when a build task lands,
the worker calls this with the integrated `task_id`; the function archives that
task's brief+plan paperwork from the repo root IFF the whole plan is now
integrated (all its oracles green). It MUST be fully fail-safe — any error
returns `[]` and never raises, because it runs on the worker's hot accept path.

# Required behaviour

`repo_root` is a path (str or pathlib.Path). `task_id` is a string. `stamp` is a
keyword-only date string (e.g. "2026-06-08"). `archive` is a keyword-only bool.

1. Coerce `repo_root` to a `pathlib.Path`. If it does not exist / is not a dir,
   return `[]`.
2. LOCATE the plan: scan `repo_root/plan_hooks_*.json`. Parse each as JSON
   (skip any that fail to parse). The matching plan is the first whose
   `data['tasks']` list contains a task dict with `task['task_id'] == task_id`.
   Derive its `slug` from the filename: `plan_hooks_<slug>.json`. If no plan
   matches, return `[]`.
3. EPIC GUARD: if `repo_root/brief_hooks_<slug>.md` exists and its YAML
   frontmatter (the block delimited by leading `---` lines) declares
   `epic: true`, return `[]` (epics decompose via children and are never reaped).
4. COLLECT the DISTINCT `verification_command` strings across ALL tasks in the
   matched plan (preserve order, drop blanks/dupes). If there are none, return
   `[]` (cannot prove integration).
5. RUN each command with `subprocess.run(cmd, shell=True, cwd=str(repo_root))`,
   suppressing stdout/stderr, with a timeout (e.g. 600s). The plan is GREEN iff
   EVERY command exits 0. A timeout / OSError counts as NOT green.
6. If NOT green, return `[]` (still building).
7. If green:
   - `archive=False`: return `[slug]` WITHOUT moving anything (dry classify).
   - `archive=True`: ensure `repo_root/_autowork_archive/<stamp>/reconciled/`
     exists (mkdir parents). Move BOTH `brief_hooks_<slug>.md` (if present) and
     `plan_hooks_<slug>.json` into it. Prefer `git mv` (so tracked files keep
     rename history) and fall back to `shutil.move` when the file is untracked
     (git mv exits non-zero — most root briefs are untracked). Return `[slug]`.
8. Wrap the whole body so ANY unexpected exception results in `return []`
   (never propagate).

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose):
- meta_task_type: data_model
- files_touched: ["tools/brief_reaper.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/tools/test_brief_reaper.py -q"
- spec_author: null
- IMPL-only: the oracle `tests/tools/test_brief_reaper.py` is a PRE-COMMITTED
  precondition — author/edit NO test; touch no other file.
- The task spec.non_goals MUST contain the literal word "integration" (this leaf
  has no integration test of its own — the worker-wiring leaf covers that).
- test_spec MUST carry >=2 regression_tests reflecting the edge cases below.

# Inputs

The contract is the committed oracle `tests/tools/test_brief_reaper.py`. It seeds
a throwaway repo under tmp_path with `brief_hooks_<slug>.md` +
`plan_hooks_<slug>.json` whose `verification_command` is a trivial
`python -c "import sys; sys.exit(N)"` (N=0 green, N=1 red), then asserts the
move/no-move and return value. READ it as the source of truth.

# Non-Goals

INTEGRATION is out of scope — do NOT import or call anything from `harness/**`,
do NOT wire into the worker or orchestrator, do NOT read config, do NOT spawn a
real build. Stdlib only (json, pathlib, subprocess, shutil, re, sys). No network,
no global state, no module-level side effects. Touch no file other than
`tools/brief_reaper.py`. Do NOT compute the date yourself — `stamp` is always
passed in by the caller.

# Edge Cases

- Red oracle (a verification_command exits non-zero): NOT archived, files stay,
  return `[]` (regression test).
- Epic brief (`epic: true` frontmatter): never reaped even when green
  (regression test).
- `task_id` not present in any plan: no-op `[]`.
- Multi-task plan: integrating any one task reaps the brief once ALL the plan's
  commands are green (the function keys off the plan, not the single task).
- `archive=False`: returns `[slug]` but moves nothing.
- Malformed plan JSON / missing repo_root / subprocess failure: `[]`, no raise.

# Deliverables

`tools/brief_reaper.py`, GREEN under
`python -m pytest tests/tools/test_brief_reaper.py -q`.
