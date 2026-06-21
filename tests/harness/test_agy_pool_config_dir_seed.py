"""Authored pytest oracle for ``harness.agy_pool.ensure_seeded``.

These tests pin the directory-creation and repair contract for a worker's
private ``$HOME``:

* the ``.gemini/config`` and ``.gemini/config/projects`` directories are created
  as real directories when absent;
* a non-directory squatting the config path (a 0-byte read-only regular file, or
  a dangling symlink) is repaired -- removed and replaced with a directory tree;
* the operation is idempotent and never raises on repeated calls;
* a pre-existing real config directory and its contents are NEVER wiped.

All filesystem effects flow through the injected ``copy``/``exists``/``makedirs``
seams, exactly as the production caller wires them, so the tests exercise the
module's REAL observable behaviour on disk under a redirected temporary HOME.
"""
import os
import shutil
import tempfile
import pytest
from harness import agy_pool

def _run_ensure_seeded(repo_root, slot, home):
    """Invoke ``ensure_seeded`` with the standard production seams."""
    return agy_pool.ensure_seeded(repo_root, slot, home=home, copy=shutil.copy2, exists=os.path.exists, makedirs=lambda d: os.makedirs(d, exist_ok=True))

def test_ensure_seeded_config_dir_absent():
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_root = os.path.join(tmp_dir, 'repo')
        os.makedirs(repo_root, exist_ok=True)
        slot = 0
        wh = str(agy_pool.worker_home(repo_root, slot))
        config_dir = os.path.join(wh, '.gemini', 'config')
        projects_dir = os.path.join(config_dir, 'projects')
        assert not os.path.exists(config_dir)
        _run_ensure_seeded(repo_root, slot, tmp_dir)
        assert os.path.isdir(config_dir)
        assert os.path.isdir(projects_dir)

def test_ensure_seeded_config_dir_repair():
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_root = os.path.join(tmp_dir, 'repo')
        slot = 0
        wh = str(agy_pool.worker_home(repo_root, slot))
        gemini_dir = os.path.join(wh, '.gemini')
        os.makedirs(gemini_dir, exist_ok=True)
        config_path = os.path.join(gemini_dir, 'config')
        with open(config_path, 'wb') as f:
            f.write(b'')
        os.chmod(config_path, 292)
        assert os.path.exists(config_path)
        assert os.path.isfile(config_path)
        assert not os.path.isdir(config_path)
        try:
            _run_ensure_seeded(repo_root, slot, tmp_dir)
            assert os.path.isdir(config_path)
            assert not os.path.isfile(config_path)
            assert os.path.isdir(os.path.join(config_path, 'projects'))
        finally:
            if os.path.isfile(config_path):
                os.chmod(config_path, 438)

def test_ensure_seeded_config_dir_idempotent():
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_root = os.path.join(tmp_dir, 'repo')
        slot = 0
        wh = str(agy_pool.worker_home(repo_root, slot))
        config_dir = os.path.join(wh, '.gemini', 'config')
        projects_dir = os.path.join(config_dir, 'projects')
        _run_ensure_seeded(repo_root, slot, tmp_dir)
        assert os.path.isdir(config_dir)
        assert os.path.isdir(projects_dir)
        _run_ensure_seeded(repo_root, slot, tmp_dir)
        assert os.path.isdir(config_dir)
        assert os.path.isdir(projects_dir)

def test_ensure_seeded_config_dir_never_wipe():
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_root = os.path.join(tmp_dir, 'repo')
        slot = 0
        wh = str(agy_pool.worker_home(repo_root, slot))
        config_dir = os.path.join(wh, '.gemini', 'config')
        projects_dir = os.path.join(config_dir, 'projects')
        os.makedirs(projects_dir, exist_ok=True)
        sentinel_path = os.path.join(projects_dir, 'keep.txt')
        with open(sentinel_path, 'wb') as f:
            f.write(b'sentinel_data')
        assert os.path.exists(sentinel_path)
        _run_ensure_seeded(repo_root, slot, tmp_dir)
        assert os.path.isdir(config_dir)
        assert os.path.isdir(projects_dir)
        assert os.path.exists(sentinel_path)
        with open(sentinel_path, 'rb') as f:
            assert f.read() == b'sentinel_data'

@pytest.mark.skipif(not hasattr(os, 'symlink'), reason='symlinks unsupported')
def test_ensure_seeded_config_dir_dangling_symlink_repaired():
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_root = os.path.join(tmp_dir, 'repo')
        slot = 0
        wh = str(agy_pool.worker_home(repo_root, slot))
        gemini_dir = os.path.join(wh, '.gemini')
        os.makedirs(gemini_dir, exist_ok=True)
        config_path = os.path.join(gemini_dir, 'config')
        os.symlink(os.path.join(tmp_dir, 'nonexistent_target'), config_path)
        assert os.path.islink(config_path)
        assert not os.path.isdir(config_path)
        _run_ensure_seeded(repo_root, slot, tmp_dir)
        assert os.path.isdir(config_path)
        assert os.path.isdir(os.path.join(config_path, 'projects'))

def test_ensure_seeded_config_dir_idempotent_after_repair():
    with tempfile.TemporaryDirectory() as tmp_dir:
        repo_root = os.path.join(tmp_dir, 'repo')
        slot = 0
        wh = str(agy_pool.worker_home(repo_root, slot))
        gemini_dir = os.path.join(wh, '.gemini')
        os.makedirs(gemini_dir, exist_ok=True)
        config_path = os.path.join(gemini_dir, 'config')
        with open(config_path, 'wb') as f:
            f.write(b'')
        os.chmod(config_path, 292)
        try:
            _run_ensure_seeded(repo_root, slot, tmp_dir)
            assert os.path.isdir(config_path)
            assert os.path.isdir(os.path.join(config_path, 'projects'))
            _run_ensure_seeded(repo_root, slot, tmp_dir)
            assert os.path.isdir(config_path)
            assert os.path.isdir(os.path.join(config_path, 'projects'))
        finally:
            if os.path.isfile(config_path):
                os.chmod(config_path, 438)