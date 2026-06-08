---
interfaces: "tools/brief_status.py: classify_briefs(repo_root) -> list[dict] (one {'slug','status','detail'} per root brief / orphan plan, status derived from ground truth) and status_of(repo_root, slug) -> str|None (the status of one slug). Pure-stdlib, single-file, self-contained. Fail-safe over malformed inputs."
meta_task_type: data_model
---

# Title

tools/brief_status.py

# ⚠️ NEW FILE — WHOLE-FILE SUBMISSION REQUIRED

`tools/brief_status.py` DOES NOT EXIST YET. Submit the COMPLETE file as a single
self-contained Python module: a module docstring, then ALL imports at the TOP of
the file (`json`, `re`, `subprocess`, `sys`, `from pathlib import Path`), then the
function definitions (plus any small private top-level helpers). Do NOT emit a
`__JANUSMASK_PATCHES__` block and do NOT bury imports inside functions — a symbol
patch cannot create a file that does not exist. Write the whole module.

# Scope

CREATE a NEW single-file, stdlib-only module `tools/brief_status.py` — the
ground-truth brief classifier used as a pre-dispatch guard (so the pipeline never
spends a build cycle on a brief whose work is already done, and so genuinely
planless leaves are surfaced rather than sitting invisibly). Expose TWO public
functions.

## `classify_briefs(repo_root) -> list[dict]`

Coerce `repo_root` to `pathlib.Path`. Scan `repo_root` for `brief_hooks_*.md`
(slug = the stem after `brief_hooks_`, before `.md`) and `plan_hooks_*.json`
(slug = stem after `plan_hooks_`, before `.json`). Return ONE dict per brief and
per orphan-plan, each `{'slug': str, 'status': str, 'detail': str}`:

- brief frontmatter (the leading `---`...`---` block) has `epic: true`
  -> status `'EPIC'`.
- brief HAS a matching plan: collect the DISTINCT `verification_command` strings
  across that plan's `tasks`; run each via
  `subprocess.run(cmd, shell=True, cwd=str(repo_root))` (suppress output,
  timeout ~600s). If every command exits 0 -> `'DONE'`; if any is non-zero /
  errors / times out -> `'PENDING'`; if the plan has NO usable command -> `'PENDING'`.
- brief has NO matching plan: parse a best-effort `verification_command` from the
  brief body (an explicit `verification_command: "..."`, else the first
  `python -m pytest ...` line). If found AND green -> `'DONE'` (built, plan not
  kept); otherwise -> `'NEEDS-PLAN'`.
  ⚠️ PARSING GOTCHA: the quoted value MAY ITSELF CONTAIN double quotes — e.g.
  `verification_command: "python -c "import sys; sys.exit(0)""`. Capture GREEDILY
  from the first quote after the colon to the LAST quote on that line
  (`r'verification_command\s*:\s*"(.+)"\s*$'` with `re.MULTILINE`), NOT a
  `[^"]+` character class — that truncates at the first inner quote and yields a
  broken `python -c ` command. The captured value is run verbatim via
  `shell=True`, so the inner quotes must be preserved.
- a `plan_hooks_<slug>.json` with NO matching `brief_hooks_<slug>.md`
  -> status `'ORPHAN-PLAN'`.

The `detail` is a short human string (e.g. `'2 oracle(s) green @HEAD'`,
`'leaf with no plan'`, `'plan with no brief'`); its exact text is not asserted.

## `status_of(repo_root, slug) -> str | None`

Convenience: return just the status string for one `slug` (run the same
ground-truth logic for that slug only). Return `None` if neither a
`brief_hooks_<slug>.md` nor a `plan_hooks_<slug>.json` exists. Used by callers
that only need "is brief X already DONE?".

# Required plan shape

Emit EXACTLY ONE task (do NOT decompose):
- meta_task_type: data_model
- files_touched: ["tools/brief_status.py"]  (this file ONLY)
- verification_command: "python -m pytest tests/tools/test_brief_status.py -q"
- spec_author: null
- IMPL-only: the oracle `tests/tools/test_brief_status.py` is a PRE-COMMITTED
  precondition — author/edit NO test; touch no other file.
- The task spec.non_goals MUST contain the literal word "integration".
- test_spec MUST carry >=2 regression_tests reflecting the edge cases below.

# Inputs

The contract is the committed oracle `tests/tools/test_brief_status.py`. It seeds
a throwaway repo under tmp_path with brief+plan pairs whose `verification_command`
is a trivial `python -c "import sys; sys.exit(N)"` (N=0 green, N=1 red) and asserts
the status per slug. READ it as the source of truth.

# Non-Goals

INTEGRATION is out of scope — do NOT import from `harness/**`, do NOT read config,
do NOT move/delete files (this module only CLASSIFIES; archival lives in
`tools/brief_reaper.py`), do NOT spawn a real build. Stdlib only (json, re,
subprocess, sys, pathlib). No network, no global state, no module-level side
effects. Touch no file other than `tools/brief_status.py`.

# Edge Cases

- Red plan (a verification_command exits non-zero): `'PENDING'` (regression test).
- Epic brief: `'EPIC'` regardless of any plan (regression test).
- Planless brief whose own brief-body oracle is green: `'DONE'`.
- Planless brief with no usable command: `'NEEDS-PLAN'`.
- Plan with no brief: `'ORPHAN-PLAN'`.
- Malformed plan JSON: skipped without raising (the brief still classifies; do
  not crash).
- `status_of` for an unknown slug: `None`.

# Deliverables

`tools/brief_status.py`, GREEN under
`python -m pytest tests/tools/test_brief_status.py -q`.
