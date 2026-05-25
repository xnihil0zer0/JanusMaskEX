"""Regression-lock P3/C9.15: the task decomposer must PROPAGATE rebuild flags.

A hard rebuild unit that fails round 1+2 decomposes into subtasks. Without
propagation those subtasks DROP the parent's fuzz_str_ascii (the word-domain
alphabet that closes pure-str false-divergence) and partial_edit (the over-budget
single-symbol patch path), so a decomposed rebuild unit false-diverges or blows
the AST-merge byte budget. _preserve_meta_task_type now carries the flags into the
child constraints and enqueue_subtasks re-hoists them to the top level where the
orchestrator/diff_fuzzer read them.
"""

from __future__ import annotations

import json

from harness.task_decomposer import (
    Subtask,
    _preserve_meta_task_type,
    enqueue_subtasks,
)


def test_preserve_carries_toplevel_rebuild_flags_into_constraints():
    parent = {
        "task_id": "RB_x_pluralize",
        "fuzz_str_ascii": True,
        "partial_edit": True,
        "meta_task_type": "harness_plumbing",
    }
    c = _preserve_meta_task_type(parent, {"function_signature": "def f(): ..."})
    assert c.get("fuzz_str_ascii") is True
    assert c.get("partial_edit") is True


def test_preserve_carries_flags_from_parent_constraints():
    parent = {
        "task_id": "RB_x_pluralize",
        "constraints": {"fuzz_str_ascii": True, "partial_edit": True},
    }
    c = _preserve_meta_task_type(parent, {})
    assert c.get("fuzz_str_ascii") is True
    assert c.get("partial_edit") is True


def test_preserve_omits_flags_when_parent_lacks_them():
    parent = {"task_id": "plain", "meta_task_type": "feature"}
    c = _preserve_meta_task_type(parent, {})
    assert "fuzz_str_ascii" not in c
    assert "partial_edit" not in c


def test_enqueue_subtasks_hoists_rebuild_flags_to_toplevel(tmp_path):
    st = Subtask(
        task_id="RB_x_pluralize_sub0",
        parent_task_id="RB_x_pluralize",
        specification="reconstruct half",
        constraints={"function_signature": "def f(): ...",
                     "fuzz_str_ascii": True, "partial_edit": True},
    )
    enqueue_subtasks([st], tmp_path)
    data = json.loads((tmp_path / "tasks" / "RB_x_pluralize_sub0.json").read_text())
    # the orchestrator/fuzzer read these at the TOP level (task.get(...)).
    assert data["fuzz_str_ascii"] is True
    assert data["partial_edit"] is True


def test_enqueue_subtasks_no_flags_when_absent(tmp_path):
    st = Subtask(
        task_id="plain_sub0",
        parent_task_id="plain",
        specification="x",
        constraints={"function_signature": "def f(): ..."},
    )
    enqueue_subtasks([st], tmp_path)
    data = json.loads((tmp_path / "tasks" / "plain_sub0.json").read_text())
    assert "fuzz_str_ascii" not in data
    assert "partial_edit" not in data
