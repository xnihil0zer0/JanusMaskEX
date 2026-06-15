---
interfaces: "_purge_stale_sidecars_safe(payload: dict, state_dir=None) -> list[str] — fail-safe terminal-outcome purge of state/output/<tid>.{patches,files}.json; never raises"
---

# Title

Worker terminal-outcome purge of stale emission sidecars (harness/orchestrator_worker.py)

# Scope

Fix a retry-poisoning defect found 2026-06-09 during the autocompiler Phase-A run:
`commit_accepted_output` (harness/git_integration.py:610-699 — do NOT edit it, it is
`_NEVER_AUTO_APPROVE`) dispatches the accept path on SIDECAR EXISTENCE — a stale
`state/output/<task_id>.patches.json` routes to the patches path (which cannot create new files)
and a stale `<task_id>.files.json` routes to the multi-file path — so a FAILED attempt's leftover
sidecar deterministically hijacks and fails every retry of the same task (observed on
`crossover_impl` and `autocompiler-fitness-vector-contract`).

Cure at the ALLOWED seam: add ONE new module-level helper `_purge_stale_sidecars_safe(payload,
state_dir=None) -> list[str]` to `harness/orchestrator_worker.py`, an exact idiom-clone of the
adjacent `_reap_spent_briefs_safe` (`:45`) fail-safe bridge: on a NON-accept terminal payload
(`outcome` not in `('accepted', 'no_diff')`) best-effort unlink
`state_dir/output/<task_id>.patches.json` and `<task_id>.files.json`, return the removed filenames;
whole body try/except so it can NEVER raise; `state_dir=None` resolves `<repo_root>/state` via
`Path(__file__).resolve().parents[1] / 'state'`. Wire it with a ONE-LINE call inside the SMALL
`_print_json_line` (`:73`) immediately after the existing `_reap_spent_briefs_safe(payload)` call,
inside the same try/except.

meta_task_type=`harness_self_fix` (sensitive `harness/**` — operator decision file will be provided).
verification_command: `python -m pytest tests/test_worker_sidecar_purge.py tests/test_worker_sidecar_purge_wired.py -q`

# Required plan shape

ONE impl task; meta_task_type=`harness_self_fix`; files_touched=
`["harness/orchestrator_worker.py"]`; verification_command exactly as above (both oracle files are
PRE-COMMITTED and RED — their docstrings/assertions are the authoritative contract; do NOT author
tests); >=2 edge_cases mirrored in regression/property tests (e.g. (a) accepted/no_diff payload
leaves sidecars untouched, (b) missing output dir / garbage payload / non-dir state_dir returns []
and never raises, (c) only the named task's sidecars are removed, `<tid>.py` is preserved).
EMISSION: symbol patches editing the SMALL `_print_json_line` symbol, with the NEW top-level helper
`_purge_stale_sidecars_safe` riding as an R-ANCHORED trailing node of that same patch (the
documented new-top-level-symbol recipe). Do NOT rewrite `main()` or any large symbol; do NOT emit
whole-file or `__JANUSMASK_MANIFEST__` for this EDIT task.

# Inputs

Pre-committed RED oracles `tests/test_worker_sidecar_purge.py` + `tests/test_worker_sidecar_purge_wired.py`
(the authoritative contract). Idiom precedents to clone, in the SAME file:
`_reap_spent_briefs_safe` (`harness/orchestrator_worker.py:45`, the fail-safe terminal bridge) and
its call site in `_print_json_line` (`:73`). Defect mechanics: `commit_accepted_output` sidecar
dispatch at `harness/git_integration.py:610-699` (read-only context — never edit).

# Non-Goals

No integration changes beyond the single one-line `_print_json_line` call site (integration with the
daemon retry loop is exercised by the existing pipeline, not re-tested here). Do NOT edit
`harness/git_integration.py`, `harness/orchestrator.py`, or any `_NEVER_AUTO_APPROVE` file. Do NOT
purge sidecars on `accepted`/`no_diff` outcomes (they are consumed by the accept path). Do NOT
delete `<task_id>.py` or any other `state/output/` artifact — ONLY the two format-dispatch sidecars
of the terminal task. Do NOT author or modify tests (oracles pre-committed). Behaviour on the accept
path must stay byte-identical.

# Deliverables

EDIT `harness/orchestrator_worker.py`: new module-level `_purge_stale_sidecars_safe(payload,
state_dir=None) -> list[str]` + one-line invocation from `_print_json_line`. Turns
`tests/test_worker_sidecar_purge.py` and `tests/test_worker_sidecar_purge_wired.py` GREEN with zero
regressions elsewhere.
