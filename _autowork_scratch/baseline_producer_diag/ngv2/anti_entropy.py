"""Deterministic anti-entropy reconciliation shell for NobleGreed v2.

The real agent prunes ``tmp/``, rotates oversized logs, marks dead workers as
crashed in the worker registry, and expires stale commands. Those operations
are dangerous and non-deterministic (wall clock, live PIDs, sqlite, a fixed
filesystem root). This module isolates the pure orchestration behind an
INJECTED :class:`AntiEntropyEnv` seam so the tested surface never touches a real
clock, network, subprocess, randomness, or ``os.environ``:

* ``now_s``               -- a deterministic injected clock reading (seconds).
* ``registry_cleanup``    -- the worker-registry "mark dead workers" side.
* ``expire_commands_fn``  -- the stale-command expiry side.
* ``integrity_check``     -- the DB/store integrity probe.
* ``tmp_size_override``   -- optional injected ``tmp/`` size for the size gate.
* ``root``                -- a relocatable base directory; all paths hang off it.

Every environment-dependent value flows through the seam, so the same inputs
always produce the same outputs.  The module is stdlib-only and imports no
sibling Epic-4 leaf.
"""
from __future__ import annotations
import datetime
import json
import shutil
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Dict, Optional
__all__ = ['LOG_ROTATE_THRESHOLD_BYTES', 'LOG_KEEP_LINES', 'TMP_MAX_BYTES', 'TMP_MAX_AGE_DAYS', 'STALE_THRESHOLD_S', 'METRICS_FIELDS', 'AntiEntropyEnv', 'make_mock_env', 'cleanup_stale', 'rotate_logs', 'prune_tmp', 'expire_commands', 'verify_integrity', 'write_metrics', 'run_all']
LOG_ROTATE_THRESHOLD_BYTES: int = 52428800
LOG_KEEP_LINES: int = 1000
TMP_MAX_BYTES: int = 21474836480
TMP_MAX_AGE_DAYS: int = 7
STALE_THRESHOLD_S: int = 1800
METRICS_FIELDS = ('timestamp', 'dry_run', 'stale_cleaned', 'logs_rotated', 'tmp_pruned', 'commands_expired', 'integrity_ok')
_DAY_S: int = 86400

def _default_registry_cleanup(dry_run: bool) -> int:
    return 0

def _default_expire_commands(dry_run: bool) -> int:
    return 0

def _default_integrity_check() -> bool:
    return True

@dataclass
class AntiEntropyEnv:
    """Bundle of every environment reading the reconciler is allowed to use.

    All filesystem locations are derived from :attr:`root`; all volatile
    readings (clock, registry side effects, integrity probe, ``tmp/`` size)
    are supplied by the injected callables/values so the tested surface is
    deterministic and side-effect free outside ``root``.
    """
    root: Path
    now_s: float = 0.0
    registry_cleanup: Callable[[bool], int] = field(default=_default_registry_cleanup)
    expire_commands_fn: Callable[[bool], int] = field(default=_default_expire_commands)
    integrity_check: Callable[[], bool] = field(default=_default_integrity_check)
    tmp_size_override: Optional[int] = None

    def __post_init__(self) -> None:
        self.root = Path(self.root)

    @property
    def data_dir(self) -> Path:
        return self.root / 'data'

    @property
    def tmp_dir(self) -> Path:
        return self.root / 'tmp'

    @property
    def overseer_log(self) -> Path:
        return self.root / 'data' / 'overseer_log.jsonl'

    @property
    def metrics_path(self) -> Path:
        return self.root / 'data' / 'anti_entropy_metrics.json'

def make_mock_env(root: Path, now_s: float=0.0, registry_cleanup: Optional[Callable[[bool], int]]=None, expire_commands_fn: Optional[Callable[[bool], int]]=None, integrity_ok: bool=True, tmp_size_override: Optional[int]=None, stale_count: int=0, commands_expired: int=0) -> AntiEntropyEnv:
    """Build a deterministic :class:`AntiEntropyEnv` for tests/drivers.

    When a seam callable is not supplied, a constant deterministic stand-in is
    synthesised from the scalar overrides (``stale_count``, ``commands_expired``,
    ``integrity_ok``).
    """
    if registry_cleanup is None:

        def registry_cleanup(dry_run: bool) -> int:
            return stale_count
    if expire_commands_fn is None:

        def expire_commands_fn(dry_run: bool) -> int:
            return commands_expired

    def integrity_check() -> bool:
        return bool(integrity_ok)
    return AntiEntropyEnv(root=Path(root), now_s=now_s, registry_cleanup=registry_cleanup, expire_commands_fn=expire_commands_fn, integrity_check=integrity_check, tmp_size_override=tmp_size_override)

def _timestamp(now_s: float) -> str:
    """Render the injected clock reading as a deterministic ISO-8601 string."""
    moment = datetime.datetime.fromtimestamp(now_s, datetime.timezone.utc)
    return moment.isoformat()

def _dir_size(path: Path) -> int:
    """Total size in bytes of all regular files under ``path`` (0 if absent)."""
    if not path.exists():
        return 0
    total = 0
    for entry in path.rglob('*'):
        try:
            if entry.is_file():
                total += entry.stat().st_size
        except OSError:
            continue
    return total

def _append_log(env: AntiEntropyEnv, component: str, message: str, severity: str='info') -> None:
    """Append one structured JSON record to the overseer log."""
    record = {'timestamp': _timestamp(env.now_s), 'component': component, 'severity': severity, 'message': message}
    path = env.overseer_log
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as handle:
        handle.write(json.dumps(record) + '\n')

def cleanup_stale(dry_run: bool, env: AntiEntropyEnv) -> int:
    """Mark dead workers crashed, delegating to the injected registry seam."""
    return int(env.registry_cleanup(dry_run))

def rotate_logs(dry_run: bool, env: AntiEntropyEnv) -> int:
    """Rotate the overseer log when it grows past the byte threshold.

    Below the threshold this is a no-op (returns 0).  When over threshold the
    file is archived to a deterministic ``.bak`` sibling and the live file is
    truncated to at most :data:`LOG_KEEP_LINES` trailing lines.  Returns the
    number of logs rotated (0 or 1).
    """
    log = env.overseer_log
    if not log.exists():
        return 0
    try:
        size = log.stat().st_size
    except OSError:
        return 0
    if size <= LOG_ROTATE_THRESHOLD_BYTES:
        return 0
    if dry_run:
        return 1
    lines = log.read_text(encoding='utf-8').splitlines()
    archive = log.with_name(f'{log.name}.{int(env.now_s)}.bak')
    archive.write_text('\n'.join(lines) + ('\n' if lines else ''), encoding='utf-8')
    kept = lines[-LOG_KEEP_LINES:]
    log.write_text('\n'.join(kept) + ('\n' if kept else ''), encoding='utf-8')
    return 1

def prune_tmp(dry_run: bool, env: AntiEntropyEnv) -> int:
    """Prune aged top-level ``tmp/`` directories, but only when over the cap.

    The size gate uses ``env.tmp_size_override`` when provided, otherwise the
    real on-disk size of ``tmp/``.  When the cap is exceeded, immediate
    sub-directories older than :data:`TMP_MAX_AGE_DAYS` are pruned; hidden
    entries (leading dot) and files are left alone.  Returns the count of
    eligible directories (which are deleted only when not ``dry_run``).
    """
    tmp = env.tmp_dir
    if env.tmp_size_override is not None:
        size = env.tmp_size_override
    else:
        size = _dir_size(tmp)
    if size <= TMP_MAX_BYTES:
        return 0
    if not tmp.is_dir():
        return 0
    cutoff = env.now_s - TMP_MAX_AGE_DAYS * _DAY_S
    pruned = 0
    for entry in sorted(tmp.iterdir(), key=lambda p: p.name):
        if not entry.is_dir():
            continue
        if entry.name.startswith('.'):
            continue
        try:
            mtime = entry.stat().st_mtime
        except OSError:
            continue
        if mtime < cutoff:
            pruned += 1
            if not dry_run:
                shutil.rmtree(entry, ignore_errors=True)
    return pruned

def expire_commands(dry_run: bool, env: AntiEntropyEnv) -> int:
    """Expire stale commands, delegating to the injected registry seam."""
    return int(env.expire_commands_fn(dry_run))

def verify_integrity(env: AntiEntropyEnv) -> bool:
    """Return the store integrity verdict from the injected probe."""
    return bool(env.integrity_check())

def write_metrics(stale_cleaned: int, logs_rotated: int, tmp_pruned: int, commands_expired: int, integrity_ok: bool, dry_run: bool, env: AntiEntropyEnv) -> Dict[str, object]:
    """Build the metrics record and persist it atomically unless ``dry_run``.

    Returns the metrics dict whose keys are exactly :data:`METRICS_FIELDS`.
    """
    metrics: Dict[str, object] = {'timestamp': _timestamp(env.now_s), 'dry_run': dry_run, 'stale_cleaned': stale_cleaned, 'logs_rotated': logs_rotated, 'tmp_pruned': tmp_pruned, 'commands_expired': commands_expired, 'integrity_ok': integrity_ok}
    if not dry_run:
        path = env.metrics_path
        path.parent.mkdir(parents=True, exist_ok=True)
        staging = path.with_name(path.name + '.tmp')
        staging.write_text(json.dumps(metrics, indent=2), encoding='utf-8')
        staging.replace(path)
    return metrics

def run_all(dry_run: bool, env: AntiEntropyEnv) -> Dict[str, object]:
    """Run every reconciliation step in order and emit the metrics record.

    Each step is logged to the structured overseer log (live runs only), then
    the aggregate metrics are written via :func:`write_metrics`.
    """
    stale_cleaned = cleanup_stale(dry_run, env)
    logs_rotated = rotate_logs(dry_run, env)
    tmp_pruned = prune_tmp(dry_run, env)
    commands_expired = expire_commands(dry_run, env)
    integrity_ok = verify_integrity(env)
    if not dry_run:
        _append_log(env, 'cleanup_stale', f'stale_cleaned={stale_cleaned}')
        _append_log(env, 'rotate_logs', f'logs_rotated={logs_rotated}')
        _append_log(env, 'prune_tmp', f'tmp_pruned={tmp_pruned}')
        _append_log(env, 'expire_commands', f'commands_expired={commands_expired}')
        _append_log(env, 'verify_integrity', f'integrity_ok={integrity_ok}', severity='info' if integrity_ok else 'error')
    return write_metrics(stale_cleaned=stale_cleaned, logs_rotated=logs_rotated, tmp_pruned=tmp_pruned, commands_expired=commands_expired, integrity_ok=integrity_ok, dry_run=dry_run, env=env)