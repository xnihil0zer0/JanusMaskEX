# ----- transitive_deps -----
"""Verification oracle for harness.autowork_parallelism.transitive_deps.

These tests describe the exact observable behaviour of ``transitive_deps``:
a breadth-first walk over a task dependency graph that returns the set of all
task ids transitively depended on by ``task_id`` (excluding ``task_id`` itself).
Only ``transitive_deps`` is exercised here; sibling units in the module are
not touched so the oracle remains valid while they are still stubbed.
"""
from __future__ import annotations

import pytest

from harness.autowork_parallelism import transitive_deps


def test_transitive_deps_direct_dependencies_returned():
    tasks = [
        {"task_id": "A", "dependencies": ["B", "C"]},
        {"task_id": "B", "dependencies": []},
        {"task_id": "C", "dependencies": []},
    ]
    assert transitive_deps("A", tasks) == {"B", "C"}


def test_transitive_deps_transitive_chain_collected():
    tasks = [
        {"task_id": "A", "dependencies": ["B"]},
        {"task_id": "B", "dependencies": ["C"]},
        {"task_id": "C", "dependencies": ["D"]},
        {"task_id": "D", "dependencies": []},
    ]
    assert transitive_deps("A", tasks) == {"B", "C", "D"}


def test_transitive_deps_excludes_starting_task():
    tasks = [
        {"task_id": "A", "dependencies": ["B"]},
        {"task_id": "B", "dependencies": ["A"]},
    ]
    # The queried task must never appear in its own transitive-dependency set,
    # even when a dependency cycles back to it.
    result = transitive_deps("A", tasks)
    assert "A" not in result
    assert result == {"B"}


def test_transitive_deps_self_dependency_returns_empty():
    tasks = [{"task_id": "A", "dependencies": ["A"]}]
    # A task depending on itself contributes nothing: the start node is already
    # marked visited, so the self-edge is skipped.
    assert transitive_deps("A", tasks) == set()


def test_transitive_deps_cycle_terminates():
    tasks = [
        {"task_id": "A", "dependencies": ["B"]},
        {"task_id": "B", "dependencies": ["C"]},
        {"task_id": "C", "dependencies": ["A"]},
    ]
    # Cyclic graphs must terminate and the start node stays excluded.
    assert transitive_deps("A", tasks) == {"B", "C"}


def test_transitive_deps_diamond_dedupes():
    tasks = [
        {"task_id": "A", "dependencies": ["B", "C"]},
        {"task_id": "B", "dependencies": ["D"]},
        {"task_id": "C", "dependencies": ["D"]},
        {"task_id": "D", "dependencies": []},
    ]
    # D is reachable via two paths but appears exactly once in the set.
    assert transitive_deps("A", tasks) == {"B", "C", "D"}


def test_transitive_deps_unknown_task_returns_empty():
    tasks = [
        {"task_id": "A", "dependencies": ["B"]},
        {"task_id": "B", "dependencies": []},
    ]
    assert transitive_deps("Z", tasks) == set()


def test_transitive_deps_empty_task_list_returns_empty():
    assert transitive_deps("A", []) == set()


def test_transitive_deps_no_dependencies_returns_empty():
    tasks = [{"task_id": "A", "dependencies": []}]
    assert transitive_deps("A", tasks) == set()


def test_transitive_deps_missing_dependencies_key_returns_empty():
    # A task with no 'dependencies' key is treated as having no dependencies.
    tasks = [{"task_id": "A"}]
    assert transitive_deps("A", tasks) == set()


def test_transitive_deps_none_dependencies_treated_as_empty():
    # 'dependencies': None must be tolerated and treated as empty, both for the
    # starting task and for an intermediate one.
    tasks = [
        {"task_id": "A", "dependencies": ["B"]},
        {"task_id": "B", "dependencies": None},
    ]
    assert transitive_deps("A", tasks) == {"B"}


def test_transitive_deps_dangling_dependency_included_not_traversed():
    # A dependency referencing a task that is absent from the list is still
    # reported, but no further traversal is attempted through it.
    tasks = [{"task_id": "A", "dependencies": ["X"]}]
    assert transitive_deps("A", tasks) == {"X"}


def test_transitive_deps_duplicate_dependency_entries_dedupe():
    tasks = [
        {"task_id": "A", "dependencies": ["B", "B"]},
        {"task_id": "B", "dependencies": []},
    ]
    assert transitive_deps("A", tasks) == {"B"}


def test_transitive_deps_non_string_task_ids_ignored():
    # Tasks whose task_id is not a string are excluded from the index entirely,
    # so they neither match queries nor participate in traversal; valid tasks
    # are still resolved correctly.
    tasks = [
        {"task_id": "A", "dependencies": ["B"]},
        {"task_id": 123, "dependencies": ["A"]},
        {"task_id": "B", "dependencies": []},
    ]
    assert transitive_deps("A", tasks) == {"B"}


def test_transitive_deps_missing_task_id_key_ignored():
    # An entry lacking a 'task_id' key must not crash indexing.
    tasks = [
        {"task_id": "A", "dependencies": ["B"]},
        {"dependencies": ["A"]},
        {"task_id": "B", "dependencies": []},
    ]
    assert transitive_deps("A", tasks) == {"B"}


def test_transitive_deps_returns_set_instance():
    tasks = [
        {"task_id": "A", "dependencies": ["B"]},
        {"task_id": "B", "dependencies": []},
    ]
    assert isinstance(transitive_deps("A", tasks), set)


def test_transitive_deps_does_not_mutate_input():
    tasks = [
        {"task_id": "A", "dependencies": ["B"]},
        {"task_id": "B", "dependencies": ["C"]},
        {"task_id": "C", "dependencies": []},
    ]
    a_deps_before = list(tasks[0]["dependencies"])
    transitive_deps("A", tasks)
    assert tasks[0]["dependencies"] == a_deps_before
    assert {t["task_id"] for t in tasks} == {"A", "B", "C"}


def test_transitive_deps_only_reachable_subgraph_returned():
    # Tasks unreachable from the start node are excluded.
    tasks = [
        {"task_id": "A", "dependencies": ["B"]},
        {"task_id": "B", "dependencies": []},
        {"task_id": "C", "dependencies": ["D"]},
        {"task_id": "D", "dependencies": []},
    ]
    assert transitive_deps("A", tasks) == {"B"}


# ----- _normalize_path -----
import os
import pathlib

import pytest

from harness.autowork_parallelism import _normalize_path


def test_normalize_path_directory_input_returns_true_flag(tmp_path):
    # A path ending in '/' is treated as a directory: second element is True.
    result, is_dir = _normalize_path(str(tmp_path) + "/")
    assert is_dir is True
    assert result.endswith("/")


def test_normalize_path_file_input_returns_false_flag(tmp_path):
    # A path NOT ending in '/' is treated as a file: second element is False.
    result, is_dir = _normalize_path(str(tmp_path / "file.txt"))
    assert is_dir is False
    assert not result.endswith("/")


def test_normalize_path_directory_preserves_trailing_slash(tmp_path):
    # Directory inputs canonicalize and re-append a single trailing slash.
    expected_base = str(tmp_path.resolve())
    assert _normalize_path(str(tmp_path) + "/") == (expected_base + "/", True)


def test_normalize_path_file_returns_canonical_without_slash(tmp_path):
    # File inputs canonicalize with no trailing slash; target need not exist.
    raw = str(tmp_path / "nested" / "thing.bin")
    expected = str(pathlib.Path(raw).resolve())
    assert _normalize_path(raw) == (expected, False)


def test_normalize_path_collapses_multiple_trailing_slashes(tmp_path):
    # rstrip('/') removes ALL trailing slashes before exactly one is restored.
    result, is_dir = _normalize_path(str(tmp_path) + "///")
    assert is_dir is True
    assert result == str(tmp_path.resolve()) + "/"
    assert not result.endswith("//")


def test_normalize_path_resolves_relative_against_cwd():
    # Relative inputs are made absolute relative to the current working dir.
    result, is_dir = _normalize_path("subdir/leaf")
    assert is_dir is False
    assert os.path.isabs(result)
    assert result == str(pathlib.Path("subdir/leaf").resolve())
    assert result.startswith(str(pathlib.Path.cwd()))


def test_normalize_path_resolves_dotdot_segments(tmp_path):
    # '..' segments are collapsed by canonicalization.
    raw = str(tmp_path / "a" / ".." / "b")
    result, is_dir = _normalize_path(raw)
    assert is_dir is False
    assert ".." not in result
    assert result == str(pathlib.Path(raw).resolve())


def test_normalize_path_returns_absolute_path(tmp_path):
    # Both directory and file forms always yield an absolute canonical path.
    file_result, _ = _normalize_path(str(tmp_path / "x"))
    dir_result, _ = _normalize_path(str(tmp_path) + "/")
    assert os.path.isabs(file_result)
    assert os.path.isabs(dir_result)


def test_normalize_path_dir_and_file_share_canonical_base(tmp_path):
    # The only difference between dir/file forms of one path is the slash + flag.
    base = str(tmp_path / "shared")
    file_canon, file_flag = _normalize_path(base)
    dir_canon, dir_flag = _normalize_path(base + "/")
    assert file_flag is False
    assert dir_flag is True
    assert dir_canon == file_canon + "/"


def test_normalize_path_returns_tuple_of_str_and_bool(tmp_path):
    # Return contract: a 2-tuple of (str, bool).
    result = _normalize_path(str(tmp_path))
    assert isinstance(result, tuple)
    assert len(result) == 2
    assert isinstance(result[0], str)
    assert isinstance(result[1], bool)


def test_normalize_path_root_slash_strips_to_cwd():
    # Edge quirk: '/' is dir, rstrip('/') yields '' which resolves to cwd.
    result, is_dir = _normalize_path("/")
    assert is_dir is True
    assert result == str(pathlib.Path("").resolve()) + "/"
