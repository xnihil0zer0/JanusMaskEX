import importlib.util
import shutil
import os
from pathlib import Path
import pytest

@pytest.fixture
def hook_runner_mod(tmp_path):
    src_path = Path('tools/drive_backup/hook_runner.py').resolve()
    if not src_path.exists():
        for parent in Path(os.getcwd()).parents:
            candidate = parent / 'tools/drive_backup/hook_runner.py'
            if candidate.exists():
                src_path = candidate
                break
    if not src_path.exists():
        src_path = Path('/home/xnihil0zer0/JanusMaskJR/tools/drive_backup/hook_runner.py')
    dest_path = tmp_path / 'hook_runner.py'
    shutil.copy(src_path, dest_path)
    spec = importlib.util.spec_from_file_location('hook_runner_temp', str(dest_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module

class MockLedger:

    def __init__(self, entries):
        self._entries = entries

    def last_backed_up_sha(self, repo):
        return None

    def record(self, sha, archive_name, uploaded, repo):
        self._entries.append({'sha': sha, 'archive_name': archive_name, 'uploaded': uploaded, 'repo': repo})

    def entries(self):
        return self._entries

def test_prune_old_uploaded_snapshot(hook_runner_mod, tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    a1_tar = artifacts_dir / 'repo_a_sha1_20260625.tar.zst'
    a1_diff = artifacts_dir / 'repo_a_sha1_20260625.diff'
    a2_tar = artifacts_dir / 'repo_a_sha2_20260625.tar.zst'
    a2_diff = artifacts_dir / 'repo_a_sha2_20260625.diff'
    a3_tar = artifacts_dir / 'repo_a_sha3_20260625.tar.zst'
    a3_diff = artifacts_dir / 'repo_a_sha3_20260625.diff'
    b1_tar = artifacts_dir / 'repo_b_sha4_20260625.tar.zst'
    b1_diff = artifacts_dir / 'repo_b_sha4_20260625.diff'
    b2_tar = artifacts_dir / 'repo_b_sha5_20260625.tar.zst'
    b2_diff = artifacts_dir / 'repo_b_sha5_20260625.diff'
    for f in [a1_tar, a1_diff, a2_tar, a2_diff, a3_tar, a3_diff, b1_tar, b1_diff, b2_tar, b2_diff]:
        f.touch()
    entries = [{'sha': 'sha1', 'archive_name': 'repo_a_sha1_20260625', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha2', 'archive_name': 'repo_a_sha2_20260625', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha3', 'archive_name': 'repo_a_sha3_20260625', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha4', 'archive_name': 'repo_b_sha4_20260625', 'uploaded': True, 'repo': 'repo_b'}, {'sha': 'sha5', 'archive_name': 'repo_b_sha5_20260625', 'uploaded': True, 'repo': 'repo_b'}]
    prune_func = getattr(hook_runner_mod, '_prune_local_snapshots')
    deleted = prune_func(str(artifacts_dir), entries, keep=1)
    assert set(deleted) == {'repo_a_sha1_20260625', 'repo_a_sha2_20260625', 'repo_b_sha4_20260625'}
    assert a3_tar.exists()
    assert a3_diff.exists()
    assert b2_tar.exists()
    assert b2_diff.exists()
    assert not a1_tar.exists()
    assert not a1_diff.exists()
    assert not a2_tar.exists()
    assert not a2_diff.exists()
    assert not b1_tar.exists()
    assert not b1_diff.exists()

def test_newest_snapshot_kept(hook_runner_mod, tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    a1_tar = artifacts_dir / 'repo_a_sha1.tar.zst'
    a1_diff = artifacts_dir / 'repo_a_sha1.diff'
    a2_tar = artifacts_dir / 'repo_a_sha2.tar.zst'
    a2_diff = artifacts_dir / 'repo_a_sha2.diff'
    a1_tar.touch()
    a1_diff.touch()
    a2_tar.touch()
    a2_diff.touch()
    entries = [{'sha': 'sha1', 'archive_name': 'repo_a_sha1', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha2', 'archive_name': 'repo_a_sha2', 'uploaded': False, 'repo': 'repo_a'}]
    prune_func = getattr(hook_runner_mod, '_prune_local_snapshots')
    deleted = prune_func(str(artifacts_dir), entries, keep=1)
    assert set(deleted) == {'repo_a_sha1'}
    assert not a1_tar.exists()
    assert not a1_diff.exists()
    assert a2_tar.exists()
    assert a2_diff.exists()

def test_unuploaded_snapshot_never_deleted(hook_runner_mod, tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    a1_tar = artifacts_dir / 'repo_a_sha1.tar.zst'
    a1_diff = artifacts_dir / 'repo_a_sha1.diff'
    a2_tar = artifacts_dir / 'repo_a_sha2.tar.zst'
    a2_diff = artifacts_dir / 'repo_a_sha2.diff'
    a1_tar.touch()
    a1_diff.touch()
    a2_tar.touch()
    a2_diff.touch()
    entries = [{'sha': 'sha1', 'archive_name': 'repo_a_sha1', 'uploaded': False, 'repo': 'repo_a'}, {'sha': 'sha2', 'archive_name': 'repo_a_sha2', 'uploaded': True, 'repo': 'repo_a'}]
    prune_func = getattr(hook_runner_mod, '_prune_local_snapshots')
    deleted = prune_func(str(artifacts_dir), entries, keep=1)
    assert not deleted
    assert a1_tar.exists()
    assert a1_diff.exists()
    assert a2_tar.exists()
    assert a2_diff.exists()

def test_fail_closed_never_delete_unuploaded(hook_runner_mod, tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    a1_tar = artifacts_dir / 'repo_a_sha1.tar.zst'
    a1_diff = artifacts_dir / 'repo_a_sha1.diff'
    a2_tar = artifacts_dir / 'repo_a_sha2.tar.zst'
    a2_diff = artifacts_dir / 'repo_a_sha2.diff'
    a1_tar.touch()
    a1_diff.touch()
    a2_tar.touch()
    a2_diff.touch()
    entries = [{'sha': 'sha1', 'archive_name': 'repo_a_sha1', 'uploaded': False, 'repo': 'repo_a'}, {'sha': 'sha2', 'archive_name': 'repo_a_sha2', 'uploaded': True, 'repo': 'repo_a'}]
    prune_func = getattr(hook_runner_mod, '_prune_local_snapshots')
    prune_func(str(artifacts_dir), entries, keep=1)
    assert a1_tar.exists()
    assert a1_diff.exists()
    assert a2_tar.exists()
    assert a2_diff.exists()

def test_untracked_stem_never_deleted(hook_runner_mod, tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    a1_tar = artifacts_dir / 'repo_a_sha1.tar.zst'
    a1_diff = artifacts_dir / 'repo_a_sha1.diff'
    a2_tar = artifacts_dir / 'repo_a_sha2.tar.zst'
    a2_diff = artifacts_dir / 'repo_a_sha2.diff'
    untracked_tar = artifacts_dir / 'untracked.tar.zst'
    untracked_diff = artifacts_dir / 'untracked.diff'
    for f in [a1_tar, a1_diff, a2_tar, a2_diff, untracked_tar, untracked_diff]:
        f.touch()
    entries = [{'sha': 'sha1', 'archive_name': 'repo_a_sha1', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha2', 'archive_name': 'repo_a_sha2', 'uploaded': True, 'repo': 'repo_a'}]
    prune_func = getattr(hook_runner_mod, '_prune_local_snapshots')
    deleted = prune_func(str(artifacts_dir), entries, keep=1)
    assert set(deleted) == {'repo_a_sha1'}
    assert not a1_tar.exists()
    assert not a1_diff.exists()
    assert a2_tar.exists()
    assert a2_diff.exists()
    assert untracked_tar.exists()
    assert untracked_diff.exists()

def test_ledger_file_untouched(hook_runner_mod, tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    a1_tar = artifacts_dir / 'repo_a_sha1.tar.zst'
    a1_diff = artifacts_dir / 'repo_a_sha1.diff'
    a1_tar.touch()
    a1_diff.touch()
    outside_file = tmp_path / 'repo_a_sha1.tar.zst'
    outside_file.touch()
    ledger_file = tmp_path / 'ledger.ndjson'
    ledger_content = '{"sha": "sha1", "archive_name": "repo_a_sha1", "uploaded": true, "repo": "repo_a"}\n'
    ledger_file.write_text(ledger_content, encoding='utf-8')
    entries = [{'sha': 'sha1', 'archive_name': 'repo_a_sha1', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha2', 'archive_name': 'repo_a_sha2', 'uploaded': True, 'repo': 'repo_a'}]
    prune_func = getattr(hook_runner_mod, '_prune_local_snapshots')
    prune_func(str(artifacts_dir), entries, keep=1)
    assert not a1_tar.exists()
    assert not a1_diff.exists()
    assert outside_file.exists()
    assert ledger_file.exists()
    assert ledger_file.read_text(encoding='utf-8') == ledger_content

def test_prune_custom_keep(hook_runner_mod, tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    a1_tar = artifacts_dir / 'repo_a_sha1.tar.zst'
    a1_diff = artifacts_dir / 'repo_a_sha1.diff'
    a2_tar = artifacts_dir / 'repo_a_sha2.tar.zst'
    a2_diff = artifacts_dir / 'repo_a_sha2.diff'
    a3_tar = artifacts_dir / 'repo_a_sha3.tar.zst'
    a3_diff = artifacts_dir / 'repo_a_sha3.diff'
    a4_tar = artifacts_dir / 'repo_a_sha4.tar.zst'
    a4_diff = artifacts_dir / 'repo_a_sha4.diff'
    for f in [a1_tar, a1_diff, a2_tar, a2_diff, a3_tar, a3_diff, a4_tar, a4_diff]:
        f.touch()
    entries = [{'sha': 'sha1', 'archive_name': 'repo_a_sha1', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha2', 'archive_name': 'repo_a_sha2', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha3', 'archive_name': 'repo_a_sha3', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha4', 'archive_name': 'repo_a_sha4', 'uploaded': True, 'repo': 'repo_a'}]
    prune_func = getattr(hook_runner_mod, '_prune_local_snapshots')
    deleted = prune_func(str(artifacts_dir), entries, keep=2)
    assert set(deleted) == {'repo_a_sha1', 'repo_a_sha2'}
    assert not a1_tar.exists()
    assert not a2_tar.exists()
    assert a3_tar.exists()
    assert a4_tar.exists()

def test_prune_missing_files_graceful(hook_runner_mod, tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    a2_tar = artifacts_dir / 'repo_a_sha2.tar.zst'
    a2_diff = artifacts_dir / 'repo_a_sha2.diff'
    a2_tar.touch()
    a2_diff.touch()
    entries = [{'sha': 'sha1', 'archive_name': 'repo_a_sha1', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha2', 'archive_name': 'repo_a_sha2', 'uploaded': True, 'repo': 'repo_a'}]
    prune_func = getattr(hook_runner_mod, '_prune_local_snapshots')
    deleted = prune_func(str(artifacts_dir), entries, keep=1)
    assert set(deleted) == {'repo_a_sha1'}
    assert a2_tar.exists()

def test_prune_oserror_ignored(hook_runner_mod, tmp_path, monkeypatch):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    a1_tar = artifacts_dir / 'repo_a_sha1.tar.zst'
    a1_diff = artifacts_dir / 'repo_a_sha1.diff'
    a2_tar = artifacts_dir / 'repo_a_sha2.tar.zst'
    a2_diff = artifacts_dir / 'repo_a_sha2.diff'
    a1_tar.touch()
    a1_diff.touch()
    a2_tar.touch()
    a2_diff.touch()
    entries = [{'sha': 'sha1', 'archive_name': 'repo_a_sha1', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha2', 'archive_name': 'repo_a_sha2', 'uploaded': True, 'repo': 'repo_a'}]
    orig_remove = os.remove

    def mock_remove(path):
        if 'repo_a_sha1.tar.zst' in str(path):
            raise OSError('Injected permission error')
        orig_remove(path)
    monkeypatch.setattr(os, 'remove', mock_remove)
    prune_func = getattr(hook_runner_mod, '_prune_local_snapshots')
    deleted = prune_func(str(artifacts_dir), entries, keep=1)
    assert set(deleted) == {'repo_a_sha1'}
    assert a1_tar.exists()
    assert not a1_diff.exists()
    assert a2_tar.exists()

def test_prune_empty_ledger(hook_runner_mod, tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    prune_func = getattr(hook_runner_mod, '_prune_local_snapshots')
    deleted = prune_func(str(artifacts_dir), [], keep=1)
    assert deleted == []

def test_prune_invalid_uploaded_values(hook_runner_mod, tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    a1_tar = artifacts_dir / 'repo_a_sha1.tar.zst'
    a1_diff = artifacts_dir / 'repo_a_sha1.diff'
    a2_tar = artifacts_dir / 'repo_a_sha2.tar.zst'
    a2_diff = artifacts_dir / 'repo_a_sha2.diff'
    a3_tar = artifacts_dir / 'repo_a_sha3.tar.zst'
    a3_diff = artifacts_dir / 'repo_a_sha3.diff'
    a4_tar = artifacts_dir / 'repo_a_sha4.tar.zst'
    a4_diff = artifacts_dir / 'repo_a_sha4.diff'
    for f in [a1_tar, a1_diff, a2_tar, a2_diff, a3_tar, a3_diff, a4_tar, a4_diff]:
        f.touch()
    entries = [{'sha': 'sha1', 'archive_name': 'repo_a_sha1', 'uploaded': 'True', 'repo': 'repo_a'}, {'sha': 'sha2', 'archive_name': 'repo_a_sha2', 'uploaded': 1, 'repo': 'repo_a'}, {'sha': 'sha3', 'archive_name': 'repo_a_sha3', 'uploaded': None, 'repo': 'repo_a'}, {'sha': 'sha4', 'archive_name': 'repo_a_sha4', 'uploaded': True, 'repo': 'repo_a'}]
    prune_func = getattr(hook_runner_mod, '_prune_local_snapshots')
    deleted = prune_func(str(artifacts_dir), entries, keep=1)
    assert not deleted
    for f in [a1_tar, a2_tar, a3_tar, a4_tar]:
        assert f.exists()

def test_prune_multiple_repos(hook_runner_mod, tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    a1_tar = artifacts_dir / 'repo_a_sha1.tar.zst'
    a2_tar = artifacts_dir / 'repo_a_sha2.tar.zst'
    b1_tar = artifacts_dir / 'repo_b_sha3.tar.zst'
    b2_tar = artifacts_dir / 'repo_b_sha4.tar.zst'
    for f in [a1_tar, a2_tar, b1_tar, b2_tar]:
        f.touch()
    entries = [{'sha': 'sha1', 'archive_name': 'repo_a_sha1', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha3', 'archive_name': 'repo_b_sha3', 'uploaded': True, 'repo': 'repo_b'}, {'sha': 'sha2', 'archive_name': 'repo_a_sha2', 'uploaded': True, 'repo': 'repo_a'}, {'sha': 'sha4', 'archive_name': 'repo_b_sha4', 'uploaded': True, 'repo': 'repo_b'}]
    prune_func = getattr(hook_runner_mod, '_prune_local_snapshots')
    deleted = prune_func(str(artifacts_dir), entries, keep=1)
    assert set(deleted) == {'repo_a_sha1', 'repo_b_sha3'}
    assert not a1_tar.exists()
    assert a2_tar.exists()
    assert not b1_tar.exists()
    assert b2_tar.exists()

def test_run_backup_prunes_on_success(hook_runner_mod, tmp_path):
    artifacts_dir = tmp_path / 'artifacts'
    artifacts_dir.mkdir()
    a1_tar = artifacts_dir / 'repo_a_sha1.tar.zst'
    a1_diff = artifacts_dir / 'repo_a_sha1.diff'
    a2_tar = artifacts_dir / 'repo_a_sha2.tar.zst'
    a2_diff = artifacts_dir / 'repo_a_sha2.diff'
    a1_tar.touch()
    a1_diff.touch()
    a2_tar.touch()
    a2_diff.touch()
    repo_root = tmp_path / 'repo_a'
    repo_root.mkdir()
    initial_entries = [{'sha': 'sha1', 'archive_name': 'repo_a_sha1', 'uploaded': True, 'repo': 'repo_a'}]
    ledger = MockLedger(initial_entries)

    class MockArchiveResult:
        manifest = {'stem': 'repo_a_sha2'}

    def archiver(r_root, sha, base_sha=None):
        return MockArchiveResult()

    class MockUploadResult:
        uploaded = True

    def uploader(archive_result):
        return MockUploadResult()
    logs = []

    def log(msg, **fields):
        logs.append((msg, fields))
    from collections import namedtuple
    PushRef = namedtuple('PushRef', ['local_ref', 'local_sha', 'remote_ref', 'remote_sha'])
    refs = [PushRef('refs/heads/main', 'sha2', 'refs/heads/main', 'sha1')]
    run_backup = getattr(hook_runner_mod, 'run_backup')
    res = run_backup(repo_root, refs, archiver=archiver, uploader=uploader, ledger=ledger, log=log, artifacts_dir=str(artifacts_dir))
    assert res == 0
    assert len(ledger.entries()) == 2
    assert ledger.entries()[1]['uploaded'] is True
    assert not a1_tar.exists()
    assert not a1_diff.exists()
    assert a2_tar.exists()

def test_run_backup_handles_missing_artifacts_dir_gracefully(hook_runner_mod, tmp_path):
    repo_root = tmp_path / 'repo_a'
    repo_root.mkdir()
    ledger = MockLedger([])

    class MockArchiveResult:
        manifest = {'stem': 'repo_a_sha2'}

    def archiver(r_root, sha, base_sha=None):
        return MockArchiveResult()

    class MockUploadResult:
        uploaded = True

    def uploader(archive_result):
        return MockUploadResult()
    logs = []

    def log(msg, **fields):
        logs.append((msg, fields))
    from collections import namedtuple
    PushRef = namedtuple('PushRef', ['local_ref', 'local_sha', 'remote_ref', 'remote_sha'])
    refs = [PushRef('refs/heads/main', 'sha2', 'refs/heads/main', 'sha1')]
    run_backup = getattr(hook_runner_mod, 'run_backup')
    res = run_backup(repo_root, refs, archiver=archiver, uploader=uploader, ledger=ledger, log=log, artifacts_dir=None)
    assert res == 0