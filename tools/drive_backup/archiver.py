"""Drive-backup archiver: build a tar.zst snapshot + git diff with a manifest.

This module is a pure seam-builder. All subprocess access flows through an
injected ``runner`` and all time through an injected ``now`` clock, so no real
tar/zstd/git execution happens in any tested path -- the tests assert argv
construction, naming, exclude materialization, and manifest contents only.

Resource hygiene: this module never writes archives, ledgers, temp dirs, lock
files, or logs into the repo/working tree. Every artifact path lives under the
caller-supplied ``out_dir``; there is no implicit default of ``.``,
``os.getcwd()``, or ``__file__``'s directory.
"""
from __future__ import annotations
import os
from dataclasses import dataclass
from typing import Any
from typing import Callable
from typing import Dict
from typing import FrozenSet
from typing import List
from typing import Optional
DEFAULT_EXCLUDES: FrozenSet[str] = frozenset({'node_modules', '.venv', 'venv', '__pycache__', '.pytest_cache', '.mypy_cache', '*.pyc', 'state/output', '_autowork_archive'})

@dataclass
class ArchiveResult:
    """Outcome of :func:`build_archive` (no real execution implied)."""
    archive_path: str
    diff_path: str
    base_sha: Optional[str]
    manifest: Dict[str, Any]

def build_archive(repo_root: str, sha: str, *, runner: Callable[..., Any], now: Callable[[], Any], out_dir: str, exclude: FrozenSet[str]=DEFAULT_EXCLUDES, base_sha: Optional[str]=None) -> ArchiveResult:
    """Construct a tar.zst snapshot + git diff for ``sha`` under ``out_dir``.

    ``runner`` is the ONLY subprocess seam; it is invoked with the archive and
    diff argvs (which are also recorded in the returned manifest). ``now`` must
    return a tz-aware UTC datetime used for the compact-UTC timestamp in the
    artifact stem ``<repo_basename>_<sha[:7]>_<compactUTC>``.
    """
    repo = os.path.basename(os.path.normpath(repo_root))
    sha7 = sha[:7]
    compact_utc = now().strftime('%Y%m%dT%H%M%SZ')
    stem = f'{repo}_{sha7}_{compact_utc}'
    os.makedirs(out_dir, exist_ok=True)
    archive_path = os.path.join(out_dir, f'{stem}.tar.zst')
    diff_path = os.path.join(out_dir, f'{stem}.diff')
    excludes: List[str] = sorted(exclude)
    archive_argv: List[str] = ['tar', '--use-compress-program=zstd', '-cf', archive_path]
    for item in excludes:
        archive_argv.extend(['--exclude', item])
    archive_argv.extend(['-C', repo_root, '.'])
    if base_sha is None:
        diff_argv: List[str] = ['git', '-C', repo_root, 'diff', sha]
    else:
        diff_argv = ['git', '-C', repo_root, 'diff', f'{base_sha}..{sha}']
    runner(archive_argv)
    runner(diff_argv)
    manifest: Dict[str, Any] = {'repo': repo, 'sha': sha, 'base_sha': base_sha, 'stem': stem, 'excludes': excludes, 'archive_argv': archive_argv, 'diff_argv': diff_argv, 'created_at': now().isoformat()}
    return ArchiveResult(archive_path=archive_path, diff_path=diff_path, base_sha=base_sha, manifest=manifest)