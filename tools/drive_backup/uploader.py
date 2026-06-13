"""Drive-backup uploader (leaf: ``drive-backup-uploader``).

Copies a drive-backup ``tar.zst`` archive and its companion ``.diff`` to a
Google-Drive rclone remote (``gdrive:repo-push-backups/<repo>/``) through an
*injected runner seam* -- never invoking a real subprocess or touching the
network in any tested path.

Design contract (pinned by ``tests/drive_backup/test_uploader.py``):

* Fail LOUDLY but NON-BLOCKING: on *any* rclone error (nonzero rc, runner
  raising, rclone-not-found) :func:`upload` copies both artifacts into a
  caller-supplied ``queue_dir`` alongside a ``<name>.queued.json`` sidecar and
  returns a queued :class:`UploadResult`. It NEVER raises.
* :func:`drive_backup_drain` retries queued artifacts idempotently, clearing
  the local copy + sidecar on success and leaving failures queued. It also
  never raises.

Stdlib only. Every write path is a caller-supplied seam -- there is no default
destination of ``.``, ``os.getcwd()`` or ``__file__``'s dir; any scratch would
live under the system temp dir via :mod:`tempfile`. Every file handle is closed
deterministically via context managers.
"""
from __future__ import annotations
import datetime as _dt
import json
import os
import shutil
from dataclasses import dataclass
from typing import Any, Callable, List, Optional
__all__ = ['DEFAULT_REMOTE', 'UploadResult', 'remote_dir_for', 'upload', 'drive_backup_drain']
DEFAULT_REMOTE = 'gdrive:'
_SIDECAR_SUFFIX = '.queued.json'

@dataclass
class UploadResult:
    """Outcome of an :func:`upload` / drain attempt for the archive bundle.

    ``remote_path`` is the resolved remote directory (success) or the intended
    remote destination recorded in the sidecar (drain). ``error`` is a
    structured, human-readable string on failure and ``None`` on success.
    """
    uploaded: bool
    queued: bool
    remote_path: Optional[str]
    error: Optional[str]

def remote_dir_for(repo: str, *, remote: str=DEFAULT_REMOTE) -> str:
    """Return the remote backup directory for ``repo`` (always ends in ``/``).

    Pure string join on ``remote`` (which already ends in ``:``) so callers can
    build per-artifact destinations with a further simple concatenation.
    """
    return f'{remote}repo-push-backups/{repo}/'

def _structured_error(kind: str, detail: str='') -> str:
    """Build a structured error string capturing the failure *kind*."""
    detail = (detail or '').strip()
    return f'{kind}: {detail}' if detail else kind

def _decode(value: Any) -> str:
    """Best-effort decode of runner stderr/stdout (bytes or str)."""
    if value is None:
        return ''
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return str(value)

def _rclone_copyto(runner: Callable[..., Any], src: str, dest: str) -> Optional[str]:
    """Invoke ``rclone copyto <src> <dest>`` through ``runner``.

    Returns ``None`` on success or a structured error string on any failure
    (nonzero rc, runner raising, or rclone-not-found). Never raises.
    """
    argv = ['rclone', 'copyto', src, dest]
    try:
        result = runner(argv)
    except FileNotFoundError as exc:
        return _structured_error('rclone-not-found', str(exc))
    except Exception as exc:
        return _structured_error(f'runner-raised:{type(exc).__name__}', str(exc))
    rc = getattr(result, 'returncode', 1)
    if rc != 0:
        stderr = _decode(getattr(result, 'stderr', b''))
        return _structured_error(f'rclone-rc:{rc}', stderr)
    return None

def _now_iso(now: Optional[Callable[[], _dt.datetime]]) -> str:
    """Resolve the injected clock to an ISO-8601 timestamp string."""
    if now is not None:
        moment = now()
    else:
        moment = _dt.datetime.now(_dt.timezone.utc)
    try:
        return moment.isoformat()
    except Exception:
        return str(moment)

def _artifact_paths(archive_result: Any) -> List[str]:
    """Extract the (archive, diff) source paths from an ArchiveResult."""
    paths: List[str] = []
    for attr in ('archive_path', 'diff_path'):
        value = getattr(archive_result, attr, None)
        if value:
            paths.append(str(value))
    return paths

def _repo_of(archive_result: Any) -> str:
    """Best-effort repo name from the ArchiveResult manifest."""
    manifest = getattr(archive_result, 'manifest', None)
    if isinstance(manifest, dict):
        repo = manifest.get('repo')
        if repo:
            return str(repo)
    return 'unknown'

def _queue_artifact(queue_dir: str, src: str, remote_dest: str, error: str, queued_at: str) -> None:
    """Copy ``src`` into ``queue_dir`` and write its ``.queued.json`` sidecar."""
    name = os.path.basename(src)
    local_copy = os.path.join(queue_dir, name)
    sidecar = os.path.join(queue_dir, name + _SIDECAR_SUFFIX)
    shutil.copy2(src, local_copy)
    meta = {'name': name, 'remote_path': remote_dest, 'error': error, 'queued_at': queued_at}
    with open(sidecar, 'w', encoding='utf-8') as fh:
        json.dump(meta, fh, indent=2, sort_keys=True)

def upload(archive_result: Any, *, remote: str=DEFAULT_REMOTE, runner: Callable[..., Any], queue_dir: str, now: Optional[Callable[[], _dt.datetime]]=None) -> UploadResult:
    """Upload the archive + diff to the remote, queuing on any failure.

    On success returns ``UploadResult(uploaded=True, queued=False,
    remote_path=<remote dir>, error=None)``. On ANY failure copies both
    artifacts into ``queue_dir/<name>`` with a ``<name>.queued.json`` sidecar
    and returns a queued result. NEVER raises.
    """
    repo = _repo_of(archive_result)
    remote_dir = remote_dir_for(repo, remote=remote)
    sources = _artifact_paths(archive_result)
    error: Optional[str] = None
    for src in sources:
        dest = remote_dir + os.path.basename(src)
        err = _rclone_copyto(runner, src, dest)
        if err is not None:
            error = err
            break
    if error is None:
        return UploadResult(uploaded=True, queued=False, remote_path=remote_dir, error=None)
    queued_at = _now_iso(now)
    try:
        os.makedirs(queue_dir, exist_ok=True)
        for src in sources:
            dest = remote_dir + os.path.basename(src)
            _queue_artifact(queue_dir, src, dest, error, queued_at)
    except Exception as exc:
        error = _structured_error(f'queue-failed:{type(exc).__name__}', f'{error} | {exc}')
    return UploadResult(uploaded=False, queued=True, remote_path=remote_dir, error=error)

def drive_backup_drain(queue_dir: str, *, remote: str=DEFAULT_REMOTE, runner: Callable[..., Any]) -> List[UploadResult]:
    """Idempotently retry queued uploads found under ``queue_dir``.

    Scans for ``*.queued.json`` sidecars, re-attempts ``rclone copyto`` per
    artifact via ``runner``, removes the local copy + sidecar on success, and
    leaves failures queued. An empty queue or an already-absent artifact is a
    no-op. Never raises; returns one :class:`UploadResult` per processed
    sidecar.
    """
    results: List[UploadResult] = []
    if not os.path.isdir(queue_dir):
        return results
    try:
        entries = sorted(os.listdir(queue_dir))
    except OSError:
        return results
    for entry in entries:
        if not entry.endswith(_SIDECAR_SUFFIX):
            continue
        sidecar = os.path.join(queue_dir, entry)
        artifact_name = entry[:-len(_SIDECAR_SUFFIX)]
        artifact = os.path.join(queue_dir, artifact_name)
        remote_dest: Optional[str] = None
        try:
            with open(sidecar, 'r', encoding='utf-8') as fh:
                meta = json.load(fh)
            if isinstance(meta, dict):
                remote_dest = meta.get('remote_path')
        except Exception:
            meta = None
        if not os.path.exists(artifact):
            continue
        if not remote_dest:
            remote_dest = remote_dir_for('unknown', remote=remote) + artifact_name
        err = _rclone_copyto(runner, artifact, remote_dest)
        if err is None:
            for path in (artifact, sidecar):
                try:
                    os.remove(path)
                except OSError:
                    pass
            results.append(UploadResult(uploaded=True, queued=False, remote_path=remote_dest, error=None))
        else:
            results.append(UploadResult(uploaded=False, queued=True, remote_path=remote_dest, error=err))
    return results