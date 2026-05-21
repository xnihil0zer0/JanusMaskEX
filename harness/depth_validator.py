import json
import logging
from pathlib import Path
logger = logging.getLogger(__name__)

def check_true_depth(task_id: str, tasks_dir: Path, max_depth: int=3) -> bool:
    """
    Check if a task's true lineage depth exceeds max_depth.

    Loads the task's JSON file and iteratively follows parent_task references
    to count the lineage depth. Parent files are looked up in ``tasks_dir``
    first, then in ``tasks_dir / 'processed'`` (decomposed parents are moved
    to processed/ once their subtasks are enqueued — see P1.4).

    Args:
        task_id: The task identifier (without .json extension)
        tasks_dir: Path to the directory containing task JSON files
        max_depth: Maximum allowed lineage depth (default: 3)

    Returns:
        False if lineage depth > max_depth, True otherwise
    """
    visited: set[str] = set()
    current = task_id
    depth = 0
    while current is not None:
        if current in visited:
            logger.warning('Circular parent reference detected at task %s', current)
            return False
        visited.add(current)
        path = tasks_dir / f'{current}.json'
        if not path.is_file():
            path = tasks_dir / 'processed' / f'{current}.json'
        if not path.is_file():
            logger.warning('Task file not found for %s in %s', current, tasks_dir)
            return False
        try:
            data = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning('Failed to load task file for %s: %s', current, exc)
            return False
        depth += 1
        if depth > max_depth:
            return False
        parent = data.get('parent_task')
        current = parent if parent else None
    return True