"""Oracle: the project-local agy worker pool (parallelism-of-N isolation).

``harness.agy_pool`` lets up to N JanusMask *worker* agy processes run
concurrently without corrupting each other's Antigravity registry. The isolation
knob (proven empirically: 4 concurrent agy in seeded private HOMEs, zero
conflict) is a private ``$HOME`` per slot, seeded with ONLY the small
auth/config set -- NEVER the multi-GB ``~/.gemini`` cache. The contract:

  * ``pool_root(repo_root)`` -> ``<repo>/.agents/agy-pool`` (project-local),
  * ``worker_home(repo_root, slot)`` -> a private home per slot,
  * ``agy_seed_plan(home)`` -> the (src, dst-relative) auth/config files to copy
    (``~/.gemini`` oauth/account/settings/trust/state/projects + the gcloud
    ADC), each placed home-relative in the slot,
  * ``ensure_seeded(...)`` -> idempotently copy only existing, not-yet-present
    seed files (via injected copy/exists/makedirs seams),
  * ``allocate_slot(busy, size)`` -> the lowest free slot, or None when full,
  * ``worker_env(repo_root, slot, base_env)`` -> base env + private HOME +
    ``GOOGLE_GENAI_USE_GCA``.

Hermetic: injected fs seams; no real copy, no agy spawn, no network.
"""
from __future__ import annotations
import os
from pathlib import Path
from harness import agy_pool

def test_pool_root_is_project_local():
    root = Path(agy_pool.pool_root('/repo'))
    assert str(root).replace('\\', '/') == '/repo/.agents/agy-pool'

def test_worker_homes_are_distinct_per_slot():
    h0 = str(agy_pool.worker_home('/repo', 0))
    h1 = str(agy_pool.worker_home('/repo', 1))
    assert h0 != h1
    assert str(agy_pool.pool_root('/repo')) in h0

def test_seed_plan_covers_auth_and_adc_not_cache():
    plan = agy_pool.agy_seed_plan('/home/u')
    srcs = [src for src, _dst in plan]
    dsts = [dst for _src, dst in plan]
    assert any((s.endswith('.gemini/oauth_creds.json') for s in srcs))
    assert any((s.endswith('.gemini/google_accounts.json') for s in srcs))
    assert any(('application_default_credentials.json' in s for s in srcs))
    assert all((not os.path.isabs(d) for d in dsts))
    assert not any(('/cache/' in s or s.rstrip('/').endswith('.gemini') for s in srcs))

class _FakeFS:

    def __init__(self, present):
        self.present = set((str(p) for p in present))
        self.copies = []
        self.made_dirs = []

    def exists(self, p):
        return str(p) in self.present

    def copy(self, src, dst):
        self.copies.append((str(src), str(dst)))
        self.present.add(str(dst))

    def makedirs(self, p):
        self.made_dirs.append(str(p))
        self.present.add(str(p))

def test_ensure_seeded_copies_existing_sources_only():
    home = '/home/u'
    plan = agy_pool.agy_seed_plan(home)
    present = {plan[0][0]}
    fs = _FakeFS(present)
    copied = agy_pool.ensure_seeded('/repo', 2, home=home, copy=fs.copy, exists=fs.exists, makedirs=fs.makedirs)
    assert len(fs.copies) == 1
    assert len(copied) == 1
    wh = str(agy_pool.worker_home('/repo', 2))
    assert all((dst.startswith(wh) for _src, dst in fs.copies))

def test_ensure_seeded_is_idempotent():
    home = '/home/u'
    plan = agy_pool.agy_seed_plan(home)
    wh = str(agy_pool.worker_home('/repo', 0))
    all_src = {src for src, _ in plan}
    all_dst = {os.path.join(wh, dst) for _src, dst in plan}
    fs = _FakeFS(all_src | all_dst)
    agy_pool.ensure_seeded('/repo', 0, home=home, copy=fs.copy, exists=fs.exists, makedirs=fs.makedirs)
    assert fs.copies == []

def test_allocate_slot_returns_lowest_free():
    assert agy_pool.allocate_slot(set(), size=4, allow_home_fallback=True) == 0
    assert agy_pool.allocate_slot({0, 1}, size=4, allow_home_fallback=True) == 2

def test_allocate_slot_returns_none_when_full():
    assert agy_pool.allocate_slot({0, 1, 2, 3}, size=4, allow_home_fallback=True) is None

def test_worker_env_sets_private_home_and_gca():
    env = agy_pool.worker_env('/repo', 1, {'PATH': '/usr/bin'})
    assert env['HOME'] == str(agy_pool.worker_home('/repo', 1))
    assert env['GOOGLE_GENAI_USE_GCA'] == '1'
    assert env['PATH'] == '/usr/bin'

def test_worker_env_does_not_mutate_base():
    base = {'PATH': '/usr/bin'}
    agy_pool.worker_env('/repo', 0, base)
    assert 'HOME' not in base
import json
import pytest

def test_get_process_start_time():
    pid = os.getpid()
    start_time = agy_pool.get_process_start_time(pid)
    assert isinstance(start_time, int)
    assert start_time >= 0

def test_allocate_slot_acquires_lock(tmp_path):
    repo_root = str(tmp_path)
    slot = agy_pool.allocate_slot(set(), size=4, repo_root=repo_root)
    assert slot == 0
    lock_path = Path(repo_root) / '.agents' / 'agy-pool' / 'w0.lock'
    assert lock_path.exists()
    with open(lock_path, 'r') as f:
        data = json.load(f)
    assert data['pid'] == os.getpid()
    assert isinstance(data['start_time'], int)

def test_allocate_slot_reclaims_stale_lock(tmp_path, monkeypatch):
    repo_root = str(tmp_path)
    root = Path(repo_root) / '.agents' / 'agy-pool'
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / 'w0.lock'
    with open(lock_path, 'w') as f:
        json.dump({'pid': 99999, 'start_time': 100}, f)
    monkeypatch.setattr(agy_pool, '_is_pid_alive', lambda pid: False if pid == 99999 else True)
    slot = agy_pool.allocate_slot(set(), size=1, repo_root=repo_root)
    assert slot == 0
    with open(lock_path, 'r') as f:
        data = json.load(f)
    assert data['pid'] == os.getpid()

def test_allocate_slot_prevents_recycled_pid(tmp_path, monkeypatch):
    repo_root = str(tmp_path)
    root = Path(repo_root) / '.agents' / 'agy-pool'
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / 'w0.lock'
    with open(lock_path, 'w') as f:
        json.dump({'pid': 99999, 'start_time': 100}, f)
    monkeypatch.setattr(agy_pool, '_is_pid_alive', lambda pid: True)
    monkeypatch.setattr(agy_pool, 'get_process_start_time', lambda pid: 200 if pid == 99999 else 100)
    slot = agy_pool.allocate_slot(set(), size=1, repo_root=repo_root)
    assert slot == 0
    with open(lock_path, 'r') as f:
        data = json.load(f)
    assert data['pid'] == os.getpid()

def test_allocate_slot_raises_without_fallback(tmp_path, monkeypatch):
    repo_root = str(tmp_path)
    monkeypatch.setattr(agy_pool, '_is_pid_alive', lambda pid: True)
    slot1 = agy_pool.allocate_slot(set(), size=2, repo_root=repo_root)
    assert slot1 == 0
    slot2 = agy_pool.allocate_slot(set(), size=2, repo_root=repo_root)
    assert slot2 == 1
    with pytest.raises(RuntimeError):
        agy_pool.allocate_slot(set(), size=2, allow_home_fallback=False, repo_root=repo_root)

def test_allocate_slot_corrupted_lock_reclamation(tmp_path):
    repo_root = str(tmp_path)
    root = Path(repo_root) / '.agents' / 'agy-pool'
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / 'w0.lock'
    with open(lock_path, 'w') as f:
        f.write('corrupted data')
    slot = agy_pool.allocate_slot(set(), size=1, repo_root=repo_root)
    assert slot == 0
    with open(lock_path, 'r') as f:
        data = json.load(f)
    assert data['pid'] == os.getpid()

def test_allocate_slot_valid_pid_retained(tmp_path, monkeypatch):
    repo_root = str(tmp_path)
    root = Path(repo_root) / '.agents' / 'agy-pool'
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / 'w0.lock'
    with open(lock_path, 'w') as f:
        json.dump({'pid': 99999, 'start_time': 100}, f)
    monkeypatch.setattr(agy_pool, '_is_pid_alive', lambda pid: True if pid == 99999 else False)
    monkeypatch.setattr(agy_pool, 'get_process_start_time', lambda pid: 100 if pid == 99999 else None)
    slot = agy_pool.allocate_slot(set(), size=2, repo_root=repo_root)
    assert slot == 1
    with open(lock_path, 'r') as f:
        data = json.load(f)
    assert data['pid'] == 99999
    assert data['start_time'] == 100

def test_allocate_slot_concurrency_file_locking(tmp_path, monkeypatch):
    repo_root = str(tmp_path)
    root = Path(repo_root) / '.agents' / 'agy-pool'
    root.mkdir(parents=True, exist_ok=True)
    lock_path = root / 'w0.lock'
    original_open = os.open
    calls = []

    def mock_open(path, flags, mode=511):
        if Path(path) == lock_path and (not calls):
            calls.append(True)
            raise FileExistsError()
        return original_open(path, flags, mode)
    monkeypatch.setattr(os, 'open', mock_open)
    slot = agy_pool.allocate_slot(set(), size=2, repo_root=repo_root)
    assert slot == 1

def test_allocate_slot_multiple_concurrent_processes(tmp_path):
    repo_root = str(tmp_path)
    s0 = agy_pool.allocate_slot(set(), size=4, repo_root=repo_root)
    s1 = agy_pool.allocate_slot(set(), size=4, repo_root=repo_root)
    s2 = agy_pool.allocate_slot(set(), size=4, repo_root=repo_root)
    assert s0 == 0
    assert s1 == 1
    assert s2 == 2

def test_allocate_slot_degenerate_size(tmp_path):
    repo_root = str(tmp_path)
    with pytest.raises(RuntimeError):
        agy_pool.allocate_slot(set(), size=0, allow_home_fallback=False, repo_root=repo_root)
    assert agy_pool.allocate_slot(set(), size=0, allow_home_fallback=True, repo_root=repo_root) is None

def test_allocate_slot_allow_fallback_returns_none(tmp_path, monkeypatch):
    repo_root = str(tmp_path)
    monkeypatch.setattr(agy_pool, '_is_pid_alive', lambda pid: True)
    agy_pool.allocate_slot(set(), size=2, repo_root=repo_root)
    agy_pool.allocate_slot(set(), size=2, repo_root=repo_root)
    slot = agy_pool.allocate_slot(set(), size=2, allow_home_fallback=True, repo_root=repo_root)
    assert slot is None