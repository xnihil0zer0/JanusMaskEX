"""RED oracle for the gap#2b smoke-gating hook in plan_normalizer.

gap#2b: the diff-fuzzer cannot resolve external ``ngv2.*`` imports and the
stateful-fuzz path diverges, so auto-planned EXTERNAL-build leaf plans that the
planner stamps with fuzz-routed meta types (``io_adapter``/``refactor`` =>
diff-fuzz; ``state_machine`` => stateful_fuzz) fail their gate even though the
build is correct, and the planner sometimes over-decomposes one leaf into
several tasks (impl + verify-oracle + conformance-gate).

Fix: ``normalize_plan(plan, repo_root=<external>)`` forces each external-build
leaf to a SINGLE smoke-gated (``data_model``) IMPL task — it groups the tasks
that share an EXISTING committed oracle test file under ``repo_root``, keeps one
impl per group, retypes it to ``data_model`` (bypass_fuzzer + smoke-gated), drops
the sibling verify/conformance/extra tasks, and rewires dependencies that
referenced a dropped task.

Strict no-op when ``repo_root`` is None, when it resolves to PROJECT_ROOT (a
JM-internal self-fix plan must NEVER be retyped), for an epic plan, and for a
group with no existing oracle. Pure (deep copy), idempotent.
"""
from __future__ import annotations

import copy
import pathlib

from harness.paths import PROJECT_ROOT
from harness.planner.plan_normalizer import normalize_plan

# meta types that must NOT be chosen as the surviving impl
_NON_IMPL = {"test_authoring", "test_acceptance", "test_unit",
             "test_integration", "test_e2e", "validation"}


def _write_oracle(root: pathlib.Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")


def _leaf_task(task_id, meta, leaf="backtrack", deps=None):
    return {
        "task_id": task_id,
        "meta_task_type": meta,
        "files_touched": ["ngv2/%s.py" % leaf],
        "dependencies": list(deps or []),
        "verification_command": "python -m pytest tests/test_%s.py -q" % leaf,
        "spec": {"objective": "build ngv2/%s.py" % leaf, "implementation_notes": ""},
    }


def _ids(plan):
    return [t["task_id"] for t in plan["tasks"]]


def test_external_multitask_leaf_collapses_to_single_data_model_impl(tmp_path):
    """A 4-task over-decomposed external leaf collapses to one data_model impl."""
    _write_oracle(tmp_path, "tests/test_backtrack.py")
    plan = {"tasks": [
        # survivor impl candidate carries a dep on a sibling that will be dropped
        _leaf_task("backtrack-impl", "state_machine", deps=["verify-backtrack-oracle"]),
        _leaf_task("impl-backtrack-shell", "state_machine"),
        _leaf_task("verify-backtrack-oracle", "test_acceptance"),
        _leaf_task("backtrack-conformance-gate", "validation"),
    ]}
    out = normalize_plan(plan, repo_root=tmp_path)

    assert len(out["tasks"]) == 1, (
        "the 4-task over-decomposed leaf must collapse to exactly one task, got "
        + repr(_ids(out))
    )
    surv = out["tasks"][0]
    assert surv["meta_task_type"] == "data_model", (
        "surviving impl must be retyped to the smoke-gated data_model type, got "
        + repr(surv["meta_task_type"])
    )
    assert surv["meta_task_type"] not in _NON_IMPL  # never a test/validation task
    # the dependency on a dropped sibling must be rewired away
    assert "verify-backtrack-oracle" not in surv.get("dependencies", []), (
        "dependencies referencing a dropped task must be stripped"
    )


def test_external_single_io_adapter_leaf_retyped_to_data_model(tmp_path):
    """A single-task external leaf typed io_adapter is retyped to data_model."""
    _write_oracle(tmp_path, "tests/test_z3_bridge.py")
    plan = {"tasks": [_leaf_task("z3-bridge-impl", "io_adapter", leaf="z3_bridge")]}
    out = normalize_plan(plan, repo_root=tmp_path)

    assert len(out["tasks"]) == 1
    assert out["tasks"][0]["meta_task_type"] == "data_model", (
        "external io_adapter leaf must be retyped to data_model (bypass_fuzzer)"
    )


def test_internal_plan_at_project_root_is_strict_noop(tmp_path):
    """repo_root == PROJECT_ROOT (a JM-internal self-fix) must NOT be retyped."""
    task = {
        "task_id": "grace-budget-fix",
        "meta_task_type": "harness_self_fix",
        "files_touched": ["harness/autowork_daemon.py"],
        "dependencies": [],
        "verification_command": "python -m pytest tests/adversarial/test_x.py -q",
        "spec": {"objective": "patch a harness fn"},
    }
    out = normalize_plan({"tasks": [task]}, repo_root=PROJECT_ROOT)
    assert len(out["tasks"]) == 1
    assert out["tasks"][0]["meta_task_type"] == "harness_self_fix", (
        "a JM-internal plan (repo_root==PROJECT_ROOT) must never be retyped to "
        "data_model; that would corrupt every harness self-fix"
    )


def test_repo_root_none_is_noop(tmp_path):
    """repo_root None leaves meta_task_type untouched."""
    plan = {"tasks": [_leaf_task("backtrack-impl", "state_machine")]}
    out = normalize_plan(plan, repo_root=None)
    assert out["tasks"][0]["meta_task_type"] == "state_machine"


def test_external_leaf_without_existing_oracle_untouched(tmp_path):
    """When no oracle file exists under repo_root, the task is left untouched."""
    # do NOT write tests/test_backtrack.py
    plan = {"tasks": [_leaf_task("backtrack-impl", "state_machine")]}
    out = normalize_plan(plan, repo_root=tmp_path)
    assert len(out["tasks"]) == 1
    assert out["tasks"][0]["meta_task_type"] == "state_machine", (
        "no existing oracle => not an identifiable external leaf => untouched"
    )


def test_epic_plan_is_noop(tmp_path):
    """An epic plan (child_slugs present) must be left untouched."""
    _write_oracle(tmp_path, "tests/test_backtrack.py")
    plan = {"child_slugs": ["a", "b"],
            "tasks": [_leaf_task("backtrack-impl", "state_machine")]}
    out = normalize_plan(plan, repo_root=tmp_path)
    assert out["tasks"][0]["meta_task_type"] == "state_machine"


def test_idempotent_under_external_repo_root(tmp_path):
    """normalize twice == normalize once."""
    _write_oracle(tmp_path, "tests/test_backtrack.py")
    plan = {"tasks": [
        _leaf_task("backtrack-impl", "state_machine"),
        _leaf_task("verify-backtrack-oracle", "test_acceptance"),
    ]}
    once = normalize_plan(plan, repo_root=tmp_path)
    twice = normalize_plan(copy.deepcopy(once), repo_root=tmp_path)
    assert _ids(once) == _ids(twice)
    assert once["tasks"][0]["meta_task_type"] == twice["tasks"][0]["meta_task_type"] == "data_model"
