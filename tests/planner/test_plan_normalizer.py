"""Oracle for harness.planner.plan_normalizer.normalize_plan.

Pins the deterministic leaf-plan corrections that let the daemon's auto-planned
child plans execute with ZERO operator vetting:
  - DEDUPE ORACLES: two test_authoring tasks sharing a mutation_target -> one
    dropped, deps rewired to the kept id, no dangling dep.
  - ENFORCE MODULE-FIRST: an inverted impl/oracle dependency is flipped so the
    oracle depends on the impl (the mutation gate needs the module to exist).
  - IDEMPOTENT + NO-OP: an already-correct plan is unchanged; running twice ==
    once.
  - UNTOUCHED: a test_authoring task whose module has no impl task is left as-is.
"""
from __future__ import annotations

import copy

from harness.planner.plan_normalizer import normalize_plan


def _impl(task_id, module_file, deps=None, vcmd=None):
    return {
        "task_id": task_id,
        "meta_task_type": "harness_plumbing",
        "dependencies": list(deps or []),
        "files_touched": [module_file],
        "verification_command": vcmd or f'python -c "import {module_file}"',
    }


def _oracle(task_id, mutation_target, test_file, deps=None):
    return {
        "task_id": task_id,
        "meta_task_type": "test_authoring",
        "mutation_target": mutation_target,
        "dependencies": list(deps or []),
        "files_touched": [test_file],
        "verification_command": f"python -m pytest {test_file} -q",
    }


def _ids(plan):
    return [t["task_id"] for t in plan["tasks"]]


def _by_id(plan, tid):
    return next(t for t in plan["tasks"] if t["task_id"] == tid)


def test_dedupe_two_oracles_same_mutation_target():
    # impl creates harness/symbol_ledger.py; its vcmd references the kept oracle's file.
    impl = _impl(
        "symbol-ledger-module",
        "harness/symbol_ledger.py",
        vcmd="python -m pytest tests/harness/test_symbol_ledger.py -q",
    )
    keep = _oracle("symbol-ledger-oracle", "harness.symbol_ledger",
                   "tests/harness/test_symbol_ledger.py", deps=["symbol-ledger-module"])
    drop = _oracle("oracle-symbol-ledger", "harness.symbol_ledger",
                   "tests/harness/test_other.py", deps=["symbol-ledger-module"])
    # a downstream task depends on the DROPPED oracle id -> must be rewired.
    downstream = {
        "task_id": "e2e",
        "meta_task_type": "harness_plumbing",
        "dependencies": ["oracle-symbol-ledger"],
        "files_touched": ["harness/e2e.py"],
        "verification_command": "true",
    }
    plan = {"tasks": [impl, keep, drop, downstream]}
    out = normalize_plan(plan)

    # exactly one oracle survives, and it is the one referenced by impl's vcmd.
    oracles = [t for t in out["tasks"] if t.get("meta_task_type") == "test_authoring"]
    assert len(oracles) == 1
    assert oracles[0]["task_id"] == "symbol-ledger-oracle"
    assert "oracle-symbol-ledger" not in _ids(out)
    # downstream dep rewired dropped -> kept, no dangling reference.
    assert _by_id(out, "e2e")["dependencies"] == ["symbol-ledger-oracle"]
    all_ids = set(_ids(out))
    for t in out["tasks"]:
        for d in t["dependencies"]:
            assert d in all_ids, f"dangling dep {d}"


def test_enforce_module_first_flips_inversion():
    # INVERTED: impl depends on the oracle ("oracle-first"); oracle has no dep.
    impl = _impl("mod", "harness/foo.py", deps=["orc"])
    orc = _oracle("orc", "harness.foo", "tests/harness/test_foo.py", deps=[])
    out = normalize_plan({"tasks": [impl, orc]})

    # Flipped to module-first: oracle depends on impl; impl no longer depends on oracle.
    assert _by_id(out, "orc")["dependencies"] == ["mod"]
    assert "orc" not in _by_id(out, "mod")["dependencies"]


def test_already_correct_plan_unchanged_and_idempotent():
    impl = _impl("mod", "harness/foo.py", deps=[])
    orc = _oracle("orc", "harness.foo", "tests/harness/test_foo.py", deps=["mod"])
    plan = {"tasks": [impl, orc]}
    before = copy.deepcopy(plan)
    once = normalize_plan(plan)
    # input is not mutated in place.
    assert plan == before
    # already-correct: structurally unchanged.
    assert _by_id(once, "orc")["dependencies"] == ["mod"]
    assert _by_id(once, "mod")["dependencies"] == []
    # idempotent: normalize(normalize(x)) == normalize(x).
    twice = normalize_plan(once)
    assert twice == once


def test_oracle_for_preexisting_module_untouched():
    # No impl task creates harness/preexisting.py -> oracle left as-is.
    orc = _oracle("orc", "harness.preexisting", "tests/harness/test_pre.py", deps=[])
    other = _impl("other", "harness/unrelated.py", deps=[])
    out = normalize_plan({"tasks": [orc, other]})
    assert _by_id(out, "orc")["dependencies"] == []
    assert _ids(out) == ["orc", "other"]


def test_non_dict_and_empty_are_noop():
    assert normalize_plan({"tasks": []}) == {"tasks": []}
    assert normalize_plan({}) == {}
    assert normalize_plan(None) is None
