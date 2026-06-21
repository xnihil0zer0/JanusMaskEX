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
    pid_path = _running_dir(root) / (str(tid) + '.pid')
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

    Also carries an advisory, detect-only :attr:`clutter_candidates` list of
    ``{'path', 'reason'}`` dicts (sorted by path, forward-slash relative paths).
    Clutter is NEVER moved/archived/deleted; it only folds into :attr:`ready`
    (a workspace with outstanding clutter is not ready). The new constructor
    parameter is optional/keyword-defaulted so existing positional callers --
    e.g. ``WorkspaceStatus(root, mode, [])`` -- keep working unchanged.
    """
    __slots__ = ('root', 'mode', 'products', 'clutter_candidates', 'ready')

    def __init__(self, root, mode, products, clutter_candidates=None):
        self.root = str(root)
        self.mode = mode
        self.products = list(products)
        self.clutter_candidates = list(clutter_candidates) if clutter_candidates else []
        self.ready = (all((p.ready for p in self.products)) if self.products else True) and (not self.clutter_candidates)

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
    so a second report after apply is convergent on the NON-LIVE subset. apply
    mode additionally runs the disk reapers (orphaned-workdir rmtree under
    :func:`agent_workroot`, log/drain age-out, impl_progress.jsonl locked-atomic
    compaction, and ``_autowork_archive`` retention prune) via
    :func:`reap_stale_disk` -- all under ``state_reconcile_lock`` and NEVER under
    ``git_commit.lock`` across the slow op -- followed by
    :func:`_reconcile_stale_ledger_heads`; both passes are fail-closed and
    idempotent and compact (never wipe) the ledger.

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

    CLUTTER (advisory, detect-only): an additional PURE-READ scan surfaces
    deterministic ``clutter_candidates`` on the returned :class:`WorkspaceStatus`.
    Clutter is NEVER moved, archived, or deleted in either mode -- the scan runs
    identically under report and apply and only folds into ``ready``. Each
    candidate is a ``{'path', 'reason'}`` dict with a forward-slash root-relative
    path; the list is sorted by path. Every directory read / stat / json parse is
    best-effort (errors skip the entry) so the scan never raises.
    """
    if mode not in ('report', 'apply'):
        raise ValueError("mode must be 'report' or 'apply', got %r" % (mode,))
    root_path = Path(root)
    archive_dir = root_path / '_autowork_archive'
    now = time.time()
    archivable = frozenset((ProductStatus.PLANNED, ProductStatus.UNPLANNED, ProductStatus.CORRUPT))
    products = []
    try:
        for entry in sorted(root_path.glob('brief_hooks_*.md')):
            products.append((entry, entry.stem[len('brief_hooks_'):]))
    except OSError:
        pass
    try:
        for entry in sorted((root_path / 'state' / 'plans').iterdir()):
            products.append((entry, entry.stem))
    except OSError:
        pass
    outcomes = []
    for product_path, tid in products:
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
    if mode == 'apply':
        try:
            reap_stale_disk(root_path, now=now)
        except Exception:
            pass
        try:
            _reconcile_stale_ledger_heads(root_path)
        except Exception:
            pass

    CLUTTER_AGE_SECONDS = 604800
    KEEP_DOCS = frozenset((
        'README.md',
        'PLAN_autonomous_resume.md',
        'factory-work-handoff.md',
        'AUTONOMY_GAPS.md',
        'DESIGN_self_healing_remediation_agent.md',
        'INTERVENTION_PLAN_v2.md',
        'INTERVENTION_ANALYSIS_02_git_selfheal.md',
        'INTERVENTION_ANALYSIS_03_archive_forensics.md',
        'PROVENANCE_REVIEW_01_internal_jm.md',
        'PROVENANCE_REVIEW_02_external_ngv2.md',
        'PROVENANCE_REVIEW_04_roi_priority.md',
    ))

    def _scan_clutter():
        candidates = []

        def _rel(p):
            try:
                rel = os.path.relpath(str(p), str(root_path))
            except (OSError, ValueError, Exception):
                rel = str(p)
            return rel.replace(os.sep, '/')

        def _mtime(p):
            try:
                return os.lstat(str(p)).st_mtime
            except (OSError, ValueError, Exception):
                return None

        # root_doc_unkept: top-level (non-recursive) <root>/*.md, basename not in
        # KEEP_DOCS, aged beyond CLUTTER_AGE_SECONDS.
        try:
            for entry in root_path.glob('*.md'):
                try:
                    if not entry.is_file():
                        continue
                    if entry.name in KEEP_DOCS:
                        continue
                    mtime = _mtime(entry)
                    if mtime is None:
                        continue
                    if now - mtime > CLUTTER_AGE_SECONDS:
                        candidates.append({'path': _rel(entry), 'reason': 'root_doc_unkept'})
                except (OSError, ValueError, Exception):
                    continue
        except (OSError, ValueError, Exception):
            pass

        # planning_dump_idle: gated entirely on <root>/state/planning/merged_plan.json
        # existing and parsing to a dict whose 'tasks' == [].
        try:
            planning_dir = root_path / 'state' / 'planning'
            merged_plan = planning_dir / 'merged_plan.json'
            idle = False
            try:
                import json as _json
                data = _json.loads(merged_plan.read_text(encoding='utf-8'))
                if isinstance(data, dict) and data.get('tasks') == []:
                    idle = True
            except (OSError, ValueError, Exception):
                idle = False
            if idle:
                _SKIP = frozenset(('merged_plan.json', 'amendment_report.json'))
                try:
                    for entry in planning_dir.glob('*.json'):
                        try:
                            name = entry.name
                            if name in _SKIP:
                                continue
                            if not (name.startswith('plan_') or name.startswith('wire_up') or name.startswith('critique')):
                                continue
                            candidates.append({'path': _rel(entry), 'reason': 'planning_dump_idle'})
                        except (OSError, ValueError, Exception):
                            continue
                except (OSError, ValueError, Exception):
                    pass
        except (OSError, ValueError, Exception):
            pass

        # scratch_aged: direct children of <root>/_autowork_scratch/ aged beyond
        # CLUTTER_AGE_SECONDS.
        try:
            scratch_dir = root_path / '_autowork_scratch'
            for entry in scratch_dir.iterdir():
                try:
                    mtime = _mtime(entry)
                    if mtime is None:
                        continue
                    if now - mtime > CLUTTER_AGE_SECONDS:
                        candidates.append({'path': _rel(entry), 'reason': 'scratch_aged'})
                except (OSError, ValueError, Exception):
                    continue
        except (OSError, ValueError, Exception):
            pass

        candidates.sort(key=lambda c: c['path'])
        return candidates

    try:
        clutter_candidates = _scan_clutter()
    except Exception:
        clutter_candidates = []

    return WorkspaceStatus(root=str(root_path), mode=mode, products=outcomes, clutter_candidates=clutter_candidates)

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
    import threading
    global _local_locks
    if '_local_locks' not in globals():
        _local_locks = threading.local()
    if not hasattr(_local_locks, 'active'):
        _local_locks.active = {}
    sd = Path(state_dir)
    sd.mkdir(parents=True, exist_ok=True)
    lock_path = sd / LOCK_FILENAME
    resolved_path = str(lock_path.resolve())
    if resolved_path in _local_locks.active:
        _local_locks.active[resolved_path] += 1
        try:
            yield lock_path
        finally:
            _local_locks.active[resolved_path] -= 1
            if _local_locks.active[resolved_path] <= 0:
                _local_locks.active.pop(resolved_path, None)
        return
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
    _local_locks.active[resolved_path] = 1
    try:
        try:
            os.write(fd, str(os.getpid()).encode('ascii'))
        except OSError:
            pass
        yield lock_path
    finally:
        _local_locks.active.pop(resolved_path, None)
        try:
            os.close(fd)
        except OSError:
            pass
        try:
            os.unlink(str(lock_path))
        except OSError:
            pass

def agent_workroot(root):
    """Return the sibling agent work-root that PEERS the repo at ``root``.

    The live disk leak is the sibling ``<repo>.parent/<repo>_agentwork`` tree
    (e.g. ``.../JanusMaskJR_agentwork``) that lives OUTSIDE the repo and holds
    the per-agent ``<agent>/<workdir>`` worktrees the reaper sweeps. The path is
    derived purely from ``root`` so callers and the reaper agree on one location;
    it is never created here (pure path computation).
    """
    p = Path(root)
    return p.parent / (p.name + '_agentwork')

def external_staging_root(root):
    """Return the external staging root, a PEER of the agent dirs under
    :func:`agent_workroot`.

    Dirs at/under this path are reclaimed only via the worktree path and are
    REFUSED by the orphaned-workdir rmtree sweep (fail-closed). Pure path
    computation -- never created here.
    """
    return agent_workroot(root) / 'external_staging'

def git_worktree_list(root):
    """Return the registered worktree paths from ``git worktree list``.

    Fail-closed: any subprocess/parse error or non-zero return yields an empty
    list (the reaper then relies on the external-staging guard alone). Parsed
    from ``--porcelain`` ``worktree <path>`` lines. Exposed at module scope so
    it can be substituted in unit tests.
    """
    import subprocess
    try:
        proc = subprocess.run(['git', '-C', str(root), 'worktree', 'list', '--porcelain'], capture_output=True, text=True)
    except (OSError, ValueError):
        return []
    if getattr(proc, 'returncode', 1) != 0:
        return []
    paths = []
    for line in (proc.stdout or '').splitlines():
        if line.startswith('worktree '):
            paths.append(line[len('worktree '):].strip())
    return paths

def _reap_resolve(p):
    """Normalised real path used for symlink/relative-proof guard comparison."""
    try:
        return os.path.normpath(os.path.realpath(str(p)))
    except (OSError, ValueError):
        return os.path.normpath(str(p))

def _reap_is_at_or_under(child, parent):
    """True iff resolved ``child`` is ``parent`` itself or nested beneath it."""
    c = _reap_resolve(child)
    pa = _reap_resolve(parent)
    if c == pa:
        return True
    return c.startswith(pa + os.sep)

def _reap_rmtree_onerror(func, path, exc_info):
    """``shutil.rmtree`` onerror handler: swallow per-entry races/permission
    errors so a single failure never aborts the whole reaper (fail-closed)."""
    return None

def _reap_worktree_set(root):
    """Resolved set of registered worktree paths, tolerant of the
    :func:`git_worktree_list` substitution arity."""
    fn = git_worktree_list
    try:
        listed = fn(root)
    except TypeError:
        try:
            listed = fn()
        except Exception:
            listed = []
    except Exception:
        listed = []
    out = set()
    for w in listed or []:
        try:
            out.add(_reap_resolve(w))
        except Exception:
            continue
    return out

def reap_orphaned_workdirs(root, *, now=None, grace=60.0):
    """rmtree orphaned ``<agent>/<workdir>`` dirs under :func:`agent_workroot`.

    For every workdir under each agent dir, the dir is rmtree'd (with an onerror
    handler) ONLY when ALL of the following hold:

    * it is NOT at/under :func:`external_staging_root` (REFUSED -- reclaimed via
      the worktree path),
    * it is NOT a registered ``git worktree list`` path (REFUSED),
    * NO live ``running/*.pid`` has a PARSED task_id EXACTLY EQUAL to the
      workdir's parsed task_id (substring/prefix pid matches are still eligible),
    * the workdir mtime is older than ``grace`` (``now - mtime > grace``).

    Paths are resolved before the guard comparison so symlinks/relatives cannot
    bypass it; symlinked agent/workdirs are skipped. Each rmtree is contained so
    a permission/race error on one workdir never aborts the sweep. As a final
    fail-safe step the sweep also invokes the module-global
    :func:`detect_and_heal_stalls` watchdog (contained, default-off) so a wedged
    in-flight task can be self-healed; the watchdog never alters the returned
    list. Returns the list of reaped workdir paths (idempotent: a second run
    reaps nothing).
    """
    import shutil
    if now is None:
        now = time.time()
    aw = agent_workroot(root)
    staging = external_staging_root(root)
    worktrees = _reap_worktree_set(root)
    running_dir = _running_dir(root)
    reaped = []
    try:
        agent_dirs = sorted(aw.iterdir())
    except OSError:
        agent_dirs = []
    for agent_dir in agent_dirs:
        try:
            if agent_dir.is_symlink() or not agent_dir.is_dir():
                continue
        except OSError:
            continue
        if _reap_is_at_or_under(agent_dir, staging):
            continue
        try:
            workdirs = sorted(agent_dir.iterdir())
        except OSError:
            continue
        for workdir in workdirs:
            try:
                if workdir.is_symlink() or not workdir.is_dir():
                    continue
            except OSError:
                continue
            if _reap_is_at_or_under(workdir, staging):
                continue
            if _reap_resolve(workdir) in worktrees:
                continue
            task_id = parse_session_slug(workdir.name)
            if task_id and task_id_has_live_pidfile(running_dir, task_id):
                continue
            try:
                mtime = workdir.stat().st_mtime
            except OSError:
                continue
            if now - mtime <= grace:
                continue
            try:
                shutil.rmtree(str(workdir), onerror=_reap_rmtree_onerror)
                reaped.append(str(workdir))
            except OSError:
                continue
    try:
        detect_and_heal_stalls(root, now=now)
    except Exception:
        pass
    return reaped

def compact_impl_progress_ledger(root, *, allow=None):
    """Locked-atomic compaction of ``<root>/state/impl_progress.jsonl``.

    Retains the consumer-allowlist rows -- every well-formed dict row carrying a
    non-empty string ``task_id`` (plus any row whose ``event``/``phase`` is in an
    explicit ``allow`` set, when provided) -- and DROPS malformed/non-dict/blank
    lines fail-closed. The surviving rows are written into a temp file in the
    ledger's own dir under a continuously-held per-target flock and swapped in
    with :func:`os.replace`, so the rewrite is atomic and consistent with the
    jsonl appenders.

    NEVER wipes the ledger: if nothing would survive the file is left intact, and
    an already-clean ledger is left byte-for-byte untouched (idempotent). Returns
    True iff a compacting rewrite was performed.
    """
    import json
    import fcntl
    import tempfile
    ledger_path = Path(root) / 'state' / 'impl_progress.jsonl'
    lock_path = Path(str(ledger_path) + '.lock')
    try:
        text = ledger_path.read_text(encoding='utf-8')
    except OSError:
        return False
    retained = []
    dropped = False
    for line in text.splitlines():
        s = line.strip()
        if not s:
            dropped = True
            continue
        try:
            obj = json.loads(s)
        except ValueError:
            dropped = True
            continue
        if not isinstance(obj, dict):
            dropped = True
            continue
        tid = obj.get('task_id')
        keep = isinstance(tid, str) and bool(tid)
        if not keep and allow is not None:
            keep = obj.get('event') in allow or obj.get('phase') in allow
        if keep:
            retained.append(obj)
        else:
            dropped = True
    if not retained:
        return False
    if not dropped:
        return False
    payload = '\n'.join((json.dumps(r) for r in retained)) + '\n'
    lock_fd = None
    try:
        lock_fd = os.open(str(lock_path), os.O_CREAT | os.O_RDWR, 420)
        try:
            fcntl.flock(lock_fd, fcntl.LOCK_EX)
        except OSError:
            pass
        fd, tmp = tempfile.mkstemp(dir=str(ledger_path.parent), prefix='.impl_progress.', suffix='.tmp')
        try:
            os.write(fd, payload.encode('utf-8'))
            try:
                os.fsync(fd)
            except OSError:
                pass
        finally:
            os.close(fd)
        os.replace(tmp, str(ledger_path))
        return True
    except OSError:
        return False
    finally:
        if lock_fd is not None:
            try:
                fcntl.flock(lock_fd, fcntl.LOCK_UN)
            except OSError:
                pass
            try:
                os.close(lock_fd)
            except OSError:
                pass

def age_out_logs(root, *, now=None, max_age_sec=1209600.0):
    """Age-out log/drain files older than ``max_age_sec`` under known log dirs.

    Scans ``<root>/state/logs``, ``<root>/state/drain`` and ``<root>/logs`` and
    unlinks plain files whose mtime is older than the age-out window; missing
    dirs and per-file errors are skipped fail-closed. Directories are left
    untouched. Returns the list of removed file paths.
    """
    if now is None:
        now = time.time()
    removed = []
    candidates = [Path(root) / 'state' / 'logs', Path(root) / 'state' / 'drain', Path(root) / 'logs']
    for d in candidates:
        try:
            entries = sorted(d.iterdir())
        except OSError:
            continue
        for e in entries:
            try:
                if e.is_dir() and (not e.is_symlink()):
                    continue
                mtime = e.stat().st_mtime
            except OSError:
                continue
            if now - mtime > max_age_sec:
                try:
                    e.unlink()
                    removed.append(str(e))
                except OSError:
                    continue
    return removed

def prune_autowork_archive(root, *, now=None, max_age_sec=1209600.0):
    """Prune ``<root>/_autowork_archive`` entries beyond the retention bound.

    Removes archive entries (files via unlink, dirs via rmtree with the onerror
    handler) whose mtime is older than ``max_age_sec``; freshly archived entries
    stay within the bound and are kept. Missing archive dir and per-entry errors
    are skipped fail-closed. Returns the list of pruned entry paths.
    """
    import shutil
    if now is None:
        now = time.time()
    archive_dir = Path(root) / '_autowork_archive'
    removed = []
    try:
        entries = sorted(archive_dir.iterdir())
    except OSError:
        return removed
    for e in entries:
        try:
            mtime = e.stat().st_mtime
        except OSError:
            continue
        if now - mtime <= max_age_sec:
            continue
        try:
            if e.is_dir() and (not e.is_symlink()):
                shutil.rmtree(str(e), onerror=_reap_rmtree_onerror)
            else:
                e.unlink()
            removed.append(str(e))
        except OSError:
            continue
    return removed

def reap_stale_disk(root, *, now=None):
    """Run the disk reapers for one workspace ``root`` under the shared lock.

    The entire slow section -- orphaned-workdir rmtree, impl_progress.jsonl
    locked-atomic compaction, log/drain age-out, ``_autowork_archive`` retention
    prune, and the spent-brief reaper -- is held under
    :func:`state_reconcile_lock` and NEVER under ``git_commit.lock`` (a multi-GB
    rmtree under the commit lock would blow the 60s accept deadline). Each reaper
    is individually contained so one failure never aborts the others; the pass is
    fail-closed and idempotent. Returns a dict summarising what each reaper did
    (including the ``spent_briefs`` slugs archived this pass).
    """
    if now is None:
        now = time.time()
    root_path = Path(root)
    state_dir = root_path / 'state'
    results = {'workdirs': [], 'ledger_compacted': False, 'logs': [], 'archive': [], 'spent_briefs': []}
    with state_reconcile_lock(state_dir):
        try:
            results['workdirs'] = reap_orphaned_workdirs(root_path, now=now)
        except Exception:
            results['workdirs'] = []
        try:
            results['ledger_compacted'] = compact_impl_progress_ledger(root_path)
        except Exception:
            results['ledger_compacted'] = False
        try:
            results['logs'] = age_out_logs(root_path, now=now)
        except Exception:
            results['logs'] = []
        try:
            results['archive'] = prune_autowork_archive(root_path, now=now)
        except Exception:
            results['archive'] = []
        try:
            results['spent_briefs'] = reap_spent_briefs(root_path)
        except Exception:
            results['spent_briefs'] = []
    return results
from harness import target_bootstrap

def is_owned(root) -> bool:
    try:
        return target_bootstrap._read_valid_marker(Path(root)) is not None
    except Exception:
        return False

def is_allowlisted(root) -> bool:
    try:
        return target_bootstrap._working_dir_allowed(Path(root))
    except Exception:
        return False

def has_staged_or_unmerged(root) -> bool:
    import subprocess
    try:
        proc = subprocess.run(['git', 'status', '--porcelain'], cwd=str(root), capture_output=True, text=True, check=True)
        for line in proc.stdout.splitlines():
            if len(line) >= 2:
                x = line[0]
                if x not in (' ', '?', '!'):
                    return True
        return False
    except Exception:
        return True

def prepare_workspace(root, *, mode='apply') -> WorkspaceStatus:
    try:
        if not is_owned(root):
            status = WorkspaceStatus(root, mode, [])
            status.ready = False
            return status
        if not is_allowlisted(root):
            status = WorkspaceStatus(root, mode, [])
            status.ready = False
            return status
        git_dir = Path(root) / '.git'
        if not git_dir.exists():
            status = WorkspaceStatus(root, mode, [])
            status.ready = False
            return status
        if target_bootstrap._is_dirty(Path(root)):
            status = WorkspaceStatus(root, mode, [])
            status.ready = False
            return status
        if has_staged_or_unmerged(root):
            status = WorkspaceStatus(root, mode, [])
            status.ready = False
            return status
    except Exception:
        status = WorkspaceStatus(root, mode, [])
        status.ready = False
        return status
    state_dir = Path(root) / 'state'
    try:
        with state_reconcile_lock(state_dir):
            staging = external_staging_root(root)
            if staging.exists() and staging.is_dir():
                worktrees = _reap_worktree_set(root)
                try:
                    entries = sorted(staging.iterdir())
                except OSError:
                    entries = []
                for entry in entries:
                    try:
                        if entry.is_symlink() or not entry.is_dir():
                            continue
                    except OSError:
                        continue
                    if _reap_resolve(entry) not in worktrees:
                        import shutil
                        try:
                            shutil.rmtree(str(entry), onerror=_reap_rmtree_onerror)
                        except OSError:
                            continue
            return cleanup_state(root, mode=mode)
    except Exception:
        status = WorkspaceStatus(root, mode, [])
        status.ready = False
        return status

def _reconcile_stale_ledger_heads(root) -> None:
    """Append a literal ``event == 'task_blocked'`` pop-row for every accepted
    tid whose recorded ``commit_sha`` is NOT an ancestor of HEAD.

    The pop-row's ``event`` is the literal ``'task_blocked'`` token consumed by
    ``compute_brief_status`` replay (a ``'reconcile_revert'`` name would be
    inert); the head-revert provenance rides on a SEPARATE ``reconcile_reason``
    field, never renaming or repurposing an existing replay event. The ledger
    is COMPACTED (malformed/non-dict lines dropped) and rewritten with the
    surviving rows plus the appended pop-rows -- it is NEVER wiped to empty.
    The pass is FAIL-CLOSED (any error is contained; the ledger is left intact)
    and IDEMPOTENT (a tid already carrying a ``task_blocked`` pop-row is never
    popped again, so a re-run appends no duplicate).
    """
    import json
    import subprocess
    import datetime
    root_path = Path(root)
    ledger_path = root_path / 'state' / 'impl_progress.jsonl'
    try:
        text = ledger_path.read_text(encoding='utf-8')
    except OSError:
        return
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except ValueError:
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    already_blocked = set()
    for r in rows:
        if r.get('event') == 'task_blocked':
            tid = r.get('task_id')
            if isinstance(tid, str) and tid:
                already_blocked.add(tid)
    accepted = {}
    for r in rows:
        if r.get('phase') == 'accepted':
            tid = r.get('task_id')
            sha = r.get('commit_sha')
            if isinstance(tid, str) and tid and isinstance(sha, str) and sha and (tid not in accepted):
                accepted[tid] = sha

    def _is_ancestor_returncode(sha):
        try:
            proc = subprocess.run(['git', '-C', str(root_path), 'merge-base', '--is-ancestor', sha, 'HEAD'], capture_output=True, text=True)
        except (OSError, ValueError):
            return None
        return proc.returncode
    ts = datetime.datetime.now(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    new_pops = []
    for tid, sha in accepted.items():
        if tid in already_blocked:
            continue
        rc = _is_ancestor_returncode(sha)
        if rc == 1:
            new_pops.append({'ts': ts, 'phase': 'autowork', 'task_id': tid, 'event': 'task_blocked', 'reconcile_reason': 'head_revert: accepted commit_sha %s is not an ancestor of HEAD' % sha, 'commit_sha': sha})
            already_blocked.add(tid)
    if not new_pops:
        return
    out_rows = rows + new_pops
    payload = '\n'.join((json.dumps(r) for r in out_rows)) + '\n'
    if not payload.strip():
        return
    try:
        ledger_path.write_text(payload, encoding='utf-8')
    except OSError:
        return

def _watchdog_truthy(val) -> bool:
    """Conservative truthiness for watchdog gate / flag values.

    Accepts bools, non-zero numbers, and the common affirmative string tokens
    (case-insensitive); everything else -- including ``None`` and unknown
    strings -- is falsey, so the watchdog stays OFF unless explicitly armed.
    """
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return val != 0
    if isinstance(val, str):
        return val.strip().lower() in ('1', 'true', 'yes', 'on', 'enabled')
    return False

def _watchdog_cfg_section(config) -> dict:
    """Defensively locate the ``autowork.watchdog`` config section.

    Tolerates a missing / None / non-dict ``config`` (returns ``{}``) and
    accepts either a bare watchdog dict, a ``{'watchdog': {...}}`` wrapper, or a
    nested ``{'autowork': {'watchdog': {...}}}`` shape. Never raises.
    """
    if not isinstance(config, dict):
        return {}
    sub = config.get('watchdog')
    if isinstance(sub, dict):
        return sub
    aw = config.get('autowork')
    if isinstance(aw, dict):
        sub = aw.get('watchdog')
        if isinstance(sub, dict):
            return sub
    return config

def _watchdog_enabled(config) -> bool:
    """Fail-safe arming gate; defaults OFF.

    The watchdog is armed iff the ``JM_WATCHDOG_ENABLED`` environment variable is
    truthy, or (failing that) the parsed config section sets ``enabled`` truthy.
    With no env var and no config the result is ``False`` -- the watchdog is a
    pure no-op by default.
    """
    env = os.environ.get('JM_WATCHDOG_ENABLED')
    if _watchdog_truthy(env):
        return True
    section = _watchdog_cfg_section(config)
    return _watchdog_truthy(section.get('enabled'))

def _watchdog_config(config) -> dict:
    """Parse watchdog tunables with conservative defaults.

    Returns ``idle_grace_sec`` (default 1800s) and ``max_retries`` (default 3),
    coercing / validating each defensively so a malformed value can never
    disable the bound or make detection over-eager.
    """
    section = _watchdog_cfg_section(config)

    def _coerce(key, default, cast):
        try:
            raw = section.get(key)
        except Exception:
            return default
        if raw is None:
            return default
        try:
            return cast(raw)
        except (TypeError, ValueError):
            return default
    idle_grace = _coerce('idle_grace_sec', 1800.0, float)
    if not idle_grace or idle_grace < 0:
        idle_grace = 1800.0
    max_retries = _coerce('max_retries', 3, int)
    if max_retries < 1:
        max_retries = 3
    return {'idle_grace_sec': float(idle_grace), 'max_retries': int(max_retries)}

def _watchdog_parse_iso(ts_raw):
    """Parse an ISO-8601 ``%Y-%m-%dT%H:%M:%SZ`` ledger ts to epoch seconds.

    Returns ``None`` for anything missing / unparseable (fail-safe -- an
    unreadable ts contributes no staleness evidence). A trailing ``Z`` and
    explicit offsets are both tolerated.
    """
    import datetime
    if not isinstance(ts_raw, str) or not ts_raw.strip():
        return None
    s = ts_raw.strip()
    try:
        dt = datetime.datetime.strptime(s, '%Y-%m-%dT%H:%M:%SZ')
        return dt.replace(tzinfo=datetime.timezone.utc).timestamp()
    except (ValueError, TypeError):
        pass
    try:
        s2 = s[:-1] + '+00:00' if s.endswith('Z') else s
        dt = datetime.datetime.fromisoformat(s2)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=datetime.timezone.utc)
        return dt.timestamp()
    except (ValueError, TypeError):
        return None

def _watchdog_ledger_newest(ledger_path) -> dict:
    """Map each task id to its NEWEST parseable ledger ts (epoch seconds).

    Reads the shared impl_progress JSONL one object per line; blank lines,
    non-JSON lines, non-dict rows, rows without a string ``task_id``, and rows
    with an unparseable ``ts`` are all skipped silently. A task with no parseable
    row simply does not appear in the result (no staleness evidence -> the
    watchdog stands down for it).
    """
    import json
    newest = {}
    try:
        text = Path(ledger_path).read_text(encoding='utf-8')
    except OSError:
        return newest
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if not isinstance(row, dict):
            continue
        tid = row.get('task_id')
        if not (isinstance(tid, str) and tid):
            continue
        epoch = _watchdog_parse_iso(row.get('ts'))
        if epoch is None:
            continue
        prev = newest.get(tid)
        if prev is None or epoch > prev:
            newest[tid] = epoch
    return newest

def _watchdog_bump_attempt(watchdog_dir, task_id) -> int:
    """Durably increment and return the recurring-stall attempt count for a task.

    The counter map persists at ``<watchdog_dir>/attempts.json`` so attempt
    state survives across reconciler sweeps (the watchdog runs once per sweep,
    not in a hot loop). Read / parse failures degrade to a fresh map; the
    rewrite is temp-file + ``os.replace`` atomic and fully contained.
    """
    import json
    path = Path(watchdog_dir) / 'attempts.json'
    data = {}
    try:
        loaded = json.loads(path.read_text(encoding='utf-8'))
        if isinstance(loaded, dict):
            data = loaded
    except (OSError, ValueError):
        data = {}
    try:
        cur = int(data.get(task_id, 0))
    except (TypeError, ValueError):
        cur = 0
    cur += 1
    data[task_id] = cur
    try:
        Path(watchdog_dir).mkdir(parents=True, exist_ok=True)
        tmp = path.with_name('attempts.json.tmp')
        tmp.write_text(json.dumps(data), encoding='utf-8')
        os.replace(str(tmp), str(path))
    except OSError:
        pass
    return cur

def _watchdog_write_escalation(watchdog_dir, task_id, now, attempts, max_retries, last_ts) -> bool:
    """Write the JSON escalation marker for a retry-exhausted stall.

    The marker lands at ``<watchdog_dir>/escalation_<task_id>.json`` and carries
    the task id, the live_idle classification, the attempt budget, and a UTC
    timestamp. Returns True on success; any I/O failure is contained and returns
    False (the sweep degrades, never raises).
    """
    import json
    import datetime
    marker = Path(watchdog_dir) / ('escalation_%s.json' % (task_id,))
    try:
        escalated_at = datetime.datetime.fromtimestamp(float(now), datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except (TypeError, ValueError, OSError, OverflowError):
        escalated_at = ''
    payload = {'task_id': task_id, 'kind': 'live_idle', 'reason': 'retry_exhausted', 'attempts': int(attempts), 'max_retries': int(max_retries), 'last_progress_ts': last_ts, 'escalated_at': escalated_at}
    try:
        Path(watchdog_dir).mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding='utf-8')
        return True
    except OSError:
        return False

def _watchdog_terminate(raw) -> None:
    """Best-effort SIGKILL of a wedged worker pid; NEVER signals our own process.

    Fully contained: a non-numeric pid, a pid equal to the current process, or
    any ``os.kill`` failure (already gone / not permitted) is swallowed.
    Clearing the processing claim -- not the kill -- is the load-bearing
    self-heal step, so a failed signal never blocks the requeue.
    """
    import signal
    try:
        pid = int(str(raw).strip())
    except (TypeError, ValueError):
        return
    if pid <= 0:
        return
    try:
        if pid == os.getpid():
            return
    except OSError:
        return
    try:
        os.kill(pid, signal.SIGKILL)
    except Exception:
        pass

def detect_and_heal_stalls(root, *, config=None, now=None) -> dict:
    """Per-task detect-and-self-heal watchdog for wedged in-flight tasks.

    FAIL-SAFE / DEFAULT-OFF: a no-op unless armed via the ``JM_WATCHDOG_ENABLED``
    environment variable (or an explicit ``enabled`` config flag). When armed it
    sweeps the canonical running-pidfile dir
    (``<root>/state/control/autowork/running``) and, for each in-flight task,
    classifies the claim against the shared impl_progress ledger:

    * ``live_idle`` -- the pidfile names a LIVE pid (``os.kill(pid, 0)`` does not
      raise ``ESRCH``; ``EPERM`` counts as live, fail-closed) AND the newest
      parseable ledger ts for that task is older than the idle grace. This is the
      only kind that is self-healed: the wedged process is best-effort killed
      (never our own pid) and its processing claim (the pidfile) is cleared so
      dispatch can re-pick the task. The progress ledger itself is preserved.
    * ``dead_mid_flight`` -- the pidfile names a dead pid. Left untouched here
      (the orphan / zombie reapers own that surface); it is never a stall.
    * ``retry_exhausted`` -- a ``live_idle`` task whose durable attempt count
      (tracked under ``state/control/autowork/watchdog/``) has reached the bound;
      a JSON escalation marker is written.

    Tasks with no parseable ledger evidence (missing / corrupt ledger or only
    fresh rows) are NEVER healed -- absent confirmed staleness the watchdog
    stands down. Every filesystem / parse step is contained so the sweep never
    raises. Returns a dict summarising the sweep.
    """
    result = {'enabled': False, 'detected': [], 'healed': [], 'escalated': [], 'dead': []}
    if not _watchdog_enabled(config):
        return result
    result['enabled'] = True
    if now is None:
        now = time.time()
    cfg = _watchdog_config(config)
    idle_grace = cfg['idle_grace_sec']
    max_retries = cfg['max_retries']
    root_path = Path(root)
    running_dir = _running_dir(root_path)
    watchdog_dir = root_path / 'state' / 'control' / 'autowork' / 'watchdog'
    ledger_path = root_path / 'state' / 'impl_progress.jsonl'
    newest_ts = _watchdog_ledger_newest(ledger_path)
    try:
        entries = sorted(running_dir.iterdir())
    except OSError:
        entries = []
    for entry in entries:
        try:
            if entry.suffix != '.pid':
                continue
        except Exception:
            continue
        task_id = _pidfile_task_id(entry.stem)
        if not task_id:
            continue
        try:
            raw = entry.read_text(encoding='utf-8').strip()
        except OSError:
            continue
        if not pid_is_live(raw):
            if task_id not in result['dead']:
                result['dead'].append(task_id)
            continue
        ts = newest_ts.get(task_id)
        if ts is None:
            continue
        if now - ts <= idle_grace:
            continue
        if task_id not in result['detected']:
            result['detected'].append(task_id)
        attempts = _watchdog_bump_attempt(watchdog_dir, task_id)
        _watchdog_terminate(raw)
        try:
            entry.unlink()
            if task_id not in result['healed']:
                result['healed'].append(task_id)
        except OSError:
            pass
        if attempts >= max_retries:
            if _watchdog_write_escalation(watchdog_dir, task_id, now, attempts, max_retries, ts):
                if task_id not in result['escalated']:
                    result['escalated'].append(task_id)
    return result

def reap_spent_briefs(root, *, stamp=None) -> list:
    """Archive fully-integrated ``plan_hooks_<slug>`` + ``brief_hooks_<slug>`` pairs.

    Thin reconciler-side wrapper that DELEGATES both the integration decision and
    the archive move to :mod:`tools.brief_reaper`: spent-ness is decided from
    ``tools.brief_reaper._integrated_task_ids`` (an ORDERED ledger replay that
    un-counts a tid once a LATER ``reject_rollback`` / ``task_blocked`` row
    reverts a prior acceptance) and each spent pair is relocated -- collision-safe,
    a plain MOVE and NEVER a delete -- by :func:`tools.brief_reaper.reap_for_task`,
    which itself fail-safe-skips epic plans and brief-less plans (no pair to
    archive). This fixes the prior over-reaping of epic / brief-less plans.

    A ``plan_hooks_<slug>.json`` at the workspace ``root`` is a reap candidate
    only when EVERY task it lists is integrated (the all-integrated gate). The
    archive lands under ``<root>/_autowork_archive/<stamp>/reconciled/`` where
    ``stamp`` defaults to today's ISO date. The returned slug list is built SOLELY
    by extending it with ``reap_for_task``'s return value, so a plan the reaper
    declines (epic / brief-less) never appears even when it cleared the gate.

    The pass is fail-safe per plan (a missing / corrupt ledger or plan is skipped,
    never raises) and idempotent (a re-run finds the plans already gone and reaps
    nothing). It acquires NO state lock itself -- the lone archive lock is taken
    inside ``reap_for_task``. ``reap_spent_briefs(root)`` stays positional /
    backward-compatible. Returns the sorted list of reaped slugs.
    """
    import json
    import datetime
    try:
        from tools.brief_reaper import _integrated_task_ids, reap_for_task
    except Exception:
        return []
    root_path = Path(root)
    try:
        integrated = _integrated_task_ids(root_path)
    except Exception:
        integrated = set()
    if stamp is None:
        stamp = datetime.date.today().isoformat()
    try:
        plans = sorted(root_path.glob('plan_hooks_*.json'))
    except OSError:
        plans = []
    prefix = 'plan_hooks_'
    reaped = []
    for plan_path in plans:
        try:
            if not plan_path.is_file():
                continue
            stem = plan_path.stem
            if not stem.startswith(prefix):
                continue
            slug = stem[len(prefix):]
            if not slug:
                continue
            try:
                data = json.loads(plan_path.read_text(encoding='utf-8'))
            except (OSError, ValueError):
                continue
            if not isinstance(data, dict):
                continue
            tasks = data.get('tasks')
            if not isinstance(tasks, list):
                continue
            plan_ids = []
            for item in tasks:
                if isinstance(item, dict):
                    tid = item.get('task_id')
                    if isinstance(tid, str) and tid:
                        plan_ids.append(tid)
            if not plan_ids:
                continue
            if any((tid not in integrated for tid in plan_ids)):
                continue
            reaped.extend(reap_for_task(root_path, plan_ids[0], stamp=stamp))
        except Exception:
            continue
    reaped.sort()
    return reaped
def _running_dir(root) -> Path:
    """Canonical autowork running-pidfile directory for ``root``.

    Both reaper sites (:func:`_classify_pidfile_is_live` and
    :func:`reap_orphaned_workdirs`) resolve their pidfile dir through this ONE
    location -- ``<root>/state/control/autowork/running`` -- so liveness checks
    and the orphaned-workdir sweep never diverge onto a stale path. Pure path
    computation; never created here.
    """
    return Path(root) / 'state' / 'control' / 'autowork' / 'running'
