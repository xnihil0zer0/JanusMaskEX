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

def write_jsonl_row(path: pathlib.Path, row: dict[str, Any], *, lock_path: pathlib.Path | None=None) -> None:
    raise NotImplementedError