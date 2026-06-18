"""Shared serialization primitive for state reconciliation.

This stdlib-only module exposes :func:`state_reconcile_lock`, a context
manager that acquires and releases the single dedicated
``state_reconcile.lock`` under a given state directory. It is the ONE shared
lock on which every state-mutating reconciliation path serializes -- the
in-loop brief_status sweep, the standalone reconcile apply, and the
post-accept brief reaper -- so the slow, destructive reconciliation work can
never run concurrently across mutators.

It is deliberately DISTINCT from the short-lived ``git_commit.lock``. The
slow destructive section is held under ``state_reconcile.lock`` and NEVER
under ``git_commit.lock``: the git commit lock is a per-git-op latch only and
must not span a slow op. A 14 GB rmtree/compaction held under the commit lock
would exceed the 60s accept deadline and route a validated build to
``auto_commit_failed``.

The lock is fail-closed (exclusive create) and is ALWAYS released on
exception via a ``finally`` so a crashing mutator never wedges the others.
"""
import os
import time
from contextlib import contextmanager
from pathlib import Path
__all__ = ['state_reconcile_lock', 'LOCK_FILENAME']
LOCK_FILENAME = 'state_reconcile.lock'

class ProductStatus:
    """Mutually-exclusive outcome tokens for :func:`classify_product`.

    Plain string members keep the resolver stdlib-only and importable without
    pulling an ``enum`` import in at module scope. ``LIVE`` is the
    short-circuit decided BEFORE any read; ``PLANNED`` is the healthy positive
    case; ``FOREIGN``/``UNPLANNED``/``CORRUPT`` cover the non-ours, absent and
    fail-closed buckets respectively.
    """
    LIVE = 'LIVE'
    FOREIGN = 'FOREIGN'
    UNPLANNED = 'UNPLANNED'
    CORRUPT = 'CORRUPT'
    PLANNED = 'PLANNED'

_WRITE_SETTLE_GRACE_SEC = 60.0

def pid_is_live(pid) -> bool:
    """True iff ``pid`` names a currently running, signalable process.

    Probes with ``os.kill(pid, 0)``: a missing/non-numeric/non-positive pid is
    not live; ``ESRCH`` means the process is gone; ``EPERM`` means it is alive
    but owned by someone else, which still counts as live (fail-closed -- never
    treat a running task's product as dead).
    """
    import errno
    try:
        pid_int = int(pid)
    except (TypeError, ValueError):
        return False
    if pid_int <= 0:
        return False
    try:
        os.kill(pid_int, 0)
    except OSError as exc:
        return getattr(exc, 'errno', None) == errno.EPERM
    return True

def _pidfile_task_id(stem):
    """Extract the exact encoded task id from a pidfile *stem* (no ``.pid``).

    Handles two stem shapes and returns ``None`` for anything unparseable:

    * regular ``<task_id>`` -- the stem *is* the task id (returned verbatim).
    * self-heal ``selfheal_<agent>_<task_id>_<pid>`` -- strip the ``selfheal_``
      prefix and the trailing numeric ``_<pid>`` segment, then peel the leading
      ``<agent>_`` segment, leaving the exact task id. Returning the parsed task
      id (rather than substring-scanning the raw stem) is what makes the
      equality check substring-proof, e.g. ``t1`` never matches ``t12``.
    """
    import re
    if not stem:
        return None
    if stem.startswith('selfheal_'):
        body = stem[len('selfheal_'):]
        m = re.match('^(?P<core>.+)_(?P<pid>\\d+)$', body)
        if m is None:
            return None
        core = m.group('core')
        if '_' not in core:
            return None
        _agent, task_id = core.split('_', 1)
        return task_id or None
    return stem

def task_id_has_live_pidfile(running_dir, task_id) -> bool:
    """True iff some ``*.pid`` under ``running_dir`` names ``task_id`` AND is live.

    Each pidfile stem is parsed to its *exact* encoded task id (regular or
    self-heal) and compared for full equality against ``task_id`` -- never a
    substring -- so ``t1`` is not confused with ``t12`` and the self-heal agent
    or trailing pid segment can never be mistaken for the task id. Only a stem
    that matches exactly *and* whose pid is signalable counts.
    """
    if not task_id:
        return False
    d = Path(running_dir)
    try:
        entries = list(d.iterdir())
    except OSError:
        return False
    for entry in entries:
        if entry.suffix != '.pid':
            continue
        encoded = _pidfile_task_id(entry.stem)
        if encoded is None or encoded != task_id:
            continue
        try:
            raw = entry.read_text(encoding='utf-8').strip()
        except OSError:
            continue
        if pid_is_live(raw):
            return True
    return False

def task_id_in_ledger(ledger_path, task_id) -> bool:
    """True iff ``task_id`` has been recorded (exact match) in the JSONL ledger.

    Reads the symbol/impl-progress ledger one JSON object per line; malformed
    lines are skipped silently. A row counts only when its ``task_id`` field is
    *exactly* equal to ``task_id`` (substring-proof: ``t1`` does not match
    ``t12``).
    """
    import json
    if not task_id:
        return False
    try:
        text = Path(ledger_path).read_text(encoding='utf-8')
    except OSError:
        return False
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get('task_id') == task_id:
            return True
    return False

def worktree_is_reachable(workdir, registered) -> bool:
    """True iff ``workdir`` is still a registered Git worktree.

    ``registered`` is the list of currently registered worktree paths (as
    produced by ``git worktree list``). Reachability is decided purely by
    membership: ``workdir`` is reachable iff its normalised, real path equals
    the normalised real path of one of the registered entries. A workdir absent
    from ``registered`` is unreachable.
    """
    if not workdir:
        return False

    def _norm(p):
        try:
            return os.path.normpath(os.path.realpath(str(p)))
        except (OSError, ValueError):
            return os.path.normpath(str(p))
    target = _norm(workdir)
    for entry in registered or []:
        if _norm(entry) == target:
            return True
    return False

def parse_session_slug(slug):
    """Extract the exact ``task_id`` from ``<agent>-r<n>-<task_id>-<uuid8>``.

    The trailing token is an 8-char hex uuid and the round marker is ``r<n>``;
    everything between the round marker and the uuid -- hyphens included -- is
    the task id, returned verbatim. Returns ``None`` for a slug that does not
    match the expected shape.
    """
    import re
    if not isinstance(slug, str):
        return None
    m = re.match('^(?P<agent>.+?)-r(?P<round>\\d+)-(?P<task_id>.+)-(?P<uuid>[0-9a-fA-F]{8})$', slug)
    if m is None:
        return None
    return m.group('task_id')
def _classify_pidfile_is_live(root, tid) -> bool:
    """True iff ``<root>/state/running/<tid>.pid`` names a live process.

    Reads ONLY the pidfile (never the plan) so liveness can be decided before
    any ``read_text``/``json.loads`` of the product. A pidfile that is missing,
    empty, non-numeric, or whose pid is not signalable (``os.kill(pid, 0)``
    raises ``ESRCH``) is treated as not-live; ``EPERM`` means the process is
    alive but not ours, which still counts as LIVE (fail-closed: do not touch a
    product owned by a running task).
    """
    import errno
    if not tid:
        return False
    pid_path = Path(root) / 'state' / 'running' / (str(tid) + '.pid')
    try:
        raw = pid_path.read_text(encoding='utf-8').strip()
    except OSError:
        return False
    if not raw:
        return False
    try:
        pid = int(raw)
    except (TypeError, ValueError):
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except OSError as exc:
        return getattr(exc, 'errno', None) == errno.EPERM
    return True

def classify_product(root, product_path, *, now=None) -> 'ProductStatus':
    """Single shared status resolver consumed by both report and apply.

    Pure classification: performs NO move/delete/apply and mutates nothing on
    disk, so it is idempotent and safe to call report-first. Ambiguous inputs
    fail closed to :attr:`ProductStatus.CORRUPT` (escalate, never silent
    delete).

    Decision order (intentional):

    1. **LIVE first, before any read.** If a live ``running/<tid>.pid`` pidfile
       exists, OR the product's own mtime is within the write-settle grace
       (default 60 s, evaluated against ``now``), the product is
       :attr:`~ProductStatus.LIVE` -- even when its bytes are unparseable. The
       plan file is never read in this case.
    2. **UNPLANNED** iff ``os.path.lexists(plan_path)`` is False. A broken
       symlink (``lexists`` True) is NOT unplanned.
    3. **FOREIGN** for a symlinked product (never followed/read through).
    4. **CORRUPT** for a directory occupying the plan path (settled).
    5. Otherwise read the RAW plan file (not the ``has_plan`` boolean that
       ``compute_brief_status`` collapses): settled-unparseable -> CORRUPT;
       valid JSON with no JM provenance -> FOREIGN; provenance present but
       wrong-schema (no ``tasks`` list) -> CORRUPT; well-formed -> the healthy
       :attr:`~ProductStatus.PLANNED`.
    """
    import json
    plan_path = Path(product_path)
    if now is None:
        now = time.time()
    grace = _WRITE_SETTLE_GRACE_SEC
    tid = plan_path.stem
    if _classify_pidfile_is_live(root, tid):
        return ProductStatus.LIVE
    if not os.path.lexists(plan_path):
        return ProductStatus.UNPLANNED
    try:
        mtime = os.lstat(plan_path).st_mtime
    except OSError:
        mtime = None
    if mtime is not None and now - mtime < grace:
        return ProductStatus.LIVE
    if os.path.islink(plan_path):
        return ProductStatus.FOREIGN
    if os.path.isdir(plan_path):
        return ProductStatus.CORRUPT
    try:
        data = json.loads(plan_path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return ProductStatus.CORRUPT
    has_provenance = isinstance(data, dict) and (isinstance(data.get('source_brief_sha256'), str) or isinstance(data.get('tasks'), list))
    if not has_provenance:
        return ProductStatus.FOREIGN
    if not isinstance(data.get('tasks'), list):
        return ProductStatus.CORRUPT
    return ProductStatus.PLANNED
@contextmanager
def state_reconcile_lock(state_dir, *, timeout: float=60.0, poll: float=0.05):
    """Acquire/release the single dedicated ``state_reconcile.lock``.

    Yields the :class:`~pathlib.Path` of the held lock file. The lock lives at
    ``<state_dir>/state_reconcile.lock`` and is acquired with an exclusive
    ``O_CREAT | O_EXCL`` create (fail-closed): if another mutator already
    holds it we poll until it is released or ``timeout`` seconds elapse, at
    which point a :class:`TimeoutError` is raised. The lock is removed in a
    ``finally`` block so it is released even if the wrapped body raises.
    """
    sd = Path(state_dir)
    sd.mkdir(parents=True, exist_ok=True)
    lock_path = sd / LOCK_FILENAME
    deadline = time.monotonic() + max(0.0, float(timeout))
    fd = None
    while True:
        try:
            fd = os.open(str(lock_path), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 420)
            break
        except FileExistsError:
            if time.monotonic() >= deadline:
                raise TimeoutError(f'timed out acquiring {lock_path}')
            time.sleep(max(0.0, float(poll)))
    try:
        try:
            os.write(fd, str(os.getpid()).encode('ascii'))
        except OSError:
            pass
        yield lock_path
    finally:
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(str(lock_path))
        except OSError:
            pass
