import json
import os
import pathlib
import time
import pytest
import importlib
autowork_daemon = importlib.import_module('harness.autowork_daemon')
_recently_failed_to_plan = autowork_daemon._recently_failed_to_plan
_plan_attempt_marker_path = autowork_daemon._plan_attempt_marker_path

def write_marker(state_dir, slug, attempts, deterministic, last_ts):
    marker_path = _plan_attempt_marker_path(state_dir, slug)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    data = {'attempts': attempts, 'deterministic': deterministic, 'last_ts': last_ts}
    marker_path.write_text(json.dumps(data), encoding='utf-8')

def write_brief(state_dir, slug, mtime):
    brief_p = pathlib.Path(state_dir).parent / f'brief_hooks_{slug}.md'
    brief_p.write_text('dummy brief content', encoding='utf-8')
    os.utime(brief_p, (mtime, mtime))

def test_not_reauthored_brief(tmp_path):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    now = time.time()
    last_ts = now - 50.0
    brief_mtime = last_ts - 10.0
    write_marker(state_dir, slug, attempts=3, deterministic=False, last_ts=last_ts)
    write_brief(state_dir, slug, mtime=brief_mtime)
    result = _recently_failed_to_plan(state_dir, slug)
    assert result is True
    marker_path = _plan_attempt_marker_path(state_dir, slug)
    assert marker_path.exists()
    data = json.loads(marker_path.read_text(encoding='utf-8'))
    assert data['attempts'] == 3
    assert data['deterministic'] is False
    assert data['last_ts'] == last_ts

def test_first_reauthor_chance_granted(tmp_path):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    now = time.time()
    last_ts = now - 50.0
    brief_mtime = last_ts + 10.0
    write_marker(state_dir, slug, attempts=3, deterministic=False, last_ts=last_ts)
    write_brief(state_dir, slug, mtime=brief_mtime)
    result = _recently_failed_to_plan(state_dir, slug)
    assert result is False
    marker_path = _plan_attempt_marker_path(state_dir, slug)
    assert marker_path.exists()
    data = json.loads(marker_path.read_text(encoding='utf-8'))
    assert data['attempts'] == 3
    assert data['deterministic'] is False
    assert data['last_ts'] >= brief_mtime

def test_second_call_reauthor_consumed(tmp_path):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    now = time.time()
    last_ts = now - 50.0
    brief_mtime = last_ts + 10.0
    write_marker(state_dir, slug, attempts=3, deterministic=False, last_ts=last_ts)
    write_brief(state_dir, slug, mtime=brief_mtime)
    result1 = _recently_failed_to_plan(state_dir, slug)
    assert result1 is False
    result2 = _recently_failed_to_plan(state_dir, slug)
    assert result2 is True
    marker_path = _plan_attempt_marker_path(state_dir, slug)
    assert marker_path.exists()
    data = json.loads(marker_path.read_text(encoding='utf-8'))
    assert data['attempts'] == 3
    assert data['deterministic'] is False

def test_second_reauthor_bump_chance_granted(tmp_path):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    now = time.time()
    last_ts = now - 100.0
    brief_mtime_1 = last_ts + 10.0
    write_marker(state_dir, slug, attempts=3, deterministic=False, last_ts=last_ts)
    write_brief(state_dir, slug, mtime=brief_mtime_1)
    result1 = _recently_failed_to_plan(state_dir, slug)
    assert result1 is False
    result2 = _recently_failed_to_plan(state_dir, slug)
    assert result2 is True
    marker_path = _plan_attempt_marker_path(state_dir, slug)
    data = json.loads(marker_path.read_text(encoding='utf-8'))
    current_marker_ts = data['last_ts']
    brief_mtime_2 = current_marker_ts + 10.0
    write_brief(state_dir, slug, mtime=brief_mtime_2)
    result3 = _recently_failed_to_plan(state_dir, slug)
    assert result3 is False
    data = json.loads(marker_path.read_text(encoding='utf-8'))
    assert data['attempts'] == 3
    assert data['deterministic'] is False
    assert data['last_ts'] >= brief_mtime_2

def test_os_error_resilience(tmp_path, monkeypatch):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    now = time.time()
    last_ts = now - 50.0
    write_marker(state_dir, slug, attempts=3, deterministic=False, last_ts=last_ts)
    original_stat = pathlib.Path.stat

    def mock_stat(self, *args, **kwargs):
        if 'brief_hooks' in self.name:
            raise OSError('Simulated permission error')
        return original_stat(self, *args, **kwargs)
    monkeypatch.setattr(pathlib.Path, 'stat', mock_stat)
    write_brief(state_dir, slug, mtime=last_ts + 10.0)
    try:
        result = _recently_failed_to_plan(state_dir, slug)
        assert result is True
    except Exception as e:
        pytest.fail(f'_recently_failed_to_plan crashed with {e} when stat raised OSError')
    monkeypatch.undo()
    original_write = pathlib.Path.write_text

    def mock_write(self, *args, **kwargs):
        if self.name.endswith('.json'):
            raise OSError('Simulated write error')
        return original_write(self, *args, **kwargs)
    monkeypatch.setattr(pathlib.Path, 'write_text', mock_write)
    write_brief(state_dir, slug, mtime=last_ts + 10.0)
    try:
        result = _recently_failed_to_plan(state_dir, slug)
        assert result is False
    except Exception as e:
        pytest.fail(f'_recently_failed_to_plan crashed with {e} when writing marker raised OSError')

def test_reauthor_missing_marker(tmp_path):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    result = _recently_failed_to_plan(state_dir, slug)
    assert result is False

def test_reauthor_invalid_json(tmp_path):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    marker_path = _plan_attempt_marker_path(state_dir, slug)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    marker_path.write_text('invalid json', encoding='utf-8')
    result = _recently_failed_to_plan(state_dir, slug)
    assert result is False

def test_reauthor_no_brief_file(tmp_path):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    now = time.time()
    write_marker(state_dir, slug, attempts=3, deterministic=False, last_ts=now - 50.0)
    result = _recently_failed_to_plan(state_dir, slug)
    assert result is True

def test_reauthor_invalid_last_ts(tmp_path):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    marker_path = _plan_attempt_marker_path(state_dir, slug)
    marker_path.parent.mkdir(parents=True, exist_ok=True)
    data = {'attempts': 3, 'deterministic': False, 'last_ts': 'not a float'}
    marker_path.write_text(json.dumps(data), encoding='utf-8')
    result = _recently_failed_to_plan(state_dir, slug)
    assert result is False

def test_reauthor_deterministic_park(tmp_path):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    now = time.time()
    write_marker(state_dir, slug, attempts=1, deterministic=True, last_ts=now - 1000.0)
    write_brief(state_dir, slug, mtime=now - 2000.0)
    result = _recently_failed_to_plan(state_dir, slug)
    assert result is True

def test_reauthor_non_deterministic_park(tmp_path):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    now = time.time()
    write_marker(state_dir, slug, attempts=2, deterministic=False, last_ts=now - 1.0)
    write_brief(state_dir, slug, mtime=now - 2.0)
    result = _recently_failed_to_plan(state_dir, slug)
    assert result is False

def test_reauthor_os_error_on_stat(tmp_path, monkeypatch):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    now = time.time()
    last_ts = now - 50.0
    write_marker(state_dir, slug, attempts=3, deterministic=False, last_ts=last_ts)
    write_brief(state_dir, slug, mtime=last_ts + 10.0)
    original_stat = pathlib.Path.stat

    def mock_stat(self, *args, **kwargs):
        if 'brief_hooks' in self.name:
            raise OSError('Simulated permission error')
        return original_stat(self, *args, **kwargs)
    monkeypatch.setattr(pathlib.Path, 'stat', mock_stat)
    result = _recently_failed_to_plan(state_dir, slug)
    assert result is True

def test_reauthor_os_error_on_write(tmp_path, monkeypatch):
    slug = 'test_slug'
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    now = time.time()
    last_ts = now - 50.0
    write_marker(state_dir, slug, attempts=3, deterministic=False, last_ts=last_ts)
    write_brief(state_dir, slug, mtime=last_ts + 10.0)
    original_write = pathlib.Path.write_text

    def mock_write(self, *args, **kwargs):
        if self.name.endswith('.json'):
            raise OSError('Simulated write error')
        return original_write(self, *args, **kwargs)
    monkeypatch.setattr(pathlib.Path, 'write_text', mock_write)
    result = _recently_failed_to_plan(state_dir, slug)
    assert result is False