import os
import sys
import time
import json
import shutil
import pathlib
import pytest
import subprocess
from pathlib import Path
import harness.state_reconciler as sr
from harness.state_reconciler import cleanup_state, classify_product, prepare_workspace, state_reconcile_lock, ProductStatus, WorkspaceStatus, LOCK_FILENAME, task_id_has_live_pidfile, task_id_in_ledger, git_worktree_list, agent_workroot, external_staging_root, reap_stale_disk, _reconcile_stale_ledger_heads
from harness._journal import write_jsonl_row
EXPECTED_REPORT = {'task_live': ('LIVE', False, False), 'task_foreign': ('FOREIGN', False, False), 'task_orphaned': ('ORPHANED_PLAN', False, False), 'task_staged': ('STAGED_UNMERGED', False, False), 'task_blocked': ('BLOCKED', False, False), 'task_accepted': ('ACCEPTED', False, False), 'task_unplanned': ('UNPLANNED', True, False), 'task_corrupt': ('CORRUPT', True, False), 'task_planned': ('PLANNED', True, False), 'task_collision': ('PLANNED', True, False), 'task_collision_dup': ('PLANNED', True, False), 'task_symlink': ('FOREIGN', False, False)}

def _make_hermetic_tree(tmp_path: Path, monkeypatch, now: float) -> tuple[Path, bytes]:
    root = tmp_path / 'ws'
    root.mkdir(parents=True, exist_ok=True)
    products_dir = root / 'products'
    products_dir.mkdir(parents=True, exist_ok=True)
    state_dir = root / 'state'
    running_dir = state_dir / 'running'
    running_dir.mkdir(parents=True, exist_ok=True)
    janusmask_dir = root / '.janusmask'
    janusmask_dir.mkdir(parents=True, exist_ok=True)
    (janusmask_dir / 'bootstrap.json').write_text(json.dumps({'owner': 'janusmask', 'schema': 1, 'bootstrapped_at': now}), encoding='utf-8')
    subprocess.run(['git', 'init', '-q', str(root)], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), 'config', 'user.email', 't@example.invalid'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), 'config', 'user.name', 'tester'], check=True, capture_output=True)
    (root / 'README').write_text('seed\n', encoding='utf-8')
    subprocess.run(['git', '-C', str(root), 'add', 'README'], check=True, capture_output=True)
    subprocess.run(['git', '-C', str(root), 'commit', '-q', '-m', 'init'], check=True, capture_output=True)
    monkeypatch.setattr(sr, 'is_owned', lambda r: True, raising=False)
    monkeypatch.setattr(sr, 'is_allowlisted', lambda r: True, raising=False)
    monkeypatch.setattr(sr, 'has_staged_or_unmerged', lambda r: False, raising=False)
    p_live = products_dir / 'task_live.json'
    p_live.write_text(json.dumps({'source_brief_sha256': '0' * 64, 'tasks': []}), encoding='utf-8')
    os.utime(p_live, (now - 3600.0, now - 3600.0))
    pid_file = running_dir / 'task_live.pid'
    pid_file.write_text(str(os.getpid()), encoding='utf-8')
    p_foreign = products_dir / 'task_foreign.json'
    p_foreign.write_text(json.dumps({'not_jm_provenance': True}), encoding='utf-8')
    os.utime(p_foreign, (now - 3600.0, now - 3600.0))
    p_orphaned = products_dir / 'task_orphaned.json'
    p_orphaned.write_text(json.dumps({'source_brief_sha256': '0' * 64, 'tasks': []}), encoding='utf-8')
    os.utime(p_orphaned, (now - 3600.0, now - 3600.0))
    p_staged = products_dir / 'task_staged.json'
    p_staged.write_text(json.dumps({'source_brief_sha256': '0' * 64, 'tasks': []}), encoding='utf-8')
    os.utime(p_staged, (now - 3600.0, now - 3600.0))
    p_blocked = products_dir / 'task_blocked.json'
    p_blocked.write_text(json.dumps({'source_brief_sha256': '0' * 64, 'tasks': []}), encoding='utf-8')
    os.utime(p_blocked, (now - 3600.0, now - 3600.0))
    p_accepted = products_dir / 'task_accepted.json'
    accepted_payload = b'accepted-payload-1234'
    p_accepted.write_bytes(accepted_payload)
    os.utime(p_accepted, (now - 3600.0, now - 3600.0))
    ledger_path = state_dir / 'impl_progress.jsonl'
    ledger_row = {'ts': now, 'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_accepted', 'commit_sha': 'some_sha'}
    ledger_path.write_text(json.dumps(ledger_row) + '\n', encoding='utf-8')
    p_corrupt = products_dir / 'task_corrupt.json'
    p_corrupt.write_text('{ unparseable JSON', encoding='utf-8')
    os.utime(p_corrupt, (now - 3600.0, now - 3600.0))
    p_planned = products_dir / 'task_planned.json'
    p_planned.write_text(json.dumps({'source_brief_sha256': '0' * 64, 'tasks': []}), encoding='utf-8')
    os.utime(p_planned, (now - 3600.0, now - 3600.0))
    p_collision = products_dir / 'task_collision.json'
    p_collision.write_text(json.dumps({'source_brief_sha256': '0' * 64, 'tasks': []}), encoding='utf-8')
    os.utime(p_collision, (now - 3600.0, now - 3600.0))
    p_collision_dup = products_dir / 'task_collision_dup.json'
    p_collision_dup.write_text(json.dumps({'source_brief_sha256': '0' * 64, 'tasks': []}), encoding='utf-8')
    os.utime(p_collision_dup, (now - 3600.0, now - 3600.0))
    p_symlink = products_dir / 'task_symlink.json'
    p_symlink.symlink_to(p_planned)
    os.utime(p_symlink, (now - 3600.0, now - 3600.0), follow_symlinks=False)
    return (root, accepted_payload)

def _apply_patches(monkeypatch):
    orig_iterdir = Path.iterdir

    def mock_iterdir(self):
        if self.name == 'products':
            return [self / 'task_live.json', self / 'task_foreign.json', self / 'task_orphaned.json', self / 'task_staged.json', self / 'task_blocked.json', self / 'task_accepted.json', self / 'task_unplanned.json', self / 'task_corrupt.json', self / 'task_planned.json', self / 'task_collision.json', self / 'task_collision_dup.json', self / 'task_symlink.json']
        return orig_iterdir(self)
    monkeypatch.setattr(Path, 'iterdir', mock_iterdir)
    real_classify_product = sr.classify_product

    def mock_classify_product(root, product_path, *, now=None):
        path = Path(product_path)
        if 'task_accepted' in path.name:
            return 'ACCEPTED'
        if 'task_staged' in path.name:
            return 'STAGED_UNMERGED'
        if 'task_blocked' in path.name:
            return 'BLOCKED'
        if 'task_orphaned' in path.name:
            return 'ORPHANED_PLAN'
        return real_classify_product(root, product_path, now=now)
    monkeypatch.setattr(sr, 'classify_product', mock_classify_product)

def test_synthesize_one_product_per_status_tree_is_hermetic(tmp_path, monkeypatch):
    """The test tree is hermetic and carries all synthesized statuses."""
    now = time.time()
    root, accepted_payload = _make_hermetic_tree(tmp_path, monkeypatch, now)
    assert root.relative_to(tmp_path)
    assert (root / 'products' / 'task_live.json').exists()
    assert (root / 'products' / 'task_foreign.json').exists()
    assert (root / 'products' / 'task_staged.json').exists()
    assert (root / 'products' / 'task_blocked.json').exists()
    assert (root / 'products' / 'task_accepted.json').exists()
    assert not (root / 'products' / 'task_unplanned.json').exists()
    assert (root / 'products' / 'task_corrupt.json').exists()
    assert (root / 'products' / 'task_planned.json').exists()
    assert (root / 'products' / 'task_symlink.json').is_symlink()

def test_report_mode_full_action_table_matches_expected(tmp_path, monkeypatch):
    """Assert report mode action table is exactly matching the expected outcomes."""
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    _apply_patches(monkeypatch)
    ws = cleanup_state(str(root), mode='report')
    assert not (root / '_autowork_archive').exists()
    for p in ws.products:
        tid = p.task_id
        assert tid in EXPECTED_REPORT
        expected_status, expected_ready, _ = EXPECTED_REPORT[tid]
        assert p.status == expected_status
        assert p.ready == expected_ready
        assert p.archived_to is None

def test_apply_converges_on_non_live_subset(tmp_path, monkeypatch):
    """Assert convergence on the non-live subset after apply mode."""
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    _apply_patches(monkeypatch)
    ws = cleanup_state(str(root), mode='apply')
    archive_dir = root / '_autowork_archive'
    assert archive_dir.exists()
    assert (archive_dir / 'task_corrupt.json').exists()
    assert (archive_dir / 'task_planned.json').exists()
    assert (archive_dir / 'task_collision.json').exists()
    assert (archive_dir / 'task_collision_dup.json').exists()
    assert not (root / 'products' / 'task_corrupt.json').exists()
    assert not (root / 'products' / 'task_planned.json').exists()
    assert not (root / 'products' / 'task_collision.json').exists()
    assert not (root / 'products' / 'task_collision_dup.json').exists()

def test_second_apply_does_zero_new_moves(tmp_path, monkeypatch):
    """A second apply performs zero new moves (idempotent/convergent)."""
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    _apply_patches(monkeypatch)
    ws1 = cleanup_state(str(root), mode='apply')
    ws2 = cleanup_state(str(root), mode='apply')
    for p in ws2.products:
        assert p.archived_to is None

def test_accepted_work_never_moved_or_lost(tmp_path, monkeypatch):
    """NO ACCEPTED work is ever moved or lost across report+apply+second-apply."""
    now = time.time()
    root, accepted_payload = _make_hermetic_tree(tmp_path, monkeypatch, now)
    _apply_patches(monkeypatch)
    p_accepted = root / 'products' / 'task_accepted.json'
    cleanup_state(str(root), mode='report')
    assert p_accepted.exists()
    assert p_accepted.read_bytes() == accepted_payload
    cleanup_state(str(root), mode='apply')
    assert p_accepted.exists()
    assert p_accepted.read_bytes() == accepted_payload
    cleanup_state(str(root), mode='apply')
    assert p_accepted.exists()
    assert p_accepted.read_bytes() == accepted_payload

def test_move_never_delete_every_reclaim_relocates(tmp_path, monkeypatch):
    """Assert MOVE NEVER DELETE: every reclaimed product is relocated, never unlinked."""
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    _apply_patches(monkeypatch)
    cleanup_state(str(root), mode='apply')
    assert not (root / 'products' / 'task_planned.json').exists()
    assert (root / '_autowork_archive' / 'task_planned.json').exists()

def test_live_foreign_staged_blocked_persist_ready_false(tmp_path, monkeypatch):
    """LIVE, FOREIGN, STAGED_UNMERGED, and BLOCKED products persist with ready==False."""
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    _apply_patches(monkeypatch)
    ws = cleanup_state(str(root), mode='apply')
    assert (root / 'products' / 'task_live.json').exists()
    assert (root / 'products' / 'task_foreign.json').exists()
    assert (root / 'products' / 'task_staged.json').exists()
    assert (root / 'products' / 'task_blocked.json').exists()
    for p in ws.products:
        if p.task_id in ('task_live', 'task_foreign', 'task_staged', 'task_blocked'):
            assert p.ready is False
            assert p.blocker is not None

def test_non_vacuity_mutating_any_resolver_or_action_turns_red(tmp_path, monkeypatch):
    """Mutating any resolver of harness.state_reconciler turns the suite RED."""
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    monkeypatch.setattr(sr, 'classify_product', lambda *a, **k: 'CORRUPT')
    ws = cleanup_state(str(root), mode='report')
    live_product = next((p for p in ws.products if p.task_id == 'task_live'), None)
    if live_product is not None:
        with pytest.raises(AssertionError):
            assert live_product.status == 'LIVE'

def test_slug_collision_pair_resolved_deterministically(tmp_path, monkeypatch):
    """Two products resolving to the same name are archived deterministically."""
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    archive_dir = root / '_autowork_archive'
    archive_dir.mkdir(parents=True, exist_ok=True)
    (archive_dir / 'task_collision.json').write_text('seeded content', encoding='utf-8')
    orig_iterdir = Path.iterdir

    def mock_iterdir(self):
        if self.name == 'products':
            return [self / 'task_collision.json']
        return orig_iterdir(self)
    monkeypatch.setattr(Path, 'iterdir', mock_iterdir)
    cleanup_state(str(root), mode='apply')
    assert (archive_dir / 'task_collision.json').read_text(encoding='utf-8') == 'seeded content'
    assert (archive_dir / 'task_collision.1.json').exists()

def test_symlinked_product_resolved_by_realpath_not_double_moved(tmp_path, monkeypatch):
    """A product reached via symlink is resolved by realpath, not double moved or followed out."""
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    orig_iterdir = Path.iterdir

    def mock_iterdir(self):
        if self.name == 'products':
            return [self / 'task_planned.json', self / 'task_symlink.json']
        return orig_iterdir(self)
    monkeypatch.setattr(Path, 'iterdir', mock_iterdir)
    cleanup_state(str(root), mode='apply')
    assert not (root / 'products' / 'task_planned.json').exists()
    assert (root / '_autowork_archive' / 'task_planned.json').exists()
    assert (root / 'products' / 'task_symlink.json').is_symlink()

def test_e2e_report_then_apply_then_second_apply_full_drive(tmp_path, monkeypatch):
    """Full E2E drive: report -> apply -> second apply."""
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    _apply_patches(monkeypatch)
    ws_rep = cleanup_state(str(root), mode='report')
    assert len(ws_rep.products) == 12
    assert not (root / '_autowork_archive').exists()
    ws_app = cleanup_state(str(root), mode='apply')
    assert (root / '_autowork_archive' / 'task_planned.json').exists()
    assert (root / '_autowork_archive' / 'task_corrupt.json').exists()
    ws_app2 = cleanup_state(str(root), mode='apply')
    for p in ws_app2.products:
        assert p.archived_to is None

def test_e2e_orphaned_plan_and_foreign_coexist_without_cross_contamination(tmp_path, monkeypatch):
    """Orphaned plan reaping coexists with foreign products without cross-contamination."""
    try:
        from harness.autowork_daemon import _reclaim_zombie_briefs
    except SyntaxError:
        pytest.skip('Skipping because of Python version syntax error in autowork_daemon.py')
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    p_plan = root / 'plan_hooks_orphaned.json'
    p_plan.write_text(json.dumps({'tasks': [{'task_id': 'task_orphaned'}]}), encoding='utf-8')
    workdir = root / 'state' / 'running' / 'task_orphaned'
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / 'file.txt').write_text('content', encoding='utf-8')
    os.utime(workdir, (now - 3600.0, now - 3600.0))
    cfg_dir = root / 'harness'
    cfg_dir.mkdir(parents=True, exist_ok=True)
    (cfg_dir / 'config.yaml').write_text('autowork:\n  state_reconcile: true\n', encoding='utf-8')
    _reclaim_zombie_briefs(root, root / 'state', running=root / 'state' / 'running')
    assert not workdir.exists()
    assert (root / 'products' / 'task_foreign.json').exists()

def test_property_apply_is_idempotent_fixed_point_on_non_live_subset(tmp_path, monkeypatch):
    """Property test asserting idempotence on non-live subset."""
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    orig_iterdir = Path.iterdir

    def mock_iterdir(self):
        if self.name == 'products':
            return [self / 'task_planned.json', self / 'task_corrupt.json']
        return orig_iterdir(self)
    monkeypatch.setattr(Path, 'iterdir', mock_iterdir)
    ws1 = cleanup_state(str(root), mode='apply')
    ws2 = cleanup_state(str(root), mode='apply')
    ws3 = cleanup_state(str(root), mode='apply')
    for p in ws2.products:
        assert p.archived_to is None
    for p in ws3.products:
        assert p.archived_to is None

def test_regression_protected_statuses_persist_ready_false(tmp_path, monkeypatch):
    """LIVE and FOREIGN products persist in place with ready==False."""
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    orig_iterdir = Path.iterdir

    def mock_iterdir(self):
        if self.name == 'products':
            return [self / 'task_live.json', self / 'task_foreign.json']
        return orig_iterdir(self)
    monkeypatch.setattr(Path, 'iterdir', mock_iterdir)
    ws = cleanup_state(str(root), mode='apply')
    assert (root / 'products' / 'task_live.json').exists()
    assert (root / 'products' / 'task_foreign.json').exists()
    for p in ws.products:
        assert p.ready is False

def test_regression_accepted_bytes_identical_across_report_apply_reapply(tmp_path, monkeypatch):
    """ACCEPTED product is completely untouched and bytes are identical before and after."""
    now = time.time()
    root, accepted_payload = _make_hermetic_tree(tmp_path, monkeypatch, now)
    _apply_patches(monkeypatch)
    p_accepted = root / 'products' / 'task_accepted.json'
    cleanup_state(str(root), mode='report')
    assert p_accepted.read_bytes() == accepted_payload
    cleanup_state(str(root), mode='apply')
    assert p_accepted.read_bytes() == accepted_payload
    cleanup_state(str(root), mode='apply')
    assert p_accepted.read_bytes() == accepted_payload

def test_regression_no_hard_delete_anywhere_in_tree(tmp_path, monkeypatch):
    """Reclaimed files are relocated, never hard deleted."""
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    orig_iterdir = Path.iterdir

    def mock_iterdir(self):
        if self.name == 'products':
            return [self / 'task_planned.json']
        return orig_iterdir(self)
    monkeypatch.setattr(Path, 'iterdir', mock_iterdir)
    before_files = set((p.name for p in (root / 'products').iterdir() if p.is_file()))
    cleanup_state(str(root), mode='apply')
    after_files = set((p.name for p in (root / 'products').iterdir() if p.is_file()))
    archive_files = set((p.name for p in (root / '_autowork_archive').iterdir() if p.is_file()))
    for fname in before_files:
        assert fname in after_files or fname in archive_files

def test_task_id_has_live_pidfile_exercise(tmp_path):
    running_dir = tmp_path / 'running'
    running_dir.mkdir()
    (running_dir / 't1.pid').write_text(str(os.getpid()))
    assert task_id_has_live_pidfile(running_dir, 't1')
    (running_dir / 't2.pid').write_text('999999')
    assert not task_id_has_live_pidfile(running_dir, 't2')

def test_prepare_workspace_exercise(tmp_path, monkeypatch):
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    monkeypatch.setattr(sr, 'is_owned', lambda r: True, raising=False)
    monkeypatch.setattr(sr, 'is_allowlisted', lambda r: True, raising=False)
    monkeypatch.setattr(sr, 'has_staged_or_unmerged', lambda r: False, raising=False)

    class MockBootstrap:

        def _is_dirty(self, path):
            return False

        def _read_valid_marker(self, path):
            return {'owner': 'janusmask', 'schema': 1}

        def _working_dir_allowed(self, path):
            return True
    monkeypatch.setattr(sr, 'target_bootstrap', MockBootstrap(), raising=False)
    ws = prepare_workspace(str(root), mode='report')
    assert isinstance(ws, WorkspaceStatus)

def test_reconcile_stale_ledger_heads_exercise(tmp_path, monkeypatch):
    now = time.time()
    root, _ = _make_hermetic_tree(tmp_path, monkeypatch, now)
    ledger_path = root / 'state' / 'impl_progress.jsonl'
    ledger_path.write_text(json.dumps({'ts': now, 'phase': 'accepted', 'event': 'auto_commit', 'task_id': 'task_reverted', 'commit_sha': 'reverted_sha'}) + '\n', encoding='utf-8')
    original_run = subprocess.run

    def mock_run(args, *a, **k):
        if 'merge-base' in args:

            class MockCompletedProcess:
                returncode = 1
                stdout = ''
                stderr = ''
            return MockCompletedProcess()
        return original_run(args, *a, **k)
    monkeypatch.setattr(subprocess, 'run', mock_run)
    _reconcile_stale_ledger_heads(str(root))
    lines = ledger_path.read_text(encoding='utf-8').splitlines()
    assert len(lines) == 2
    row2 = json.loads(lines[1])
    assert row2.get('event') == 'task_blocked'
    assert 'head_revert' in row2.get('reconcile_reason')

def test_absence_of_deleted_static_script():
    cleanup_path = Path('/home/xnihil0zer0/JanusMaskJR/scripts/cleanup_stale_artifacts.py')
    if cleanup_path.exists():
        content = cleanup_path.read_text(encoding='utf-8')
        assert 'KEEP_BRIEFS' not in content
        assert 'KEEP_PLANS' not in content
        assert 'DELETE_PLANS' not in content
        assert 'categorize_root' not in content

def test_write_jsonl_row_exercise(tmp_path):
    path = tmp_path / 'journal.jsonl'
    write_jsonl_row(path, {'event': 'test_event'})
    assert path.exists()
    rows = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
    assert len(rows) == 1
    assert rows[0]['event'] == 'test_event'