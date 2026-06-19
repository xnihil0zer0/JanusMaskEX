"""RED oracle for int3-p2: flag-gated, deterministic, task_id-derived worker
cwd pinning in ``harness.orchestrator``.

These tests pin the contract for ``harness.orchestrator._build_agent_env`` and
its new helpers ``_pin_task_cwd_enabled`` / ``_pinned_session_slug``:

  * FLAG OFF (default / missing ``workers.pin_task_cwd``): the
    ``JANUSMASK_WORK_DIR`` basename keeps HEAD's uuid8 shape
    (``claude-r1-<task>-<8hex>``) and two calls with the SAME task_id produce
    DIFFERENT cwds (uuid randomness preserved -- behaviour byte-identical to
    HEAD).
  * FLAG ON: ``_pinned_session_slug`` and the resulting ``JANUSMASK_WORK_DIR``
    are deterministic (same ``(agent, round_number, task_id)`` -> identical
    slug/cwd across calls), distinct task_ids -> distinct slugs, and the slug is
    path-safe (only ``[A-Za-z0-9._-]``, no ``os.sep``) with no random uuid tail
    (repeats byte-identically).
  * WIRED: source-level proof (``inspect.getsource``) that ``_build_agent_env``
    routes the pinned slug through ``agent_work_dir(agent, session_slug)`` into
    ``JANUSMASK_WORK_DIR``, and that ``spawn_claude_tmux`` reads
    ``env['JANUSMASK_WORK_DIR']`` and threads ``work_dir=`` into the PTY backend.

The wiring/ON tests reference ``harness.orchestrator._pinned_session_slug``
directly; on HEAD that symbol does not exist, so the missing-symbol surfaces as
a real AttributeError failure (NOT a skip). The OFF tests exercise the live
HEAD behaviour and stay green there, but fail against any mutant that breaks the
uuid8 slug shape or its per-spawn randomness.

Safety: these tests use only string / regex / ``inspect.getsource`` checks plus
direct calls into the pure ``_build_agent_env`` env-builder. They NEVER spawn an
agent and never call ``exec`` / ``eval`` / ``compile`` / ``__import__``.
"""
from __future__ import annotations
import inspect
import os
import re
import harness.orchestrator as orch
import harness.tmux_worker as tmux_worker
_UUID8_TAIL = re.compile('-[0-9a-f]{8}$')
_PATH_SAFE = re.compile('^[A-Za-z0-9._-]+$')

def _work_dir_basename(env: dict) -> str:
    return os.path.basename(env['JANUSMASK_WORK_DIR'])

def test_flag_off_matches_head_uuid8_shape(monkeypatch, tmp_path):
    """Default/OFF: JANUSMASK_WORK_DIR basename keeps the HEAD uuid8 shape."""
    monkeypatch.setattr(orch, '_pin_task_cwd_enabled', lambda: False, raising=False)
    monkeypatch.setenv('JANUSMASK_TASK_ID', 'alpha-task')
    env = orch._build_agent_env('claude', str(tmp_path), 1)
    base = _work_dir_basename(env)
    assert base.startswith('claude-r1-alpha-task-')
    assert _UUID8_TAIL.search(base), base

def test_flag_off_same_task_id_yields_different_cwds(monkeypatch, tmp_path):
    """OFF: two spawns with the same task_id keep distinct uuid-tailed cwds."""
    monkeypatch.setattr(orch, '_pin_task_cwd_enabled', lambda: False, raising=False)
    monkeypatch.setenv('JANUSMASK_TASK_ID', 'alpha-task')
    env_a = orch._build_agent_env('claude', str(tmp_path), 1)
    env_b = orch._build_agent_env('claude', str(tmp_path), 1)
    base_a = _work_dir_basename(env_a)
    base_b = _work_dir_basename(env_b)
    assert _UUID8_TAIL.search(base_a)
    assert _UUID8_TAIL.search(base_b)
    assert base_a != base_b
    assert env_a['JANUSMASK_WORK_DIR'] != env_b['JANUSMASK_WORK_DIR']

def test_flag_on_pinned_slug_deterministic_same_inputs(monkeypatch, tmp_path):
    """ON: same (agent, round, task_id) -> identical slug and cwd across calls."""
    monkeypatch.setattr(orch, '_pin_task_cwd_enabled', lambda: True, raising=False)
    monkeypatch.setenv('JANUSMASK_TASK_ID', 'alpha-task')
    slug_a = orch._pinned_session_slug('claude', 1, 'alpha-task')
    slug_b = orch._pinned_session_slug('claude', 1, 'alpha-task')
    assert slug_a == slug_b
    env_a = orch._build_agent_env('claude', str(tmp_path), 1)
    env_b = orch._build_agent_env('claude', str(tmp_path), 1)
    base_a = _work_dir_basename(env_a)
    base_b = _work_dir_basename(env_b)
    assert base_a == base_b
    assert env_a['JANUSMASK_WORK_DIR'] == env_b['JANUSMASK_WORK_DIR']
    assert base_a == slug_a

def test_flag_on_distinct_task_ids_distinct_slugs(monkeypatch, tmp_path):
    """ON: distinct task_ids -> distinct slugs and distinct cwds."""
    monkeypatch.setattr(orch, '_pin_task_cwd_enabled', lambda: True, raising=False)
    slug_a = orch._pinned_session_slug('claude', 1, 'task-aaa')
    slug_b = orch._pinned_session_slug('claude', 1, 'task-bbb')
    assert slug_a != slug_b
    monkeypatch.setenv('JANUSMASK_TASK_ID', 'task-aaa')
    env_a = orch._build_agent_env('claude', str(tmp_path), 1)
    monkeypatch.setenv('JANUSMASK_TASK_ID', 'task-bbb')
    env_b = orch._build_agent_env('claude', str(tmp_path), 1)
    assert _work_dir_basename(env_a) != _work_dir_basename(env_b)

def test_flag_on_slug_path_safe_no_sep_no_uuid_tail(monkeypatch, tmp_path):
    """ON: slug sanitizes unsafe task_ids to a path-safe, deterministic slug."""
    monkeypatch.setattr(orch, '_pin_task_cwd_enabled', lambda: True, raising=False)
    raw = 'a/b c\\d:e'
    slug = orch._pinned_session_slug('claude', 1, raw)
    assert _PATH_SAFE.match(slug), slug
    assert os.sep not in slug
    assert '/' not in slug and '\\' not in slug
    assert orch._pinned_session_slug('claude', 1, raw) == slug
    other = 'a/b c\\d:f'
    assert orch._pinned_session_slug('claude', 1, other) != slug
    monkeypatch.setenv('JANUSMASK_TASK_ID', raw)
    env = orch._build_agent_env('claude', str(tmp_path), 1)
    base = _work_dir_basename(env)
    assert _PATH_SAFE.match(base), base
    assert os.sep not in base
    assert base == slug

def test_pinned_slug_idempotent_across_repeated_calls(monkeypatch):
    """ON: repeated _pinned_session_slug calls are byte-identical (idempotent)."""
    monkeypatch.setattr(orch, '_pin_task_cwd_enabled', lambda: True, raising=False)
    slugs = {orch._pinned_session_slug('claude', 1, 'alpha-task') for _ in range(8)}
    assert len(slugs) == 1, slugs
    r2 = {orch._pinned_session_slug('claude', 2, 'alpha-task') for _ in range(8)}
    assert len(r2) == 1, r2

def test_build_agent_env_wires_pinned_slug_through_work_dir_seam():
    """_build_agent_env routes the flag-gated pinned slug into JANUSMASK_WORK_DIR."""
    src = inspect.getsource(orch._build_agent_env)
    assert '_pin_task_cwd_enabled(' in src
    assert '_pinned_session_slug(' in src
    assert 'agent_work_dir(agent, session_slug)' in src
    assert 'JANUSMASK_WORK_DIR' in src

def test_spawn_claude_tmux_threads_work_dir_into_pty_backend():
    """spawn_claude_tmux reads env['JANUSMASK_WORK_DIR'] and threads work_dir=."""
    src = inspect.getsource(tmux_worker.spawn_claude_tmux)
    assert "env['JANUSMASK_WORK_DIR']" in src
    assert 'work_dir=work_dir' in src