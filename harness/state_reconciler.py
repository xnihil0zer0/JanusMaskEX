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

class _CleanupProduct:
    """Per-product cleanup outcome carried by a :class:`WorkspaceStatus`.

    Plain attribute object (kept stdlib-only, no ``dataclass`` import) exposing
    ``task_id`` / ``path`` / ``status`` / ``ready`` / ``blocker`` so both report
    and apply agree on a single per-product shape. ``ready`` is the FAIL-CLOSED
    invariant ``blocker is None``: a product is ready only when nothing blocks
    its reconciliation.
    """
    __slots__ = ('task_id', 'path', 'product_path', 'status', 'ready', 'blocker', 'archived_to')

    def __init__(self, task_id, path, status, *, ready, blocker=None, archived_to=None):
        self.task_id = task_id
        self.path = str(path)
        self.product_path = str(path)
        self.status = status
        self.ready = bool(ready)
        self.blocker = blocker
        self.archived_to = str(archived_to) if archived_to is not None else None

    def __repr__(self):
        return '_CleanupProduct(task_id=%r, status=%r, ready=%r, blocker=%r)' % (self.task_id, self.status, self.ready, self.blocker)

class WorkspaceStatus:
    """Aggregate of per-product cleanup outcomes for one workspace ``root``.

    Carries the per-product collection under :attr:`products` plus a derived
    workspace-level :attr:`ready` (True iff every enumerated product is ready).
    Iterable and sized for convenience; the per-product entries are
    :class:`_CleanupProduct` instances.
    """
    __slots__ = ('root', 'mode', 'products', 'ready')

    def __init__(self, root, mode, products):
        self.root = str(root)
        self.mode = mode
        self.products = list(products)
        self.ready = all((p.ready for p in self.products)) if self.products else True

    def __iter__(self):
        return iter(self.products)

    def __len__(self):
        return len(self.products)

    def __repr__(self):
        return 'WorkspaceStatus(root=%r, mode=%r, products=%r)' % (self.root, self.mode, self.products)

def _archive_move_collision_safe(src, archive_dir):
    """Collision-safe, race-tolerant archive move primitive used by apply only.

    Replaces the old ``_move_no_clobber`` / ``src.replace`` pattern. Behaviour:

    * **Race-tolerant (no TOCTOU).** There is deliberately NO ``exists()``
      pre-check guarding the SOURCE: we attempt the move directly and treat a
      vanished source (``FileNotFoundError`` / ``ENOENT``) as a recorded SUCCESS
      (returns ``None`` -- nothing landed, nothing to do).
    * **Never overwrite.** On a destination collision the archived name is
      suffix-disambiguated (``<stem>.<n><suffix>``) until it lands on a fresh,
      unique path, so a pre-existing archived artifact is never clobbered. The
      only existence probe is on the DESTINATION candidate, never the source.
    * **Never strand.** If ``shutil.move`` copied to the candidate but then
      failed to remove the source (so the move did not fully complete), the
      partial copy is undone before the error is re-raised -- the source is left
      intact and the archive is left clean, so the per-product error handler can
      record an honest blocker without a stranded duplicate.

    Returns the destination :class:`~pathlib.Path` the artifact landed on, or
    ``None`` when the source was already gone (ENOENT == success).
    """
    import shutil
    import errno as _errno
    src_path = Path(src)
    dst_dir = Path(archive_dir)
    dst_dir.mkdir(parents=True, exist_ok=True)
    name = src_path.name
    stem = src_path.stem
    suffix = src_path.suffix
    attempt = 0
    while True:
        if attempt == 0:
            candidate = dst_dir / name
        else:
            candidate = dst_dir / ('%s.%d%s' % (stem, attempt, suffix))
        if os.path.lexists(candidate):
            attempt += 1
            continue
        try:
            shutil.move(str(src_path), str(candidate))
            return candidate
        except FileNotFoundError:
            return None
        except OSError as exc:
            if getattr(exc, 'errno', None) == _errno.ENOENT:
                return None
            try:
                if os.path.lexists(src_path) and os.path.lexists(candidate):
                    if os.path.isdir(candidate) and (not os.path.islink(candidate)):
                        shutil.rmtree(candidate, ignore_errors=True)
                    else:
                        os.remove(candidate)
            except OSError:
                pass
            raise

def cleanup_state(root, *, mode='report') -> 'WorkspaceStatus':
    """Report-first state-reconciliation action engine for one workspace ``root``.

    ``mode="report"`` is a PURE READ: it classifies every product under
    ``<root>/products/`` via the shared :func:`classify_product` resolver (and
    its discriminator library) and returns a :class:`WorkspaceStatus`
    enumerating each product's status / blocker / ready WITHOUT touching disk
    (``_autowork_archive/`` is never created or written); it is idempotent.

    ``mode="apply"`` drives the classify-product action table. Each NON-LIVE
    *archivable* product (PLANNED / UNPLANNED / CORRUPT) is relocated into
    ``<root>/_autowork_archive/`` via the collision-safe
    :func:`_archive_move_collision_safe` primitive (a plain move -- NEVER
    ``git mv``); the classification is identical to report mode (report-first),
    so a second report after apply is convergent on the NON-LIVE subset.

    FAIL-CLOSED / MOVE-NEVER-DELETE invariants:

    * LIVE products (a live ``running/<tid>.pid`` or within the write-settle
      grace) and FOREIGN products (symlinked / non-JM-owned) are NEVER moved in
      either mode; they PERSIST in place each carrying an explicit blocker and
      ``ready == False``.
    * Moves are race-tolerant: a vanished source (ENOENT) is a recorded success
      with no TOCTOU ``exists()`` pre-check.
    * Per-product error containment: a non-ENOENT failure on one product is
      captured as THAT product's blocker (``ready == False``) and the sweep
      continues -- it never aborts the whole reconciliation.
    """
    if mode not in ('report', 'apply'):
        raise ValueError("mode must be 'report' or 'apply', got %r" % (mode,))
    root_path = Path(root)
    products_dir = root_path / 'products'
    archive_dir = root_path / '_autowork_archive'
    now = time.time()
    archivable = frozenset((ProductStatus.PLANNED, ProductStatus.UNPLANNED, ProductStatus.CORRUPT))
    try:
        entries = sorted(products_dir.iterdir())
    except OSError:
        entries = []
    outcomes = []
    for entry in entries:
        product_path = entry
        tid = product_path.stem
        status = None
        blocker = None
        ready = True
        archived_to = None
        try:
            status = classify_product(str(root_path), str(product_path), now=now)
            if status == ProductStatus.LIVE:
                blocker = 'LIVE: product is owned by a running task (live running/<tid>.pid or within the write-settle grace); never archived'
                ready = False
            elif status == ProductStatus.FOREIGN:
                blocker = 'FOREIGN: symlinked or non-JM-owned product; never followed or archived'
                ready = False
            elif status in archivable:
                if mode == 'apply':
                    archived_to = _archive_move_collision_safe(product_path, archive_dir)
            else:
                blocker = '%s: unhandled classification; persisted fail-closed' % (status,)
                ready = False
        except Exception as exc:
            blocker = '%s: %s' % (type(exc).__name__, exc)
            ready = False
        outcomes.append(_CleanupProduct(task_id=tid, path=product_path, status=status if status is not None else 'UNKNOWN', ready=ready, blocker=blocker, archived_to=archived_to))
    return WorkspaceStatus(root=str(root_path), mode=mode, products=outcomes)
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
