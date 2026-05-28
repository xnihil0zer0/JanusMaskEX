import json
from pathlib import Path
import pytest

def check_true_depth(task_id: str, tasks_dir: Path, max_depth: int = 3) -> bool:
    if not task_id:
        return False
    
    try:
        tasks_dir = Path(tasks_dir)
    except TypeError:
        return False
        
    try:
        max_depth = int(max_depth)
    except (TypeError, ValueError):
        return False

    current_task = str(task_id)
    depth = 1
    seen = set()

    while True:
        if current_task in seen:
            return False  # Circular reference
        seen.add(current_task)

        if depth > max_depth:
            return False

        task_file = tasks_dir / f"{current_task}.json"
        
        try:
            if not task_file.is_file():
                task_file = tasks_dir / "processed" / f"{current_task}.json"
                if not task_file.is_file():
                    return False
        except (OSError, TypeError, ValueError):
            return False

        try:
            with open(task_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, json.JSONDecodeError):
            return False

        parent = data.get("parent_task")
        if not parent:
            break

        current_task = str(parent)
        depth += 1

    return True

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

