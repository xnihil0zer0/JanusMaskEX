"""RED oracle for the flag-gated PTY ``--continue`` resume behaviour of
``harness.tmux_worker.spawn_claude_tmux``.

This file pins the *paired* (RED) contract for sub-plan int3-p3: a bwrap-jailed
interactive claude turn may resume its PINNED cwd session with a single
``--continue`` token, but ONLY when

  1. the ``workers.resume_pinned_session`` flag is ON
     (``harness.tmux_worker._resume_pinned_session_enabled() -> True``), AND
  2. cwd-pinning is ON
     (``harness.orchestrator._pin_task_cwd_enabled() -> True``), AND
  3. a prior session transcript actually exists for the pinned cwd
     (``harness.tmux_worker._pinned_session_present(config_dir, work_dir) -> True``).

OFF by default the produced jailed argv is byte-identical to HEAD (no
``--continue``). The DO-NOT-BUILD ``--input-format stream-json`` resume loop
(GH #3187 hang) is asserted ABSENT in every case.

All checks are string / inspect / seam-driven over a minimal real env+config in
``tmp_path``; the injectable ``run_worker`` seam captures the ``jailed_argv``
kwarg. No real claude / PTY / subprocess is ever spawned, and exec / eval /
compile / __import__ are never used.

These tests FAIL against HEAD (the new helpers and the ``--continue`` wiring do
not yet exist) and FAIL against the declared mutant of ``harness.tmux_worker``;
they go GREEN once the implementation lands.
"""
from __future__ import annotations
import inspect
import re
import pytest
import harness.tmux_worker as tw

def _encode_cwd(path: str) -> str:
    """Claude's project-dir encoding: every non-[A-Za-z0-9] char -> '-'."""
    return re.sub('[^A-Za-z0-9]', '-', str(path))

def _patch_resume(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(tw, '_resume_pinned_session_enabled', lambda: value)

def _patch_pinning(monkeypatch, value: bool) -> None:
    import harness.orchestrator as orch
    monkeypatch.setattr(orch, '_pin_task_cwd_enabled', lambda: value)
    if hasattr(tw, '_pin_task_cwd_enabled'):
        monkeypatch.setattr(tw, '_pin_task_cwd_enabled', lambda: value, raising=False)

def _patch_present(monkeypatch, value: bool) -> None:
    monkeypatch.setattr(tw, '_pinned_session_present', lambda *a, **k: value)

def _setup_spawn(tmp_path, monkeypatch, *, name: str):
    """Minimal real env+config in tmp_path plus a capturing run_worker seam.

    Returns ``(work_dir, state_dir, env, config, cap, fake_run_worker)`` where
    ``cap`` records the interactive argv handed to the jail and the jailed argv
    handed to the worker.
    """
    base = tmp_path / name
    work_dir = base / 'wd'
    work_dir.mkdir(parents=True)
    state_dir = base / 'state'
    state_dir.mkdir(parents=True)
    fake_home = base / 'home'
    fake_home.mkdir(parents=True)
    monkeypatch.setenv('HOME', str(fake_home))
    monkeypatch.delenv('JANUSMASK_WORKING_DIR', raising=False)
    cap: dict = {}

    def spy_build_jail_argv(cmd, **kwargs):
        cap['interactive'] = list(cmd)
        cap['jail_kwargs'] = kwargs
        return ['/usr/bin/bwrap', '--JAILED--', *cmd]
    monkeypatch.setattr(tw.agent_jail, 'build_jail_argv', spy_build_jail_argv)

    def fake_run_worker(*, jailed_argv, work_dir, **kwargs):
        cap['jailed_argv'] = list(jailed_argv)
        cap['run_kwargs'] = dict(work_dir=work_dir, **kwargs)
        return tw.TmuxWorkerResult(started=True, idle=True, snapshot='')
    config = {'agents': {'claude': {'command': '/opt/claude/bin/claude', 'args': ['--model', 'opus', '--tools', 'Read,Glob,Grep,Write']}}, 'synthesis': {'timeout_seconds': 123}}
    env = {'JANUSMASK_WORK_DIR': str(work_dir), 'JANUSMASK_STATE_DIR': str(state_dir), 'JANUSMASK_TASK_ID': 'leaf-' + name}
    return (work_dir, state_dir, env, config, cap, fake_run_worker)

def _seed_prior_transcript(work_dir) -> str:
    """Create ``<work_dir>/.tmuxcfg/projects/<cwd-encoded>/sess.jsonl`` and
    return the config_dir."""
    config_dir = work_dir / '.tmuxcfg'
    proj = config_dir / 'projects' / _encode_cwd(str(work_dir))
    proj.mkdir(parents=True)
    (proj / 'sess.jsonl').write_text('{"type": "summary"}\n')
    return str(config_dir)

def test_flag_off_no_continue_token_byte_identical_to_head(tmp_path, monkeypatch):
    work_dir, state_dir, env, config, cap, fake_run_worker = _setup_spawn(tmp_path, monkeypatch, name='off')
    _seed_prior_transcript(work_dir)
    _patch_resume(monkeypatch, False)
    _patch_pinning(monkeypatch, True)
    tw.spawn_claude_tmux('claude', 'BODY', env, config, run_worker=fake_run_worker)
    jailed = cap['jailed_argv']
    assert '--continue' not in jailed, 'resume OFF must not inject --continue'
    assert '--input-format' not in jailed
    assert 'stream-json' not in jailed
    assert '-p' not in jailed and '--print' not in jailed

def test_flag_on_pinning_on_prior_present_appends_continue_once_no_streamjson(tmp_path, monkeypatch):
    work_dir, state_dir, env, config, cap, fake_run_worker = _setup_spawn(tmp_path, monkeypatch, name='on')
    config_dir = _seed_prior_transcript(work_dir)
    _patch_resume(monkeypatch, True)
    _patch_pinning(monkeypatch, True)
    assert tw._pinned_session_present(config_dir, str(work_dir)) is True
    tw.spawn_claude_tmux('claude', 'BODY', env, config, run_worker=fake_run_worker)
    jailed = cap['jailed_argv']
    assert jailed.count('--continue') == 1, 'resume must inject --continue exactly once'
    assert '--input-format' not in jailed
    assert 'stream-json' not in jailed
    assert '--continue' in cap['interactive']

def test_first_attempt_no_prior_transcript_pinned_session_present_false_no_continue(tmp_path, monkeypatch):
    work_dir, state_dir, env, config, cap, fake_run_worker = _setup_spawn(tmp_path, monkeypatch, name='first')
    _patch_resume(monkeypatch, True)
    _patch_pinning(monkeypatch, True)
    config_dir = str(work_dir / '.tmuxcfg')
    assert tw._pinned_session_present(config_dir, str(work_dir)) is False
    tw.spawn_claude_tmux('claude', 'BODY', env, config, run_worker=fake_run_worker)
    jailed = cap['jailed_argv']
    assert '--continue' not in jailed, 'first attempt (no prior session) must not resume'
    assert 'stream-json' not in jailed

def test_pinned_session_present_seam_absent_or_empty_projects_false_jsonl_present_true():
    cfg = '/cfgdir'
    wd = '/work/dir'

    def _ends_projects(p) -> bool:
        return str(p).rstrip('/').endswith('projects')
    assert tw._pinned_session_present(cfg, wd, exists=lambda p: False, listdir=lambda p: []) is False
    assert tw._pinned_session_present(cfg, wd, exists=lambda p: True, listdir=lambda p: []) is False

    def ld_txt(p):
        return ['proj1'] if _ends_projects(p) else ['notes.txt']
    assert tw._pinned_session_present(cfg, wd, exists=lambda p: True, listdir=ld_txt) is False

    def ld_jsonl(p):
        return ['proj1'] if _ends_projects(p) else ['sess.jsonl']
    assert tw._pinned_session_present(cfg, wd, exists=lambda p: True, listdir=ld_jsonl) is True

    def ld_boom(p):
        raise OSError('boom')
    assert tw._pinned_session_present(cfg, wd, exists=lambda p: True, listdir=ld_boom) is False

def test_spawn_source_guards_continue_with_all_three_predicates_and_flows_to_jail_and_run_worker():
    src = inspect.getsource(tw.spawn_claude_tmux)
    assert '_resume_pinned_session_enabled(' in src
    assert '_pin_task_cwd_enabled(' in src
    assert '_pinned_session_present(' in src
    assert '--continue' in src
    assert 'interactive' in src
    assert 'build_jail_argv(' in src
    assert 'jailed_argv=' in src
    assert callable(tw._resume_pinned_session_enabled)
    assert callable(tw._pinned_session_present)

def test_regression_resume_flag_default_off_keeps_argv_identical_to_head(tmp_path, monkeypatch):
    """Default / missing ``workers.resume_pinned_session`` reads False, so the
    jailed argv carries no --continue (byte-identical to HEAD)."""
    monkeypatch.setattr('harness.orchestrator.load_config', lambda: {})
    assert tw._resume_pinned_session_enabled() is False
    work_dir, state_dir, env, config, cap, fake_run_worker = _setup_spawn(tmp_path, monkeypatch, name='regdefault')
    _seed_prior_transcript(work_dir)
    _patch_pinning(monkeypatch, True)
    tw.spawn_claude_tmux('claude', 'BODY', env, config, run_worker=fake_run_worker)
    jailed = cap['jailed_argv']
    assert '--continue' not in jailed
    assert '--input-format' not in jailed
    assert 'stream-json' not in jailed

def test_regression_continue_only_when_resume_and_pinning_and_prior_transcript_all_true(tmp_path, monkeypatch):
    """--continue appears IFF resume AND pinning AND prior-transcript are all
    true; flipping any single predicate off removes it."""

    def drive(resume: bool, pinning: bool, present: bool, tag: str):
        work_dir, state_dir, env, config, cap, fake_run_worker = _setup_spawn(tmp_path, monkeypatch, name='combo-' + tag)
        _patch_resume(monkeypatch, resume)
        _patch_pinning(monkeypatch, pinning)
        _patch_present(monkeypatch, present)
        tw.spawn_claude_tmux('claude', 'BODY', env, config, run_worker=fake_run_worker)
        return cap['jailed_argv']
    assert drive(True, True, True, 'all').count('--continue') == 1
    assert '--continue' not in drive(False, True, True, 'noresume')
    assert '--continue' not in drive(True, False, True, 'nopin')
    assert '--continue' not in drive(True, True, False, 'noprior')

def test_regression_never_emits_input_format_stream_json_do_not_build_path(tmp_path, monkeypatch):
    """Even with resume fully active, the DO-NOT-BUILD stream-json resume loop
    (GH #3187 hang) is never emitted -- only the bare --continue token is."""
    work_dir, state_dir, env, config, cap, fake_run_worker = _setup_spawn(tmp_path, monkeypatch, name='nostreamjson')
    _patch_resume(monkeypatch, True)
    _patch_pinning(monkeypatch, True)
    _patch_present(monkeypatch, True)
    tw.spawn_claude_tmux('claude', 'BODY', env, config, run_worker=fake_run_worker)
    jailed = cap['jailed_argv']
    assert '--continue' in jailed
    assert '--input-format' not in jailed
    assert 'stream-json' not in jailed