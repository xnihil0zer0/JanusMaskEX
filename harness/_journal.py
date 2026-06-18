"""Shared JSONL row writer primitive for JanusMask event journals.

Low-level file-append primitive with zero domain logic. Callers own row
construction (timestamps, event IDs, schema fields, enum validation). The
primitive owns parent-directory creation, optional fcntl locking,
JSON-line encoding, and durable flush via fsync.
"""

from __future__ import annotations

import fcntl
import json
import os
import pathlib
from typing import Any


def write_jsonl_row(
    path: pathlib.Path,
    row: dict[str, Any],
    *,
    lock_path: pathlib.Path | None = None,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row) + "\n"

    if lock_path is None:
        lock_path = path.with_suffix(path.suffix + ".lock")

    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a", encoding="utf-8") as lock_fd:
        fcntl.flock(lock_fd, fcntl.LOCK_EX)
        try:
            with path.open("a", encoding="utf-8") as f:
                f.write(line)
                f.flush()
                os.fsync(f.fileno())
        finally:
            fcntl.flock(lock_fd, fcntl.LOCK_UN)
