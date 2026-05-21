"""Unit tests for harness.depth_validator.check_true_depth.

Covers the P1.4 ride-along: parent files may live in tasks/ or tasks/processed/
once decomposition has moved them. Adversarial scenarios (4-deep chains, loops)
live under tests/adversarial/test_P0_depth_and_current_task.py.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness.depth_validator import check_true_depth


@pytest.fixture
def tasks_dir(tmp_path: Path) -> Path:
    d = tmp_path / "tasks"
    d.mkdir()
    (d / "processed").mkdir()
    return d


def _write(dirpath: Path, task_id: str, parent: str | None = None) -> None:
    payload = {"task_id": task_id}
    if parent is not None:
        payload["parent_task"] = parent
    (dirpath / f"{task_id}.json").write_text(json.dumps(payload))


def test_parentless_task_passes(tasks_dir: Path) -> None:
    _write(tasks_dir, "root")
    assert check_true_depth("root", tasks_dir) is True


def test_chain_within_max_depth_passes(tasks_dir: Path) -> None:
    _write(tasks_dir, "a")
    _write(tasks_dir, "b", parent="a")
    _write(tasks_dir, "c", parent="b")
    assert check_true_depth("c", tasks_dir, max_depth=3) is True


def test_chain_exceeding_max_depth_fails(tasks_dir: Path) -> None:
    _write(tasks_dir, "a")
    _write(tasks_dir, "b", parent="a")
    _write(tasks_dir, "c", parent="b")
    _write(tasks_dir, "d", parent="c")
    assert check_true_depth("d", tasks_dir, max_depth=3) is False


def test_parent_in_processed_dir_resolved(tasks_dir: Path) -> None:
    _write(tasks_dir / "processed", "parent")
    _write(tasks_dir, "child", parent="parent")
    assert check_true_depth("child", tasks_dir, max_depth=3) is True


def test_circular_reference_fails(tasks_dir: Path) -> None:
    _write(tasks_dir, "a", parent="b")
    _write(tasks_dir, "b", parent="a")
    assert check_true_depth("a", tasks_dir, max_depth=10) is False


def test_missing_parent_file_fails(tasks_dir: Path) -> None:
    _write(tasks_dir, "child", parent="ghost")
    assert check_true_depth("child", tasks_dir) is False
