"""Oracle for plan_normalizer._split_multifile_module_tasks.

A task that creates MORE THAN ONE new .py module is split into one task per
module so the blind worker never has to emit a multi-file whole-file manifest
(the failure mode that silently clobbered run_stage in the worker rework). The
pass runs inside normalize_plan before _dedupe_oracles.

Module-creating notion (mirrors plan_validator._is_module_creating): a .py path
not under tests/ that does not already exist on disk under the repo root. Paths
like ``ngv2/workers/base.py`` do not exist in THIS repo, so they read as new;
``harness/planner/plan_normalizer.py`` exists, so it is an EDIT.
"""
import copy

from harness.planner.plan_normalizer import (
    _split_multifile_module_tasks,
    normalize_plan,
)


def _task(tid, files, mtt="orchestration", deps=None):
    return {
        "task_id": tid,
        "files_touched": list(files),
        "dependencies": list(deps or []),
        "meta_task_type": mtt,
    }


def test_a_two_new_modules_split_into_one_file_each_independent():
    out = _split_multifile_module_tasks(
        [_task("build", ["ngv2/workers/__init__.py", "ngv2/workers/base.py"])]
    )
    ids = [t["task_id"] for t in out]
    assert "build" not in ids  # original replaced
    assert len(out) == 2
    for t in out:
        assert len(t["files_touched"]) == 1
    a, b = out
    assert b["task_id"] not in a["dependencies"]
    assert a["task_id"] not in b["dependencies"]
    # union of the split files == the original file set
    assert {t["files_touched"][0] for t in out} == {
        "ngv2/workers/__init__.py", "ngv2/workers/base.py"}


def test_b_downstream_dependency_fans_out_to_all_splits():
    orig = _task("build", ["ngv2/a.py", "ngv2/b.py"])
    down = _task("oracle", ["ngv2/tests/test_x.py"], mtt="test_authoring", deps=["build"])
    out = _split_multifile_module_tasks([orig, down])
    split_ids = {t["task_id"] for t in out if t["task_id"] != "oracle"}
    d = next(t for t in out if t["task_id"] == "oracle")
    assert set(d["dependencies"]) == split_ids
    assert "build" not in d["dependencies"]


def test_c_single_new_module_unchanged():
    out = _split_multifile_module_tasks([_task("one", ["ngv2/solo.py"])])
    assert len(out) == 1
    assert out[0]["task_id"] == "one"
    assert out[0]["files_touched"] == ["ngv2/solo.py"]


def test_d_edit_task_of_existing_files_unchanged():
    files = ["harness/planner/plan_normalizer.py", "harness/planner/plan_validator.py"]
    out = _split_multifile_module_tasks([_task("edit", files, mtt="refactor")])
    assert len(out) == 1
    assert out[0]["files_touched"] == files


def test_e_test_authoring_never_split():
    out = _split_multifile_module_tasks(
        [_task("orc", ["ngv2/test_a.py", "ngv2/test_b.py"], mtt="test_authoring")]
    )
    assert len(out) == 1


def test_f_split_ids_unique_and_deterministic():
    orig = _task("build", ["ngv2/x.py", "ngv2/y.py"])
    ids1 = [t["task_id"] for t in _split_multifile_module_tasks([copy.deepcopy(orig)])]
    ids2 = [t["task_id"] for t in _split_multifile_module_tasks([copy.deepcopy(orig)])]
    assert ids1 == ids2  # deterministic
    assert len(set(ids1)) == len(ids1)  # unique


def test_anti_seesaw_normalize_plan_noop_for_single_file_plan():
    plan = {"tasks": [_task("one", ["ngv2/solo.py"])]}
    out = normalize_plan(copy.deepcopy(plan))
    assert any(t["task_id"] == "one" for t in out["tasks"])
