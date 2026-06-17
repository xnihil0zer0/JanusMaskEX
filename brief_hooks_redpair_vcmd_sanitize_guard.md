---
title: Planner red-pair vcmd-sanitize guard — never vacuous-ize an impl whose vcmd references a real in-plan oracle
meta_task_type: harness_self_fix
working_dir: /home/xnihil0zer0/JanusMaskJR
required_task_ids:
  - redpair-sanitize-predicate
  - redpair-sanitize-impl
  - redpair-sanitize-wireup
files_touched:
  - tests/harness/test_redpair_sanitize_guard.py
  - harness/redpair_vcmd_guard.py
  - harness/planner/plan_normalizer.py
verification_command: python -m pytest tests/harness/test_redpair_sanitize_guard.py tests/planner/test_sanitize_vcmd_repo_mapping.py -q
---

# Title

Planner `_sanitize_impl_verification_commands` red-pair guard: an impl task whose
`verification_command` references a sibling in-plan `test_authoring` oracle's own
`files_touched` — when that oracle's `mutation_target` resolves to a real on-disk
module — is a genuine fix-forward red-pair and MUST NOT be rewritten to a vacuous
`python -c "import <modules>"` smoke check.

# Scope

`harness/planner/plan_normalizer.py::_sanitize_impl_verification_commands`
(defined at line 179, invoked from `normalize_plan` at line 1076, AFTER the
keystone red-pair KEEP guards earlier in `normalize_plan`) is the last pass that
touches impl verification_commands. For each non-`test_authoring` task whose vcmd
either references an oracle file (`references_oracle`, line 234) or is a weak
import-smoke (`is_import_smoke`, line 239), it rewrites the vcmd: to a pytest run
of an existing `tests/**/test_<leaf>.py` when one is found on disk (line 274),
else to a vacuous `python -c "import <modules>"` (line 277), else strips oracle
tokens (line 283).

THE DEFECT: when the impl edits an EXISTING module and its vcmd legitimately runs
the sibling oracle's OWN authored test file (the fix-forward red-pair contract —
exactly what `is_fix_forward_redpair` in `harness/redpair_acceptance.py:21` keys
off, line 51: the impl vcmd substring-contains the oracle's own file), and no
`tests/**/test_<leaf>.py` exists on disk for the impl's module (the common case
for a harness module like `plan_normalizer.py` which has no `test_plan_normalizer.py`),
the existing-test glob at line 263 finds nothing, so the rewrite falls through to
line 277 and DESTROYS the red-pair reference — replacing the gating oracle run
with a no-op import. This de-gates the impl: a behaviour-breaking edit ACCEPTs
vacuously, and `is_fix_forward_redpair` can NEVER fire live because the vcmd it
inspects has been clobbered before acceptance.

THE FIX (permanent root cause, not a band-aid): before the line-277 vacuous
rewrite, compute the set of in-plan `test_authoring` oracle files whose owning
oracle task carries a `mutation_target` that resolves to a REAL on-disk module
file (under `repo_root`). If the current impl's vcmd references any such oracle
file, SKIP the rewrite entirely and leave the vcmd untouched — it is a genuine
red-pair, the oracle file is its real gate. A new helper module
`harness/redpair_vcmd_guard.py` exposes the substring predicate
`references_sibling_oracle(vcmd, oracle_files) -> bool`; the wireup in
`plan_normalizer.py` computes the qualifying-oracle-file set and consults the
predicate immediately before the rewrite.

The guard is narrowly scoped: it ONLY protects vcmds that reference a real
red-pair oracle (oracle WITH an on-disk `mutation_target`). Oracles with NO
`mutation_target`, or a `mutation_target` for an absent (new) module, do NOT
qualify — so every existing hermetic case in
`tests/planner/test_sanitize_vcmd_repo_mapping.py` (none of which attach a
`mutation_target` to their oracle tasks) is left BYTE-IDENTICAL: all 6 stay
green, none flip. Genuine vacuous / non-red-pair impls keep the existing
import-smoke and existing-regression-test behaviour unchanged.

# Scope (component breakdown)

C1 — New helper `harness/redpair_vcmd_guard.py` (NEW module). Pure, no I/O,
never raises. Public signature:

    def references_sibling_oracle(vcmd: str, oracle_files: list[str]) -> bool:
        """True iff ``vcmd`` substring-contains any path in ``oracle_files``.

        ``vcmd`` non-str / empty, or ``oracle_files`` empty / non-list, → False.
        Non-str entries in ``oracle_files`` are skipped. Never raises."""

C2 — Wireup in `harness/planner/plan_normalizer.py` (EXISTING module, additive
edit only). Import `references_sibling_oracle` from `harness.redpair_vcmd_guard`.
Inside `_sanitize_impl_verification_commands`, BEFORE the line-277
`if modules:` vacuous-rewrite branch, compute once (per call) the set of
qualifying oracle files: for every `test_authoring` task in the plan that has a
`mutation_target` whose `_module_path(mutation_target)` EXISTS under `repo_root`
(skip when `repo_root is None`), add that oracle's `files_touched` entries. Then,
inside the per-impl loop, if `references_sibling_oracle(vcmd, qualifying_files)`
is True, `continue` (skip the rewrite) — leaving the impl vcmd untouched. Place
the skip so it short-circuits BEFORE line 274's existing-test rewrite as well, so
a genuine red-pair vcmd is never rewritten even when an unrelated
`test_<leaf>.py` happens to exist. Edit ADDITIVELY via the
R-ANCHOR/`__JANUSMASK_PATCHES__` path — do NOT reproduce `plan_normalizer.py`
whole.

# Non-goals

- Not an integration test of the live daemon or `_auto_commit_accepted` — unit
  oracles against the normalizer sanitize seam and the helper predicate are
  sufficient (this is an integration-excused scope; H3 in the plan separately
  drives the discriminating live fix-forward e2e).
- Does NOT change the planner brief schema, meta_task_type taxonomy, or the
  keystone red-pair KEEP guards earlier in `normalize_plan`.
- Does NOT alter behaviour for impls whose oracle has no `mutation_target` or a
  `mutation_target` pointing at an ABSENT module — those keep the existing
  import-smoke / existing-regression-test / token-strip behaviour verbatim.
- Does NOT edit `tests/planner/test_sanitize_vcmd_repo_mapping.py` — all 6 cases
  there must stay green unchanged (they attach no `mutation_target`, so the guard
  leaves them untouched).

# Inputs

Exact code anchors (already verified on HEAD):
- harness/planner/plan_normalizer.py:179 — `_sanitize_impl_verification_commands`
  (oracle_files union 219-224; `references_oracle` 234; `is_import_smoke` 239;
  existing-test glob 263; existing-test rewrite 274; VACUOUS rewrite 277;
  token-strip 283).
- harness/planner/plan_normalizer.py:1076 — `normalize_plan` calls the sanitize
  pass AFTER the red-pair KEEP guards (1067-1075).
- harness/planner/plan_normalizer.py:25 — `_module_path(mutation_target)`
  (`mutation_target.replace('.', '/') + '.py'`) — reuse for the on-disk check.
- harness/planner/plan_normalizer.py:34 `_files_touched`, :42 `_mutation_target`,
  :46 `_is_test_authoring` — reuse these existing helpers in the wireup.
- harness/redpair_acceptance.py:21 — `is_fix_forward_redpair` (the live
  acceptance predicate this fix finally lets fire; line 51 substring rule).
- harness/orchestrator.py:1978 — `_new_module_red_by_absence` (accepts leaf-1's
  RED oracle for the absent `harness.redpair_vcmd_guard` module).
- tests/planner/test_sanitize_vcmd_repo_mapping.py — the 6 anti-seesaw cases
  (no `mutation_target` on any oracle → unaffected by the guard).

# Deliverables

1. NEW `harness/redpair_vcmd_guard.py` (C1) with EXACTLY this source:

```python
"""Red-pair vcmd guard for the planner's impl-vcmd sanitize pass.

A genuine fix-forward red-pair impl runs its sibling oracle's OWN authored test
file as its ``verification_command`` (the same substring rule
``harness.redpair_acceptance.is_fix_forward_redpair`` keys off). The planner's
``_sanitize_impl_verification_commands`` must NOT rewrite such a vcmd to a
vacuous ``python -c "import ..."`` smoke check, which would de-gate the impl.
This module exposes the pure substring predicate used to detect that case.
"""
from __future__ import annotations

from typing import List


def references_sibling_oracle(vcmd: str, oracle_files: List[str]) -> bool:
    """Return True iff ``vcmd`` substring-contains any path in ``oracle_files``.

    Pure and total: ``vcmd`` that is not a non-empty str, or ``oracle_files``
    that is not a list / is empty, yields False. Non-str entries in
    ``oracle_files`` are skipped. Empty-string entries never match. Never raises.
    """
    if not isinstance(vcmd, str) or not vcmd:
        return False
    if not isinstance(oracle_files, list) or not oracle_files:
        return False
    for of in oracle_files:
        if isinstance(of, str) and of and of in vcmd:
            return True
    return False
```

2. A pipeline-authored RED oracle `tests/harness/test_redpair_sanitize_guard.py`
   (test_authoring) — RED on current HEAD (the module
   `harness/redpair_vcmd_guard.py` does NOT exist → ImportError mentioning
   `harness`; and the end-to-end red-pair-preservation assert fails because the
   un-guarded sanitizer vacuous-izes the impl vcmd). GREEN after both impls land.
   EXACTLY this source:

```python
"""RED-by-absence oracle for the red-pair vcmd-sanitize guard.

RED on HEAD: ``harness.redpair_vcmd_guard`` does not exist (import fails,
ModuleNotFoundError mentioning ``harness``), AND — once the module exists but
before the plan_normalizer wireup lands — the end-to-end test fails because the
un-guarded ``_sanitize_impl_verification_commands`` rewrites a genuine red-pair
impl's vcmd to a vacuous ``python -c "import ..."`` smoke check.

GREEN after the fix: the helper predicate behaves as specified, AND a constructed
red-pair plan (impl edits an existing module, vcmd runs the sibling oracle's own
file, oracle carries a real on-disk mutation_target) has its impl vcmd PRESERVED
through ``normalize_plan(plan, repo_root=repo)`` rather than vacuous-ized.

All cases are HERMETIC under tmp_path — no dependency on the real repo tree.
"""
import copy

import pytest

from harness.redpair_vcmd_guard import references_sibling_oracle
from harness.planner.plan_normalizer import normalize_plan


ORACLE_TEST_FILE = "tests/pkg/test_thing_oracle.py"
EXISTING_MODULE = "pkg/thing.py"  # created on-disk in the fake repo


def _impl_task(task_id, files_touched, verification_command):
    return {
        "task_id": task_id,
        "title": "impl " + task_id,
        "meta_task_type": "implementation",
        "dependencies": [],
        "files_touched": list(files_touched),
        "verification_command": verification_command,
    }


def _oracle_task(task_id, files_touched, verification_command, mutation_target=None):
    t = {
        "task_id": task_id,
        "title": "oracle " + task_id,
        "meta_task_type": "test_authoring",
        "dependencies": [],
        "files_touched": list(files_touched),
        "verification_command": verification_command,
    }
    if mutation_target is not None:
        t["mutation_target"] = mutation_target
    return t


def _plan(*tasks):
    return {"tasks": [copy.deepcopy(t) for t in tasks]}


def _task_by_id(plan, task_id):
    for task in plan["tasks"]:
        if task["task_id"] == task_id:
            return task
    raise AssertionError("task %r not in %r" % (task_id, [t["task_id"] for t in plan["tasks"]]))


def _make_repo(tmp_path, files):
    """Create a fake repo root with the given files (rel paths) present."""
    for rel in files:
        p = tmp_path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("# placeholder\n", encoding="utf-8")
    return tmp_path


# ---- helper predicate unit cases ---------------------------------------------

def test_predicate_true_when_vcmd_contains_an_oracle_file():
    vcmd = "python -m pytest %s -q" % ORACLE_TEST_FILE
    assert references_sibling_oracle(vcmd, [ORACLE_TEST_FILE]) is True


def test_predicate_false_when_vcmd_references_no_oracle_file():
    vcmd = 'python -c "import pkg.thing"'
    assert references_sibling_oracle(vcmd, [ORACLE_TEST_FILE]) is False


def test_predicate_total_on_degenerate_inputs():
    assert references_sibling_oracle("", [ORACLE_TEST_FILE]) is False
    assert references_sibling_oracle(None, [ORACLE_TEST_FILE]) is False
    assert references_sibling_oracle("python -m pytest x -q", []) is False
    assert references_sibling_oracle("python -m pytest x -q", None) is False
    # non-str entries skipped, no raise
    assert references_sibling_oracle("python -m pytest x -q", [123, None]) is False


# ---- end-to-end: a genuine red-pair impl vcmd is PRESERVED -------------------

def test_redpair_impl_vcmd_preserved_when_oracle_has_real_mutation_target(tmp_path):
    """Impl edits an EXISTING module; its vcmd runs the sibling oracle's own
    (not-yet-landed) test file; the oracle carries a mutation_target that
    resolves to a real on-disk module. The sanitize pass must PRESERVE the impl
    vcmd (it is a genuine fix-forward red-pair) — not rewrite it to a vacuous
    smoke import."""
    repo = _make_repo(tmp_path, [EXISTING_MODULE])  # module exists; oracle test does NOT
    impl = _impl_task(
        "thing-impl",
        [EXISTING_MODULE],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
    )
    oracle = _oracle_task(
        "thing-oracle",
        [ORACLE_TEST_FILE],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
        mutation_target="pkg.thing",  # resolves to pkg/thing.py which EXISTS
    )
    plan = _plan(impl, oracle)

    result = normalize_plan(plan, repo_root=repo)

    vc = _task_by_id(result, "thing-impl")["verification_command"]
    assert vc == "python -m pytest %s -q" % ORACLE_TEST_FILE  # PRESERVED, untouched
    assert "import" not in vc  # NOT vacuous-ized


def test_non_redpair_impl_still_vacuous_ized_when_oracle_has_no_mutation_target(tmp_path):
    """Control: an oracle with NO mutation_target does NOT qualify, so the
    existing vacuous-import behaviour is preserved (matches the 6 cases in
    tests/planner/test_sanitize_vcmd_repo_mapping.py)."""
    repo = _make_repo(tmp_path, [EXISTING_MODULE])
    impl = _impl_task(
        "thing-impl2",
        [EXISTING_MODULE],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
    )
    oracle = _oracle_task(
        "thing-oracle2",
        [ORACLE_TEST_FILE],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
        mutation_target=None,  # no mutation_target → not a qualifying red-pair
    )
    plan = _plan(impl, oracle)

    result = normalize_plan(plan, repo_root=repo)

    vc = _task_by_id(result, "thing-impl2")["verification_command"]
    assert vc == 'python -c "import pkg.thing"'  # vacuous-ized as before


def test_oracle_with_absent_mutation_target_does_not_qualify(tmp_path):
    """An oracle whose mutation_target points at an ABSENT module does NOT
    qualify (new-module red-by-absence path), so the impl vcmd is still
    rewritten — the guard only protects real existing-module red-pairs."""
    repo = _make_repo(tmp_path, [EXISTING_MODULE])  # pkg.absent does NOT exist
    impl = _impl_task(
        "thing-impl3",
        [EXISTING_MODULE],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
    )
    oracle = _oracle_task(
        "thing-oracle3",
        [ORACLE_TEST_FILE],
        "python -m pytest %s -q" % ORACLE_TEST_FILE,
        mutation_target="pkg.absent",  # resolves to pkg/absent.py which does NOT exist
    )
    plan = _plan(impl, oracle)

    result = normalize_plan(plan, repo_root=repo)

    vc = _task_by_id(result, "thing-impl3")["verification_command"]
    assert vc == 'python -c "import pkg.thing"'  # not protected → vacuous-ized


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
```

3. The C1/C2 changes above. C2 is landed via the R-ANCHOR/`__JANUSMASK_PATCHES__`
   partial-edit path (do NOT reproduce `plan_normalizer.py` whole).

4. Anti-seesaw — the fix MUST keep ALL 6 cases in
   `tests/planner/test_sanitize_vcmd_repo_mapping.py` green (they pin the
   unaffected behaviour: existing-test rewrite, brand-new-module smoke fallback,
   repo_root=None backward compat, oracle-file-never-used-as-regression,
   idempotence, test_authoring vcmd never touched). None attach a
   `mutation_target` → none qualify for the guard → all stay byte-identical.

# Required plan shape

Decompose into EXACTLY these three leaves, using these EXACT task_ids (declared
in frontmatter `required_task_ids`; `validate_plan` rejects the plan with
`missing_required_task` if any is absent). This is the new-module-predicate
pattern, which dodges the chicken-and-egg: leaf 1's oracle targets a NEW module
(`harness.redpair_vcmd_guard`, absent on HEAD) so it is accepted via
`_new_module_red_by_absence` (orchestrator.py:1978), not via the existing-module
fix-forward path.

1. task_id: redpair-sanitize-predicate
   - meta_task_type: test_authoring
   - files_touched: [tests/harness/test_redpair_sanitize_guard.py]
   - mutation_target: harness.redpair_vcmd_guard   (bare dotted module-under-test;
     its file harness/redpair_vcmd_guard.py does NOT yet exist — NEW module,
     accepted RED-by-absence)
   - verification_command: python -m pytest tests/harness/test_redpair_sanitize_guard.py -q
   - dependencies: []
   - Authors the RED oracle of deliverable 2; RED on current HEAD (module absent
     → ImportError mentioning `harness`), GREEN after the two impls land.
     spec_author: null.

2. task_id: redpair-sanitize-impl
   - meta_task_type: harness_self_fix
   - files_touched: [harness/redpair_vcmd_guard.py]
   - verification_command: python -m pytest tests/harness/test_redpair_sanitize_guard.py -q
   - dependencies: [redpair-sanitize-predicate]
   - Implements C1 (NEW module `harness/redpair_vcmd_guard.py` with
     `references_sibling_oracle`). Whole-file new module (a NEW single file is
     authored whole, not patched).

3. task_id: redpair-sanitize-wireup
   - meta_task_type: harness_self_fix
   - files_touched: [harness/planner/plan_normalizer.py]
   - verification_command: python -m pytest tests/harness/test_redpair_sanitize_guard.py tests/planner/test_sanitize_vcmd_repo_mapping.py -q
   - dependencies: [redpair-sanitize-impl]
   - Implements C2 (import + compute qualifying-oracle-file set + skip rewrite
     when the impl vcmd references a qualifying oracle file). Edit ADDITIVELY via
     the R-ANCHOR/`__JANUSMASK_PATCHES__` path; do NOT reproduce
     `plan_normalizer.py` whole.

Each leaf's `non_goals` MUST contain the word "integration" (integration-excused
scope — see Non-goals; the planner's `missing_integration_test` gate at
plan_validator.py is excused only when a non_goal contains "integration").
Each leaf's `test_spec.regression_tests` MUST contain >= 2 entries, INCLUDING
`tests/planner/test_sanitize_vcmd_repo_mapping.py` (the anti-seesaw pin) and
`tests/harness/test_redpair_sanitize_guard.py`.

Pairing rationale (do not change): the oracle (leaf 1) declares NO dependencies;
both impls depend on it transitively (leaf 2 → leaf 1; leaf 3 → leaf 2). The
oracle's `mutation_target` (`harness.redpair_vcmd_guard`) is ABSENT on HEAD, so
acceptance flows through `_new_module_red_by_absence`, not
`is_fix_forward_redpair`. The brief's TOP-LEVEL `verification_command` (the real
oracle tests) gates the whole bundle at final brief verification, so even though
leaf 3's per-leaf vcmd is vacuous-ized by the very pass it edits (there is no
`tests/**/test_plan_normalizer.py` on disk, and the guard it adds does not yet
apply to ITS OWN leaf), a mis-wired leaf 3 is caught RED at final verification
rather than silently landing.
