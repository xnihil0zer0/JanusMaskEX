# A.2 — Planner ignores the brief's pytest `verification_command`

## Symptom
For NEW-module / `harness_self_fix` leaves the planner-produced impl task carries
a WEAK `python -c "import <module>"` import-smoke even when a paired committed
oracle (`tests/**/test_<leaf>.py`) exists, so a buggy-but-importable module
ACCEPTs. (Refactor/edit tasks were unaffected because their LLM-drafted vcmd
already named the oracle file, which DID trip the rewrite.) This is the fuel for
the A.1 dep-gate leak.

## Exact current logic
File: `harness/planner/plan_normalizer.py`
Function: `_sanitize_impl_verification_commands(plan, repo_root=None)` (def at L179),
called from `normalize_plan` at L756.

The pass iterates non-`test_authoring` tasks and at **L234**:
```python
if not any((of in vcmd for of in oracle_files)):
    continue
```
i.e. it ONLY proceeds to the repo-aware existing-test lookup (L251-269) when the
impl's `verification_command` ALREADY contains the literal path of a sibling
`test_authoring` task's `files_touched`. A blind-drafted impl that emitted
`python -c "import <module>"` (the common new-module / self-fix case) names no
oracle file, so the guard `continue`s and the weak smoke survives — the paired
`tests/**/test_<leaf>.py` glob (L257) is never even consulted.

Empirically confirmed: with a fake repo containing `tests/pkg/test_widget.py`
and an impl whose vcmd is `python -c "import pkg.widget"`, `normalize_plan(...,
repo_root=repo)` leaves the vcmd unchanged.

## Exact intended logic
When an impl task's `verification_command` is an **import-smoke**
(`python -c "import ..."`) — or, more generally, names NO real pytest oracle —
AND `repo_root` is set AND a paired committed `tests/**/test_<leaf>.py` exists
for one of its importable touched modules, the pass MUST upgrade the command to
`python -m pytest <existing test(s)> -q`. A genuinely brand-new module with no
paired test still falls back to the import smoke; `repo_root=None` stays a pure
smoke check. The existing oracle-referencing rewrite path is unchanged.

## Precise change (single function, `_sanitize_impl_verification_commands`)
Replace the unconditional skip at L234 so the pass ALSO enters when the command
is an import-smoke that should be upgraded. Concretely, gate the existing
`continue` so it does NOT fire for an import-smoke command:

```python
        vcmd = t.get('verification_command')
        if not isinstance(vcmd, str) or not vcmd:
            continue
        references_oracle = any((of in vcmd for of in oracle_files))
        # A.2: also handle a WEAK import-smoke (python -c "import ...") that
        # names no oracle file — when a paired committed test exists on disk we
        # must still upgrade it to a real pytest gate, else a buggy-but-
        # importable new-module / harness_self_fix impl ACCEPTs vacuously.
        is_import_smoke = 'python -c' in vcmd and 'import' in vcmd
        if not references_oracle and not is_import_smoke:
            continue
```
The downstream block is unchanged: it computes `modules`/`leaves` from
`files_touched` (L236-250), and at L251 when `repo_root is not None and leaves`
globs `tests/**/test_<leaf>.py` (excluding oracle files) and, if found, sets
`python -m pytest <tests> -q` (L267-269). If NO paired test exists it falls to
the `if modules:` import-smoke fallback (L270-272) — which, for an
already-import-smoke command, is a byte-identical no-op, preserving the
brand-new-module and idempotency contracts. The token-strip tail (L273-277)
still only runs for oracle-referencing commands with no importable module.

Net: a new-module/self-fix impl is gated on its paired committed oracle whenever
one exists; brand-new modules and `repo_root=None` behaviour are unchanged.

## Oracle (RED on HEAD, committed)
`tests/planner/test_impl_vcmd_upgrades_import_smoke_to_paired_test.py`
- RED: `test_import_smoke_impl_upgraded_to_paired_committed_test`,
  `test_harness_self_fix_import_smoke_upgraded_to_paired_test`
- GREEN guards (both sides): brand-new-no-test stays smoke, repo_root=None stays
  smoke, idempotency.
Confirmed `2 failed, 3 passed` at HEAD.
