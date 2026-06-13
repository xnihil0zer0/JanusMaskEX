"""Drive-backup ledger: an append-only NDJSON record of prior backups.

``BackupLedger`` takes an EXPLICIT path seam (no implicit default). Each row is
one JSON object on its own line. Appends are atomic (write-temp-then-rename) so
records are durable across separate instances pointed at the same path, and a
corrupt/partial trailing line is skipped rather than fatal.

Resource hygiene: every file handle is closed deterministically and the only
side effect is the caller-supplied ledger file (plus a transient sibling temp
file that is renamed into place, leaving no ``.lock``/``.tmp`` residue).
"""
from __future__ import annotations
import json
import os
import tempfile
from typing import Any, Dict, List, Optional

class BackupLedger:
    """Newline-delimited JSON ledger of backup rows at an explicit path."""

    def __init__(self, path: str) -> None:
        self._path = path

    def entries(self) -> List[Dict[str, Any]]:
        """Return all valid rows in order; skip corrupt/partial lines."""
        rows: List[Dict[str, Any]] = []
        if not os.path.exists(self._path):
            return rows
        with open(self._path, 'r', encoding='utf-8') as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except (ValueError, json.JSONDecodeError):
                    continue
                if isinstance(obj, dict):
                    rows.append(obj)
        return rows

    def last_backed_up_sha(self) -> Optional[str]:
        """Return the most recently recorded sha, or None when empty/missing."""
        rows = self.entries()
        if not rows:
            return None
        return rows[-1].get('sha')

    def record(self, sha: str, archive_name: str, uploaded: bool) -> None:
        """Append one row atomically via write-temp-then-rename."""
        row = {'sha': sha, 'archive_name': archive_name, 'uploaded': uploaded}
        line = json.dumps(row)
        existing = ''
        if os.path.exists(self._path):
            with open(self._path, 'r', encoding='utf-8') as fh:
                existing = fh.read()
        if existing and (not existing.endswith('\n')):
            existing += '\n'
        new_content = existing + line + '\n'
        directory = os.path.dirname(self._path) or '.'
        fd, tmp_path = tempfile.mkstemp(dir=directory, prefix='.ledger-', suffix='.tmp')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as fh:
                fh.write(new_content)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp_path, self._path)
        except BaseException:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            raise