---
dependencies: []
interfaces: "edits harness/autowork_daemon.py::_brief_dep_gate_ok(task, status_records, repo_root) -> bool so a dependent task is HELD (returns False) whenever its declared sibling-brief dependency has NOT genuinely completed (record absent / not-yet-dispatched / blocked / zombie / queued / in_flight), and is RELEASED (True) ONLY when the dependency is a terminal-ACCEPTED brief (task_ids non-empty AND remaining empty) or the owning brief declares no frontmatter deps -- making the committed oracles tests/harness/test_dep_gate_no_premature_release.py and tests/harness/test_brief_level_dep_gate.py GREEN"
---

# Title

harness/autowork_daemon.py — FIX DEFECT A.1 (dep-gate premature release): stop releasing a dependent whose sibling-brief dependency is merely absent / not-yet-dispatched / blocked / zombie; release ONLY on a genuine terminal-ACCEPTED dependency.

# Scope

EDIT the EXISTING module harness/autowork_daemon.py (JM self task — no working_dir). DEFECT A.1: the brief-level dep gate `_brief_dep_gate_ok` (def at L1637; loop body L1685–1699; called from `_decide` at L1708) currently RELEASES a dependent task whenever its dependency's status record is ABSENT (`rec is None` → `continue`) or its state is `'blocked'`/`'zombie'` (`if state in ('blocked','zombie'): continue`). Both are premature: an absent record means the dependency simply has not been dispatched/planned yet, and a blocked/zombie dependency still has un-accepted work — in neither case has the dependency COMPLETED. The canonical trigger: a fresh 2-task plan (an impl task + its paired `test_authoring` oracle whose brief frontmatter `dependencies: [impl-slug]`) — at plan-time the impl record does not exist, so the oracle's dep reads ABSENT and the oracle is dispatched BEFORE the impl lands.

FIX INTENT: a dependent must be HELD (return False) unless its dependency is a genuine terminal-ACCEPTED brief. PRESERVE the two `except Exception: return True` error-degrade-to-dispatch wrappers UNCHANGED (a malformed brief/record must never wedge the daemon). PRESERVE the early-True fast paths (non-dict task, no tid, no owning brief, no declared deps) byte-identical. Only the per-dep loop body changes.

Exactly ONE symbol changes: the body of `_brief_dep_gate_ok`. Apply as an R-ANCHORED SYMBOL PATCH targeting the 1-part qualname `_brief_dep_gate_ok` (NEVER whole-file: this file is ~2400 lines and whole-file emission gets paraphrased). The two changes inside the per-dep `for dep in dep_slugs:` loop:

1. `if rec is None: continue` → `if rec is None: return False` (absent / not-yet-dispatched dependency means NOT-completed → HOLD).
2. DELETE the `state = rec.get('state')` line and the `if state in ('blocked', 'zombie'): continue` block entirely. A blocked/zombie dependency has un-accepted work and must fall through to the existing `return False` HOLD path — the only surviving `continue` in the loop is the genuine-ACCEPTED one (`if task_ids and (not remaining): continue`).

The exact intended loop body (everything before `for dep in dep_slugs:` is byte-identical to the staged baseline):

    for dep in dep_slugs:
        if dep == owner_slug:
            continue
        rec = by_slug.get(dep)
        if rec is None:
            # DEFECT A.1: absent / not-yet-dispatched dependency has NOT
            # completed -> HOLD (a held task is re-evaluated next tick).
            return False
        remaining = rec.get('remaining')
        task_ids = rec.get('task_ids') or []
        # Released ONLY on a genuine terminal-ACCEPTED dependency.
        if task_ids and (not remaining):
            continue
        # Exists but not fully accepted (queued / in_flight / blocked /
        # zombie) -> still un-accepted work -> HOLD.
        return False
    return True

Also update the function's docstring so it no longer claims "absent / never-planned, or whose record is terminally blocked, falls back to DISPATCH" — replace that sentence with: absent / not-yet-dispatched / blocked / zombie dependencies all HOLD; a dependent is released ONLY on a genuine terminal-ACCEPTED dependency, and any error degrades to DISPATCH (True).

POST-EMIT SELF-CHECK (mandatory): the patch anchors qualname `_brief_dep_gate_ok` (1-part, top-level); the symbol still begins with the unchanged guard/owner-resolution/frontmatter-parse block and the two `except Exception: return True` wrappers; the per-dep loop contains NO reference to `rec.get('state')` and NO `('blocked','zombie')` literal; the loop's only `continue` statements are the `dep == owner_slug` skip and the `task_ids and (not remaining)` accepted-skip; both `if rec is None` (now `return False`) and the trailing exists-but-unaccepted `return False` are present; no other symbol of the module is named or modified; no module-level imports are added.

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the operator decision file at state/control/decisions/dep_gate_no_premature_release.json is keyed to it): `task_id`: `dep_gate_no_premature_release`. meta_task_type=`harness_self_fix` (production harness edit — a whole-file EDIT of an existing harness file routes through the harness_self_fix refactor path; bypass_fuzzer + skip_smoke_gates per META_TASK_POLICY; the decision file authorizes the harness/** protected-path write). priority: high. dependencies: []. spec_author: null. working_dir: ABSENT (JM self task — do NOT set it). files_touched: `["harness/autowork_daemon.py"]` ONLY. partial_edit semantics: R-ANCHORED SYMBOL PATCH targeting `_brief_dep_gate_ok` per the Scope DISPATCH DIRECTIVE — the intended loop body and POST-EMIT SELF-CHECK above MUST be copied VERBATIM into the task's `spec.implementation_notes` so the blind worker sees the contract. verification_command: `python3 -m pytest -q tests/harness/test_dep_gate_no_premature_release.py tests/harness/test_brief_level_dep_gate.py` (BOTH committed oracles — the fix must verify the UNION; 10 passed). spec.non_goals MUST contain the word "integration". test-spec balance: test_tokens >= 1.5 * implementation_tokens; minimum_test_count >= 1.5 * len(functional_requirements); unit_tests length >= len(functional_requirements). `test_spec.regression_tests` MUST list at least two entries that NAME existing committed test cases (plan descriptors referencing committed tests — this does NOT authorize authoring new tests), e.g. `test_accepted_dependency_still_releases`, `test_no_declared_deps_still_dispatchable`, `test_met_brief_dep_allows_dispatch`.

# Non-Goals

Do NOT touch `_decide`, `collect_dispatchable_tasks`, `prioritize`, `can_run_parallel`, `_auto_promote`, or any other symbol of harness/autowork_daemon.py beyond `_brief_dep_gate_ok`. Do NOT touch harness/planner/brief_loader.py or harness/brief_status.py. Do NOT author or modify any test — the oracles are committed and authoritative. Do NOT add module-level imports, state files, telemetry events, retries, or persistence — the gate stays a pure read-only filter re-evaluated each tick. Do NOT add a genuine-deadlock telemetry emission in this task (additive, non-releasing, deferred — an integration concern). Do NOT emit a whole-file replacement or a multi-file manifest. Integration / e2e testing is out of scope — this fix is verified solely by the two committed unit oracles.

# Inputs

The two committed authoritative oracles (currently RED on HEAD against the leak, 5 failing + 5 passing):
* tests/harness/test_dep_gate_no_premature_release.py — pins the A.1 fix: `test_absent_dependency_record_holds_dispatch` (absent dep → False), `test_blocked_dependency_not_yet_complete_holds_dispatch` (blocked dep → False), `test_zombie_dependency_not_yet_complete_holds_dispatch` (zombie dep → False), plus regression guards `test_accepted_dependency_still_releases` (accepted dep → True) and `test_no_declared_deps_still_dispatchable` (no deps → True).
* tests/harness/test_brief_level_dep_gate.py — the original gate oracle, with its two stale cases updated to the corrected behaviour: `test_absent_dep_slug_holds_dispatch` (absent → False) and `test_blocked_dep_holds_dispatch` (blocked → False); the other three (`test_unmet_brief_dep_holds_dispatch`, `test_met_brief_dep_allows_dispatch`, `test_no_declared_deps_is_dispatchable`) stay GREEN unchanged.

`status_records` rows come from `compute_brief_status` (harness/brief_status.py) and carry `slug`, `brief_filename`, `task_ids`, `accepted`, `remaining`, `blocked`, `state` (one of unplanned/planned/blocked/in_flight/complete/zombie/queued). "Fully accepted" == `task_ids` non-empty AND `remaining` empty. The owning brief is resolved by membership of the task's `task_id` in a record's `task_ids`, then frontmatter deps are read from `repo_root / brief_filename` via `harness.planner.brief_loader._parse_frontmatter` + `_coerce_optional_brief_fields` (lazy import inside the function, UNCHANGED). stdlib only.

# Deliverables

harness/autowork_daemon.py with `_brief_dep_gate_ok` edited so the per-dep loop HOLDS (returns False) on an absent / blocked / zombie / queued / in_flight dependency and releases (continues) ONLY on a genuine terminal-ACCEPTED dependency, with every other line of the module byte-identical to the staged baseline and both `except Exception: return True` error-degrade wrappers preserved. Verified GREEN by `python3 -m pytest -q tests/harness/test_dep_gate_no_premature_release.py tests/harness/test_brief_level_dep_gate.py` (10 passed).
