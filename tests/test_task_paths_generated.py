"""Verification oracle for harness.task_paths.

These tests describe the observable behaviour of
``harness.task_paths.current_task_spec_path`` exactly. They exercise real
behaviour so they fail against a NotImplementedError stub.
"""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from harness.task_paths import current_task_spec_path


def test_current_task_spec_path_returns_path_instance():
    result = current_task_spec_path("/tmp/state", "abc")
    assert isinstance(result, Path)


def test_current_task_spec_path_full_path_from_str_state_dir():
    result = current_task_spec_path("/tmp/state", "abc")
    assert result == Path("/tmp/state") / "tasks" / "current_task_abc.json"


def test_current_task_spec_path_accepts_path_state_dir():
    state_dir = Path("/var/run/state")
    result = current_task_spec_path(state_dir, "xyz")
    assert result == Path("/var/run/state") / "tasks" / "current_task_xyz.json"


def test_current_task_spec_path_filename_format():
    result = current_task_spec_path("/tmp/state", "42")
    assert result.name == "current_task_42.json"


def test_current_task_spec_path_parent_is_tasks_dir():
    result = current_task_spec_path("/tmp/state", "task1")
    assert result.parent == Path("/tmp/state") / "tasks"
    assert result.parent.name == "tasks"


def test_current_task_spec_path_has_json_suffix():
    result = current_task_spec_path("/tmp/state", "task1")
    assert result.suffix == ".json"


def test_current_task_spec_path_interpolates_task_id():
    result = current_task_spec_path("/tmp/state", "deadbeef")
    assert "deadbeef" in result.name
    assert result.name == "current_task_deadbeef.json"


def test_current_task_spec_path_different_task_ids_differ():
    a = current_task_spec_path("/tmp/state", "one")
    b = current_task_spec_path("/tmp/state", "two")
    assert a != b
    assert a.name == "current_task_one.json"
    assert b.name == "current_task_two.json"


def test_current_task_spec_path_relative_state_dir():
    result = current_task_spec_path("relstate", "t")
    assert result == Path("relstate") / "tasks" / "current_task_t.json"
    assert not result.is_absolute()


def test_current_task_spec_path_preserves_state_dir_prefix():
    result = current_task_spec_path("/a/b/c", "id99")
    parts = result.parts
    # state_dir components precede the 'tasks' segment and filename
    assert parts[-1] == "current_task_id99.json"
    assert parts[-2] == "tasks"
    assert str(Path("/a/b/c")) == str(Path(*parts[:-2]))


def test_current_task_spec_path_empty_task_id():
    result = current_task_spec_path("/tmp/state", "")
    assert result == Path("/tmp/state") / "tasks" / "current_task_.json"
    assert result.name == "current_task_.json"


def test_current_task_spec_path_numeric_looking_task_id_kept_as_given():
    result = current_task_spec_path("/tmp/state", "007")
    assert result.name == "current_task_007.json"
