from __future__ import annotations
import fcntl
import json
import os
import pathlib
from typing import Any

def write_jsonl_row(path: pathlib.Path, row: dict[str, Any], *, lock_path: pathlib.Path | None=None) -> None:
    path = pathlib.Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    line = json.dumps(row) + '\n'

    def _append() -> None:
        with open(path, 'a', encoding='utf-8') as fh:
            fh.write(line)
            fh.flush()
            os.fsync(fh.fileno())
    if lock_path is None:
        _append()
        return
    lock_path = pathlib.Path(lock_path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, 'a+') as lock_fh:
        fcntl.flock(lock_fh.fileno(), fcntl.LOCK_EX)
        try:
            _append()
        finally:
            fcntl.flock(lock_fh.fileno(), fcntl.LOCK_UN)
'Shared JSONL row writer primitive for JanusMask event journals.\n\nLow-level file-append primitive with zero domain logic. Callers own row\nconstruction (timestamps, event IDs, schema fields, enum validation). The\nprimitive owns parent-directory creation, optional fcntl locking,\nJSON-line encoding, and durable flush via fsync.\n'