"""Single source of truth for per-task spec file paths."""
from __future__ import annotations
from pathlib import Path

def current_task_spec_path(state_dir, task_id: str) -> Path:
    """Return the canonical path to the per-task spec JSON for ``task_id``."""
    raise NotImplementedError
__version__ = '1.0.0'