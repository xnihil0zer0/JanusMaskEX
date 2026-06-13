"""Git pre-push hook runner for the drive-backup tool.

This module is the entrypoint wired into git's ``pre-push`` hook (invoked in
production via ``python -m tools.drive_backup.hook_runner``). Git feeds the
hook, on stdin, one line per ref being pushed of the form::

    <local_ref> <local_sha> <remote_ref> <remote_sha>

We parse those lines, then orchestrate an injected pipeline of
``archiver -> uploader -> ledger.record`` for each pushed commit. Every
collaborator failure is caught and logged loudly through an injected ``log``
seam, and the runner ALWAYS returns ``0`` -- a nonzero pre-push exit aborts
the push, and a backup hiccup must never block a developer's push.

Stdlib only. No real archive/upload/git/network and no subprocess spawning
happens here; all such work is delegated to injected seams.
"""
from __future__ import annotations
import os
import sys
from typing import Any, Callable, Iterable, List, NamedTuple, Optional
__all__ = ['PushRef', 'parse_push_refs', 'pushed_shas', 'run_backup', 'main']

class PushRef(NamedTuple):
    """A single ref line from git's pre-push stdin."""
    local_ref: str
    local_sha: str
    remote_ref: str
    remote_sha: str

def _is_deletion(local_sha: str) -> bool:
    """A deletion is signalled by an all-zero local_sha (40 or 64 zeros)."""
    return bool(local_sha) and set(local_sha) == {'0'}

def parse_push_refs(stdin_text: str) -> List[PushRef]:
    """Parse git pre-push stdin into PushRef records.

    Blank/whitespace-only lines are skipped, and deletion sentinels (an
    all-zero local_sha) are skipped so they never produce a PushRef.
    """
    refs: List[PushRef] = []
    for line in (stdin_text or '').splitlines():
        parts = line.split()
        if len(parts) < 4:
            continue
        local_ref, local_sha, remote_ref, remote_sha = parts[:4]
        if _is_deletion(local_sha):
            continue
        refs.append(PushRef(local_ref, local_sha, remote_ref, remote_sha))
    return refs

def pushed_shas(refs: Iterable[Any]) -> List[str]:
    """Return deduped non-deletion local_sha values in encounter order."""
    seen: set = set()
    shas: List[str] = []
    for ref in refs:
        sha = getattr(ref, 'local_sha', None)
        if not sha or _is_deletion(sha):
            continue
        if sha in seen:
            continue
        seen.add(sha)
        shas.append(sha)
    return shas

def _archive_name(archive_result: Any) -> str:
    """Derive a human-friendly archive name from an archiver result."""
    manifest = getattr(archive_result, 'manifest', None)
    if isinstance(manifest, dict) and manifest.get('stem'):
        return str(manifest['stem'])
    path = getattr(archive_result, 'archive_path', None)
    if path:
        return os.path.basename(str(path))
    return str(archive_result)

def run_backup(repo_root: Any, refs: Iterable[Any], *, archiver: Callable[..., Any], uploader: Callable[..., Any], ledger: Any, log: Callable[..., Any]) -> int:
    """Orchestrate archiver -> uploader -> ledger.record for pushed shas.

    Reads ``ledger.last_backed_up_sha()`` as the base for incremental
    archives. For each pushed sha it builds the archive, uploads/queues it,
    and records the result in the ledger -- recording ONLY after a
    successful archive. Every collaborator exception is caught and logged
    via the ``log`` seam; this function ALWAYS returns 0 and never raises.
    """
    base_sha = None
    try:
        base_sha = ledger.last_backed_up_sha()
    except Exception as exc:
        log('drive_backup: failed to read base_sha from ledger', error=repr(exc))
    for sha in pushed_shas(refs):
        try:
            archive_result = archiver(repo_root, sha, base_sha=base_sha)
        except Exception as exc:
            log('drive_backup: archive failed', sha=sha, error=repr(exc))
            continue
        uploaded = False
        try:
            upload_result = uploader(archive_result)
            uploaded = bool(getattr(upload_result, 'uploaded', False))
        except Exception as exc:
            log('drive_backup: upload failed', sha=sha, error=repr(exc))
            uploaded = False
        try:
            ledger.record(sha, _archive_name(archive_result), uploaded)
        except Exception as exc:
            log('drive_backup: ledger record failed', sha=sha, error=repr(exc))
    return 0

def _resolve_repo_root() -> str:
    """Best-effort repo root resolution without spawning a subprocess.

    Honors ``$GIT_DIR`` if set, otherwise walks up from the current working
    directory looking for a ``.git`` entry, falling back to cwd.
    """
    git_dir = os.environ.get('GIT_DIR')
    if git_dir:
        return os.path.dirname(os.path.abspath(git_dir)) or os.getcwd()
    current = os.getcwd()
    while True:
        if os.path.exists(os.path.join(current, '.git')):
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return os.getcwd()
        current = parent

def _read_stdin(stdin: Any) -> str:
    """Read pre-push ref text from an injected stdin or sys.stdin."""
    if stdin is None:
        stdin = sys.stdin
    if isinstance(stdin, str):
        return stdin
    read = getattr(stdin, 'read', None)
    if callable(read):
        return read()
    return str(stdin)

def _default_build_deps(repo_root: Any) -> Any:
    """Wire the real archiver/uploader/ledger/log for production use.

    Imported lazily so unit tests (which inject ``build_deps``) never touch
    the real sibling modules or any real I/O.
    """
    from types import SimpleNamespace
    from tools.drive_backup import archiver as archiver_mod
    from tools.drive_backup import uploader as uploader_mod
    from tools.drive_backup.archiver import ledger as ledger_mod

    def log(message: str, **fields: Any) -> None:
        extra = ' '.join((f'{k}={v!r}' for k, v in fields.items()))
        line = message if not extra else f'{message} {extra}'
        print(line, file=sys.stderr)
    return SimpleNamespace(archiver=archiver_mod.build_archive, uploader=uploader_mod.upload, ledger=ledger_mod.BackupLedger(repo_root), log=log)

def main(argv: Optional[List[str]]=None, *, stdin: Any=None, repo_root: Any=None, build_deps: Optional[Callable[[Any], Any]]=None) -> int:
    """Pre-push entrypoint: read refs, build deps, run the backup.

    Resolves stdin/repo_root/build_deps from injectable seams (defaulting to
    real runtime sources) and delegates to ``run_backup``. Any top-level
    exception -- including ``build_deps`` raising -- is swallowed and logged;
    this function ALWAYS returns 0 so a push is never blocked.
    """
    try:
        text = _read_stdin(stdin)
        refs = parse_push_refs(text)
        root = repo_root if repo_root is not None else _resolve_repo_root()
        factory = build_deps if build_deps is not None else _default_build_deps
        deps = factory(root)
        return run_backup(root, refs, archiver=deps.archiver, uploader=deps.uploader, ledger=deps.ledger, log=deps.log)
    except Exception as exc:
        print(f'drive_backup: hook runner failed: {exc!r}', file=sys.stderr)
        return 0
if __name__ == '__main__':
    sys.exit(main())