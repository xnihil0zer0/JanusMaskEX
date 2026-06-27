# A.1 DEP-GATE LEAK — analysis

Target: `harness/autowork_daemon.py::_brief_dep_gate_ok` (def at **L1637**, the
loop body at **L1685–1698**). Caller: `_decide` at **L1708**
(`candidates = [c for c in candidates if _brief_dep_gate_ok(c, status_records, repo_root)]`).
State strings come from `harness/brief_status.py::compute_brief_status`
(L57–70): `unplanned, planned, blocked, in_flight, complete, zombie, queued`.
"Fully accepted" is represented as `task_ids` non-empty AND `remaining` empty
(equivalently `state == 'complete'`).

## EXACT CURRENT LOGIC (the leak), L1685–1699

```python
for dep in dep_slugs:
    if dep == owner_slug:
        continue
    rec = by_slug.get(dep)
    if rec is None:            # <-- LEAK 1: absent/never-planned -> RELEASE
        continue
    state = rec.get('state')
    if state in ('blocked', 'zombie'):   # <-- LEAK 2: not-complete -> RELEASE
        continue
    remaining = rec.get('remaining')
    task_ids = rec.get('task_ids') or []
    if task_ids and (not remaining):     # genuine ACCEPTED -> release (correct)
        continue
    return False               # only path that HOLDS
return True
```

A dependent is released whenever its dependency is merely **absent**
(not-yet-dispatched/planned) or **blocked/zombie** (un-accepted work). On a
fresh 2-task plan (impl + paired `test_authoring` oracle, oracle frontmatter
`dependencies: [impl-slug]`), at plan-time the impl record does not exist →
`rec is None` → the oracle is released and dispatched BEFORE the impl lands.
Premature release.

## EXACT INTENDED LOGIC

Release a dependent ONLY when the dependency is a genuine terminal-ACCEPTED
brief (`task_ids` non-empty AND `remaining` empty). Absent /
not-yet-dispatched / blocked / zombie all mean "the dep has not COMPLETED
yet" → HOLD (`return False`). A true unbreakable deadlock is surfaced via
explicit telemetry, NOT a silent state-based release.

```python
for dep in dep_slugs:
    if dep == owner_slug:
        continue
    rec = by_slug.get(dep)
    if rec is None:
        # absent / not-yet-dispatched: dependency has NOT completed -> HOLD.
        return False
    remaining = rec.get('remaining')
    task_ids = rec.get('task_ids') or []
    if task_ids and (not remaining):
        # genuine terminal-ACCEPTED dependency -> released.
        continue
    # exists but not fully accepted (queued/in_flight/blocked/zombie) -> HOLD.
    return False
return True
```

## PRECISE CONDITIONAL CHANGE (minimal)

1. **L1689–1690**: `if rec is None: continue` → `if rec is None: return False`
   (absent dep must HOLD).
2. **L1692–1693**: DELETE the `if state in ('blocked', 'zombie'): continue`
   block (a blocked/zombie dep has un-accepted work → must fall through to the
   `return False` HOLD path, not release). `state = rec.get('state')` line
   becomes unused and may be dropped.

Net: the ONLY `continue` that survives in the loop is the genuine-ACCEPTED one
(`if task_ids and not remaining`). Every non-accepted/absent dep reaches
`return False`. The docstring's "DEADLOCK-SAFE … absent/blocked falls back to
DISPATCH" must be rewritten to "absent/blocked/zombie HOLD; only a
terminal-ACCEPTED dep releases".

## DEADLOCK-SAFETY NOTE (for the worker)

The original silent release was the (over-broad) deadlock escape. Replacing it
with a HOLD is correct for A.1 because a dep that has not completed should
never release its dependent. If genuine-deadlock telemetry is desired it is an
ADDITIVE, non-releasing log emission — out of scope for this minimal fix
(integration concern). The error-degrades-to-True wrappers (the two `except
Exception: return True`) are PRESERVED unchanged so a malformed brief/record
can never wedge the daemon.

## TEST IMPACT (orchestrator must verify the UNION)

The fix flips behaviour that the EXISTING committed oracle
`tests/harness/test_brief_level_dep_gate.py` pins as PASS:
  * `test_absent_dep_slug_does_not_deadlock` (absent dep → True) — now WRONG.
  * `test_terminally_blocked_dep_does_not_deadlock` (blocked dep → True) — now WRONG.

Both must be UPDATED by the fix to assert HOLD (`False`) for the not-completed
dependency, consistent with the new A.1 oracle
`tests/harness/test_dep_gate_no_premature_release.py`. The other 3 cases in the
old oracle (`test_unmet_brief_dep_holds_dispatch`, `test_met_brief_dep_allows_dispatch`,
`test_no_declared_deps_is_dispatchable`) stay GREEN unchanged. Editing test
files is permitted (tests/oracles are hand-authorable); the fix's
verification_command must run BOTH oracle files so the worker proves the union.
```
