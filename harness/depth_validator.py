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
    if not isinstance(task_id, str) or not task_id:
        return False
    if isinstance(tasks_dir, bool):
        return False
    try:
        tasks_dir = Path(tasks_dir)
        processed_dir = tasks_dir / 'processed'
    except Exception:
        return False

    depth = 0
    current_task_id = task_id
    visited = set()
    try:
        while current_task_id:
            if not isinstance(current_task_id, str) or not current_task_id:
                return False
            if current_task_id in visited:
                logger.warning(f'Circular reference detected in task lineage starting from {task_id}')
                return False
            visited.add(current_task_id)
            depth += 1
            if depth > max_depth:
                logger.warning(f'Task {task_id} lineage depth {depth} exceeds max_depth {max_depth}')
                return False
            task_file = tasks_dir / f'{current_task_id}.json'
            if not task_file.exists():
                task_file = processed_dir / f'{current_task_id}.json'
            try:
                with open(task_file, 'r') as f:
                    task_data = json.load(f)
            except FileNotFoundError:
                logger.warning(f'Task file not found in tasks/ or processed/: {current_task_id}')
                return False
            except json.JSONDecodeError as e:
                logger.warning(f'Invalid JSON in task file {task_file}: {e}')
                return False

            p_val = None
            if 'parent_task' in task_data:
                p_val = task_data['parent_task']
            elif 'parent_task_id' in task_data:
                p_val = task_data['parent_task_id']

            if p_val is None:
                break
            if not isinstance(p_val, str) or not p_val:
                return False
            current_task_id = p_val
    except Exception as e:
        logger.warning(f'Error checking depth for task {task_id}: {e}')
        return False
    return True