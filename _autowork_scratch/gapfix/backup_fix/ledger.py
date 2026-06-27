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
from typing import Any
from typing import Dict
from typing import List
from typing import Optional

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

    def last_backed_up_sha(self, repo: Optional[str]=None) -> Optional[str]:
        """Return the most recently recorded sha, or None when empty/missing.

        When ``repo`` is given, only rows tagged with that ``repo`` are
        considered -- so a single global ledger shared by several repos hands
        each push a base_sha that actually exists in ITS repo (rows written
        before repo-tagging, which lack a ``repo`` key, are skipped for a
        scoped query). When ``repo`` is None the historical behavior is
        preserved: the most recent row overall.
        """
        rows = self.entries()
        if repo is not None:
            rows = [r for r in rows if r.get('repo') == repo]
        if not rows:
            return None
        return rows[-1].get('sha')

    def record(self, sha: str, archive_name: str, uploaded: bool, repo: Optional[str]=None) -> None:
        """Append one row atomically via write-temp-then-rename.

        When ``repo`` is provided it is stored on the row so future
        :meth:`last_backed_up_sha` queries can be scoped per repo. Omitting
        ``repo`` preserves the original (untagged) row shape.
        """
        row = {'sha': sha, 'archive_name': archive_name, 'uploaded': uploaded}
        if repo is not None:
            row['repo'] = repo
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