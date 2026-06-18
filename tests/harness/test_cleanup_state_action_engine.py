"""RED oracle for ``harness.state_reconciler.cleanup_state(root, *, mode=...)``.

This is a hermetic verification oracle (a pytest TEST FILE), NOT an
implementation. Each test synthesizes its OWN ``tmp_path`` workspace -- a root
holding ``state/running/<tid>.pid`` pidfiles plus product plan files spanning
the classes already defined by the present ``classify_product`` -- and drives
``cleanup_state`` over it. No live ``state/``, no network, no shared global
state, no fixtures shared across tests.

Contract pinned (post-fix):

* ``mode="report"`` is a PURE READ: it returns a ``WorkspaceStatus`` enumerating
  each product's per-product status / blocker / ready and leaves the tree
  byte-for-byte unchanged (``_autowork_archive/`` not created or empty);
  idempotent across repeated calls.
* ``mode="apply"`` drives the classify_product + discriminator action table:
  every NON-LIVE archivable product (PLANNED / UNPLANNED / CORRUPT) is relocated
  into ``_autowork_archive/`` via a plain move, while LIVE / FOREIGN /
  STAGED_UNMERGED / BLOCKED products PERSIST in place carrying an explicit
  blocker string and ``ready == False``.
* moves are race-tolerant (a vanished source == recorded success, ENOENT
  swallowed, NO TOCTOU ``exists()`` pre-check), dst-collision-safe
  (suffix-disambiguation -- never overwrite, never strand), per-product
  error-class contained (a non-ENOENT move error becomes THAT product's blocker
  while the sweep continues), and report-first convergent on the NON-LIVE subset.

RED on HEAD because ``cleanup_state`` does not exist yet (the import below
fails at collection); GREEN after the impl leaf lands.
"""
import errno
import hashlib
import json
import os
import random
import time
from pathlib import Path
import pytest
from harness.state_reconciler import cleanup_state, classify_product, ProductStatus
_OLD_SEC = 10000.0

def _running_dir(root: Path) -> Path:
    d = Path(root) / 'state' / 'running'
    d.mkdir(parents=True, exist_ok=True)
    return d

def _products_dir(root: Path) -> Path:
    d = Path(root) / 'products'
    d.mkdir(parents=True, exist_ok=True)
    return d

def _archive_dir(root: Path) -> Path:
    return Path(root) / '_autowork_archive'

def _age(path: Path) -> None:
    old = time.time() - _OLD_SEC
    os.utime(path, (old, old), follow_symlinks=False)

def _dead_pid() -> int:
    """A pid that is currently NOT live (so its pidfile reads as stale)."""
    for _ in range(20000):
        pid = random.randint(100000, 200000)
        try:
            os.kill(pid, 0)
        except OSError as exc:
            if getattr(exc, 'errno', None) == errno.ESRCH:
                return pid
    return 199999

def _pidfile(root: Path, tid: str, pid: int) -> Path:
    p = _running_dir(root) / f'{tid}.pid'
    p.write_text(str(pid), encoding='utf-8')
    return p

def _planned(root: Path, tid: str, *, pidfile: bool=True) -> Path:
    """A healthy, NON-LIVE PLANNED product (valid JM provenance + tasks list)."""
    p = _products_dir(root) / f'{tid}.json'
    p.write_text(json.dumps({'source_brief_sha256': '0' * 64, 'tasks': []}), encoding='utf-8')
    _age(p)
    if pidfile:
        _pidfile(root, tid, _dead_pid())
    return p

def _corrupt(root: Path, tid: str, *, pidfile: bool=True) -> Path:
    """A NON-LIVE CORRUPT product (settled-unparseable)."""
    p = _products_dir(root) / f'{tid}.json'
    p.write_text('{ this is : not valid json', encoding='utf-8')
    _age(p)
    if pidfile:
        _pidfile(root, tid, _dead_pid())
    return p

def _live(root: Path, tid: str) -> Path:
    """A LIVE product: a live running/<tid>.pid (this very process)."""
    p = _products_dir(root) / f'{tid}.json'
    p.write_text(json.dumps({'source_brief_sha256': '1' * 64, 'tasks': []}), encoding='utf-8')
    _age(p)
    _pidfile(root, tid, os.getpid())
    return p

def _foreign(root: Path, tid: str) -> Path:
    """A FOREIGN product: a symlink (never followed / read-through / moved)."""
    p = _products_dir(root) / f'{tid}.json'
    try:
        p.symlink_to('does_not_exist_target')
    except (OSError, NotImplementedError):
        pytest.skip('symlinks unsupported on this platform')
    old = time.time() - _OLD_SEC
    try:
        os.utime(p, (old, old), follow_symlinks=False)
    except (NotImplementedError, OSError):
        pytest.skip('aging a symlink (lutimes) unsupported on this platform')
    _pidfile(root, tid, _dead_pid())
    return p
_MISSING = object()

def _get(obj, *names, default=_MISSING):
    for n in names:
        if isinstance(obj, dict):
            if n in obj:
                return obj[n]
        elif hasattr(obj, n):
            return getattr(obj, n)
    if default is _MISSING:
        raise AssertionError(f'none of {names!r} present on {obj!r}')
    return default

def _entries(ws):
    """The per-product collection carried by a WorkspaceStatus."""
    assert ws is not None, 'cleanup_state must return a WorkspaceStatus'
    for n in ('products', 'product_statuses', 'statuses', 'items', 'entries', 'results'):
        v = ws.get(n) if isinstance(ws, dict) else getattr(ws, n, None)
        if v is None:
            continue
        if isinstance(v, dict):
            return list(v.values())
        if isinstance(v, (list, tuple, set)):
            return list(v)
    if isinstance(ws, (list, tuple)):
        return list(ws)
    raise AssertionError(f'WorkspaceStatus exposes no per-product collection: {ws!r}')

def _ident(p) -> str:
    return str(_get(p, 'task_id', 'tid', 'id', 'name', 'path', 'product_path', 'source', 'stem', default=''))

def _status_str(p) -> str:
    s = _get(p, 'status', 'state', 'classification', 'klass', default='')
    return str(getattr(s, 'value', s))

def _ready_opt(p):
    return _get(p, 'ready', 'is_ready', default=None)

def _blocker_opt(p):
    return _get(p, 'blocker', 'reason', 'blocked_reason', default=None)

def _find(ws, tid):
    for p in _entries(ws):
        if tid in _ident(p):
            return p
    return None

def _snapshot(root: Path) -> dict:
    snap = {}
    root = Path(root)
    for dp, dns, fns in os.walk(root):
        for dn in dns:
            rel = str((Path(dp) / dn).relative_to(root)) + '/'
            snap[rel] = ('dir',)
        for fn in fns:
            fp = Path(dp) / fn
            rel = str(fp.relative_to(root))
            try:
                if fp.is_symlink():
                    snap[rel] = ('link', os.readlink(fp))
                else:
                    snap[rel] = ('file', hashlib.sha256(fp.read_bytes()).hexdigest())
            except OSError as exc:
                snap[rel] = ('err', getattr(exc, 'errno', None))
    return snap

def _archived_files(root: Path):
    ad = _archive_dir(root)
    if not ad.exists():
        return []
    return [p for p in ad.rglob('*') if p.is_file() or p.is_symlink()]

def _archived_for(root: Path, tid: str):
    return [p for p in _archived_files(root) if tid in p.name]

def _archive_absent_or_empty(root: Path) -> bool:
    ad = _archive_dir(root)
    return not ad.exists() or not any(ad.iterdir())

def test_report_mode_is_pure_read_leaves_tree_unchanged(tmp_path):
    root = tmp_path / 'ws'
    root.mkdir()
    pl = _planned(root, 'planned_alpha')
    co = _corrupt(root, 'corrupt_alpha')
    fo = _foreign(root, 'foreign_alpha')
    lv = _live(root, 'live_alpha')
    assert classify_product(str(root), str(pl)) == ProductStatus.PLANNED
    assert classify_product(str(root), str(co)) == ProductStatus.CORRUPT
    assert classify_product(str(root), str(fo)) == ProductStatus.FOREIGN
    assert classify_product(str(root), str(lv)) == ProductStatus.LIVE
    before = _snapshot(root)
    ws = cleanup_state(str(root), mode='report')
    after = _snapshot(root)
    assert after == before, 'report mode must not mutate the tree'
    assert _archive_absent_or_empty(root), 'report must not write _autowork_archive/'
    assert len(_entries(ws)) >= 1, 'report must enumerate the products'

def test_apply_archives_nonlive_subset_into_autowork_archive_via_move(tmp_path):
    root = tmp_path / 'ws'
    root.mkdir()
    pl = _planned(root, 'planned_beta')
    co = _corrupt(root, 'corrupt_beta')
    lv = _live(root, 'live_beta')
    cleanup_state(str(root), mode='apply')
    assert not pl.exists(), 'PLANNED source must be moved out of products/'
    assert not co.exists(), 'CORRUPT source must be moved out of products/'
    assert _archived_for(root, 'planned_beta'), 'PLANNED must land in _autowork_archive/'
    assert _archived_for(root, 'corrupt_beta'), 'CORRUPT must land in _autowork_archive/'
    assert lv.exists(), 'LIVE product must persist in place'
    assert not _archived_for(root, 'live_beta'), 'LIVE must never be archived'

def test_live_foreign_blocked_persist_with_blocker_and_ready_false(tmp_path):
    root = tmp_path / 'ws'
    root.mkdir()
    lv = _live(root, 'live_gamma')
    fo = _foreign(root, 'foreign_gamma')
    ws = cleanup_state(str(root), mode='apply')
    assert lv.exists(), 'LIVE must persist in apply mode'
    assert os.path.islink(fo), 'FOREIGN symlink must persist and not be followed'
    assert not _archived_for(root, 'live_gamma')
    assert not _archived_for(root, 'foreign_gamma')
    for tid in ('live_gamma', 'foreign_gamma'):
        ent = _find(ws, tid)
        assert ent is not None, f'{tid} must appear in WorkspaceStatus'
        ready = _ready_opt(ent)
        assert ready is not None and (not ready), f'{tid} must carry ready==False'
        blk = _blocker_opt(ent)
        assert isinstance(blk, str) and blk.strip(), f'{tid} must carry an explicit blocker'

def test_apply_move_enoent_recorded_as_success_no_toctou_precheck(tmp_path):
    root = tmp_path / 'ws'
    root.mkdir()
    healthy = _planned(root, 'planned_delta')
    vanish = _planned(root, 'vanish_delta')
    vanish.unlink()
    assert not vanish.exists()
    ws = cleanup_state(str(root), mode='apply')
    ent = _find(ws, 'vanish_delta')
    if ent is not None:
        assert not _blocker_opt(ent), 'ENOENT move must be recorded as success, not blocked'
    assert not _archived_for(root, 'vanish_delta'), 'nothing existed to land in the archive'
    assert not healthy.exists()
    assert _archived_for(root, 'planned_delta'), 'the healthy product must still be archived'

def test_dst_collision_suffix_disambiguates_never_overwrite_never_strand(tmp_path):
    root = tmp_path / 'ws'
    root.mkdir()
    tid = 'planned_epsilon'
    src = _planned(root, tid)
    new_bytes = src.read_bytes()
    ad = _archive_dir(root)
    ad.mkdir(parents=True, exist_ok=True)
    seeded = ad / f'{tid}.json'
    seed_bytes = b'PREEXISTING-DO-NOT-OVERWRITE'
    seeded.write_bytes(seed_bytes)
    cleanup_state(str(root), mode='apply')
    assert seeded.read_bytes() == seed_bytes, 'pre-existing archived artifact overwritten'
    assert not src.exists(), 'source must not be stranded after a collision move'
    files = _archived_files(root)
    assert len(files) >= 2, 'both the seeded and the moved artifact must survive'
    assert any((f.read_bytes() == new_bytes for f in files)), 'moved artifact content lost'

def test_per_product_error_surfaced_as_blocker_sweep_continues(tmp_path):
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        pytest.skip('permission-based error injection is a no-op for root')
    root = tmp_path / 'ws'
    root.mkdir()
    products = _products_dir(root)
    boom = _planned(root, 'planned_zeta')
    other = _planned(root, 'vanish_zeta')
    other.unlink()
    os.chmod(products, 320)
    try:
        try:
            ws = cleanup_state(str(root), mode='apply')
            raised = None
        except Exception as exc:
            ws = None
            raised = exc
    finally:
        os.chmod(products, 448)
    assert raised is None, f'a per-product error must be contained, not raised: {raised!r}'
    ent = _find(ws, 'planned_zeta')
    assert ent is not None, 'the erroring product must still appear in WorkspaceStatus'
    blk = _blocker_opt(ent)
    assert isinstance(blk, str) and blk.strip(), "the move error must become that product's blocker"
    ready = _ready_opt(ent)
    assert ready is not None and (not ready), 'an errored product must have ready==False'
    assert boom.exists(), 'the erroring product must not have been moved away'
    assert not _archived_for(root, 'planned_zeta')
    other_ent = _find(ws, 'vanish_zeta')
    if other_ent is not None:
        assert not _blocker_opt(other_ent), 'the lock-immune product should not be blocked'

def test_report_is_idempotent_across_repeated_calls(tmp_path):
    root = tmp_path / 'ws'
    root.mkdir()
    _planned(root, 'planned_eta')
    _corrupt(root, 'corrupt_eta')
    _live(root, 'live_eta')
    _foreign(root, 'foreign_eta')
    before = _snapshot(root)
    ws1 = cleanup_state(str(root), mode='report')
    mid = _snapshot(root)
    ws2 = cleanup_state(str(root), mode='report')
    after = _snapshot(root)
    assert mid == before, 'first report mutated the tree'
    assert after == before, 'second report mutated the tree'
    assert _archive_absent_or_empty(root)
    idents1 = sorted((_ident(p) for p in _entries(ws1)))
    idents2 = sorted((_ident(p) for p in _entries(ws2)))
    assert idents1 == idents2, 'report must enumerate the same products each call'

def test_apply_then_report_convergent_on_nonlive_subset(tmp_path):
    root = tmp_path / 'ws'
    root.mkdir()
    pl = _planned(root, 'planned_theta')
    co = _corrupt(root, 'corrupt_theta')
    lv = _live(root, 'live_theta')
    cleanup_state(str(root), mode='apply')
    assert not pl.exists() and (not co.exists())
    assert lv.exists()
    ws = cleanup_state(str(root), mode='report')
    archivable = {ProductStatus.PLANNED, ProductStatus.CORRUPT}
    for tid in ('planned_theta', 'corrupt_theta'):
        ent = _find(ws, tid)
        if ent is not None:
            assert _status_str(ent) not in archivable, f'{tid} still reported as pending-archivable after apply'
    assert lv.exists()
    cleanup_state(str(root), mode='apply')
    assert lv.exists(), 'a repeated apply must still never touch LIVE'

def test_report_never_creates_or_writes_autowork_archive(tmp_path):
    root = tmp_path / 'ws'
    root.mkdir()
    _planned(root, 'planned_iota')
    _corrupt(root, 'corrupt_iota')
    assert not _archive_dir(root).exists()
    before = _snapshot(root)
    cleanup_state(str(root), mode='report')
    after = _snapshot(root)
    assert _archive_absent_or_empty(root), 'report must not create/populate _autowork_archive/'
    assert after == before, 'report must be a pure read'

def test_apply_never_overwrites_preexisting_archived_artifact(tmp_path):
    root = tmp_path / 'ws'
    root.mkdir()
    tid = 'planned_kappa'
    src = _planned(root, tid)
    moved_bytes = src.read_bytes()
    ad = _archive_dir(root)
    ad.mkdir(parents=True, exist_ok=True)
    seeded = ad / f'{tid}.json'
    seed_bytes = b'ALREADY-ARCHIVED-PROTECTED'
    seeded.write_bytes(seed_bytes)
    cleanup_state(str(root), mode='apply')
    assert seeded.read_bytes() == seed_bytes, 'a pre-existing archived artifact was overwritten'
    assert not src.exists(), 'the moved source must not be stranded'
    files = _archived_files(root)
    assert len(files) >= 2, 'both artifacts must coexist in the archive'
    assert any((f.read_bytes() == moved_bytes for f in files)), 'the newly moved artifact is missing'