"""RED oracle for the shared ``classify_product()`` status resolver.

Pins the behavioural contract of
``harness.state_reconciler.classify_product(root, product_path, *, now=None)``
-> ``ProductStatus`` (the single classifier consumed by both report and apply):

* **LIVE is decided FIRST and short-circuits BEFORE any ``json.loads``/``read_text``** --
  a mid-write/unparseable product under a live ``running/<tid>.pid`` pidfile, or
  whose mtime is within the write-settle grace (default 60 s), is ``LIVE`` and is
  never read, never ``CORRUPT``.
* **FOREIGN** for a symlinked product and for a valid-JSON file with no JM
  provenance (no top-level ``source_brief_sha256`` string and no ``tasks`` list).
* **UNPLANNED** if and ONLY if ``os.path.lexists(plan_path)`` is False (a broken
  symlink whose ``lexists`` is True is NOT ``UNPLANNED``).
* **CORRUPT** for a settled (no live pidfile, past grace) product that is
  unparseable, wrong-schema, or a directory occupying the plan path -- reading
  the RAW plan file, NOT the ``has_plan`` boolean that ``compute_brief_status``
  collapses (MISSING/STALE/CORRUPT/DIRECTORY all to ``has_plan=False``/
  ``'unplanned'``).

This oracle is RED on HEAD (``classify_product`` does not exist yet) and GREEN
after ``stale-status-resolver-core-impl`` lands.

NON-GOALS: ``integration`` -- no live-daemon run and no live ``state/`` directory;
every test is a hermetic unit drive over synthesized product paths in its OWN
``tmp_path`` with no network and no shared globals, and edits no source file. The
write-settle grace boundary is pinned deterministically through the ``now=``
keyword rather than by sleeping.
"""
import json
import os
from pathlib import Path
import pytest
from harness.state_reconciler import classify_product
NOW = 1000000.0
GRACE_SEC = 60.0
WITHIN_GRACE_MTIME = NOW - 5.0
SETTLED_MTIME = NOW - 3600.0

def _label(status) -> str:
    """Collapse a ProductStatus return to a comparable UPPER token.

    The impl may expose the status as an ``Enum`` member (compare ``.name``/
    ``.value``) or as a bare string; normalise every shape to e.g. ``'LIVE'``.
    """
    for attr in ('name', 'value'):
        val = getattr(status, attr, None)
        if isinstance(val, str) and val:
            return val.upper()
    return str(status).rsplit('.', 1)[-1].upper()

def _make_root(tmp_path: Path) -> Path:
    """Build a hermetic, JM-owned workspace root under the test's own tmp_path."""
    root = tmp_path / 'ws'
    (root / 'state' / 'control' / 'autowork' / 'running').mkdir(parents=True)
    (root / 'state' / 'output').mkdir(parents=True)
    (root / '.janusmask').mkdir(parents=True)
    (root / '.janusmask' / 'bootstrap.json').write_text(json.dumps({'root': str(root)}), encoding='utf-8')
    return root

def _set_mtime(path: Path, mtime: float) -> None:
    """Stamp ``path``'s mtime (the symlink's own mtime, never the target's)."""
    os.utime(path, (mtime, mtime), follow_symlinks=False)

def _live_pidfile(root: Path, tid: str) -> Path:
    """Stamp ``running/<tid>.pid`` with OUR pid (provably live via os.kill(pid,0))."""
    pid_path = root / 'state' / 'control' / 'autowork' / 'running' / f'{tid}.pid'
    pid_path.write_text(str(os.getpid()), encoding='utf-8')
    return pid_path

def test_live_first_unparseable_under_live_pidfile_is_live(tmp_path):
    """Unparseable bytes under a live pidfile -> LIVE (decided before any read)."""
    root = _make_root(tmp_path)
    tid = 't1'
    product = root / 'state' / 'output' / f'{tid}.json'
    product.write_bytes(b'{ this is NOT valid json <<<')
    _set_mtime(product, SETTLED_MTIME)
    _live_pidfile(root, tid)
    assert _label(classify_product(root, product, now=NOW)) == 'LIVE'

def test_live_within_write_settle_grace_is_live(tmp_path):
    """A freshly-written unparseable plan inside the 60 s grace -> LIVE, not CORRUPT."""
    root = _make_root(tmp_path)
    product = root / 'state' / 'output' / 'fresh.json'
    product.write_bytes(b'\x00\x01 not json at all')
    _set_mtime(product, WITHIN_GRACE_MTIME)
    assert _label(classify_product(root, product, now=NOW)) == 'LIVE'

def test_settled_unparseable_past_grace_is_corrupt(tmp_path):
    """Same unparseable plan, aged past the grace with no live tid -> CORRUPT."""
    root = _make_root(tmp_path)
    product = root / 'state' / 'output' / 'settled.json'
    product.write_bytes(b'{ broken json )))')
    _set_mtime(product, SETTLED_MTIME)
    assert _label(classify_product(root, product, now=NOW)) == 'CORRUPT'

def test_directory_named_plan_is_corrupt(tmp_path):
    """A directory occupying the plan path (settled) -> CORRUPT."""
    root = _make_root(tmp_path)
    product = root / 'state' / 'output' / 'dir_plan.json'
    product.mkdir()
    _set_mtime(product, SETTLED_MTIME)
    assert _label(classify_product(root, product, now=NOW)) == 'CORRUPT'

def test_wrong_schema_settled_is_corrupt(tmp_path):
    """Valid JSON carrying JM provenance but no ``tasks`` list (settled) -> CORRUPT."""
    root = _make_root(tmp_path)
    product = root / 'state' / 'output' / 'wrongschema.json'
    product.write_text(json.dumps({'source_brief_sha256': 'b' * 64, 'not_tasks': 123}), encoding='utf-8')
    _set_mtime(product, SETTLED_MTIME)
    assert _label(classify_product(root, product, now=NOW)) == 'CORRUPT'

def test_symlinked_product_is_foreign(tmp_path):
    """A symlinked product is FOREIGN -- never followed/read through."""
    root = _make_root(tmp_path)
    target = root / 'state' / 'output' / 'real_plan.json'
    target.write_text(json.dumps({'source_brief_sha256': 'a' * 64, 'tasks': [{'task_id': 't1'}]}), encoding='utf-8')
    link = root / 'state' / 'output' / 'link_plan.json'
    link.symlink_to(target)
    _set_mtime(link, SETTLED_MTIME)
    assert _label(classify_product(root, link, now=NOW)) == 'FOREIGN'

def test_no_jm_provenance_is_foreign(tmp_path):
    """Valid JSON with neither ``source_brief_sha256`` nor ``tasks`` -> FOREIGN."""
    root = _make_root(tmp_path)
    product = root / 'state' / 'output' / 'foreign.json'
    product.write_text(json.dumps({'hello': 'world', 'note': 'hand-authored WIP, not ours'}), encoding='utf-8')
    _set_mtime(product, SETTLED_MTIME)
    assert _label(classify_product(root, product, now=NOW)) == 'FOREIGN'

def test_unplanned_only_when_lexists_false(tmp_path):
    """UNPLANNED iff os.path.lexists is False; a broken symlink is NOT UNPLANNED."""
    root = _make_root(tmp_path)
    missing = root / 'state' / 'output' / 'nope.json'
    assert not os.path.lexists(missing)
    assert _label(classify_product(root, missing, now=NOW)) == 'UNPLANNED'
    broken = root / 'state' / 'output' / 'broken.json'
    broken.symlink_to(root / 'state' / 'output' / 'no_such_target.json')
    _set_mtime(broken, SETTLED_MTIME)
    assert os.path.lexists(broken) and (not os.path.exists(broken))
    broken_status = _label(classify_product(root, broken, now=NOW))
    assert broken_status != 'UNPLANNED'
    assert broken_status in ('FOREIGN', 'CORRUPT')

def test_classification_is_idempotent_report_first(tmp_path):
    """Two classifications agree and the call mutates nothing on disk."""
    root = _make_root(tmp_path)
    product = root / 'state' / 'output' / 'settled.json'
    product.write_bytes(b'not json {{{')
    _set_mtime(product, SETTLED_MTIME)
    before = sorted((p.relative_to(root).as_posix() for p in root.rglob('*')))
    first = classify_product(root, product, now=NOW)
    second = classify_product(root, product, now=NOW)
    after = sorted((p.relative_to(root).as_posix() for p in root.rglob('*')))
    assert _label(first) == _label(second)
    assert _label(first) == 'CORRUPT'
    assert before == after

def test_reads_raw_plan_not_has_plan_settled_corrupt_is_corrupt_not_unplanned(tmp_path):
    """A present-but-wrong-schema plan that compute_brief_status would collapse to
    has_plan=False/'unplanned' must classify CORRUPT, never UNPLANNED -- proving
    the resolver reads the RAW plan file rather than trusting has_plan."""
    root = _make_root(tmp_path)
    product = root / 'state' / 'output' / 'collapsed.json'
    product.write_text(json.dumps({'source_brief_sha256': 'c' * 64, 'tasks': 'not-a-list'}), encoding='utf-8')
    _set_mtime(product, SETTLED_MTIME)
    assert os.path.lexists(product)
    status = _label(classify_product(root, product, now=NOW))
    assert status != 'UNPLANNED'
    assert status == 'CORRUPT'

def test_live_first_short_circuits_before_any_read(tmp_path):
    """Bytes that would raise/CORRUPT if read first, under a live pidfile, settled
    past grace -> LIVE: the live check runs and returns BEFORE any read_text/json.loads."""
    root = _make_root(tmp_path)
    tid = 't1'
    product = root / 'state' / 'output' / f'{tid}.json'
    product.write_bytes(b'\xff\xfe corrupt mid-write bytes {[')
    _set_mtime(product, SETTLED_MTIME)
    _live_pidfile(root, tid)
    assert _label(classify_product(root, product, now=NOW)) == 'LIVE'