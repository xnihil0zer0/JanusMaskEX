"""Unit and seam tests for ``harness/tmux_worker.py``.

These tests exercise the REAL observable behaviour of the tmux worker backend
over injected fakes only. No real ``tmux`` session or ``claude`` process is ever
spawned: every side-effecting seam (the executor, the optional jail backend, the
filesystem) is redirected at injected fakes or ``tmp_path``. Per the spec, the
live end-to-end path (a real interactive claude in a real tmux session) is an
operator-validated, post-merge step and is deliberately out of scope here.
"""
from __future__ import annotations
import json
import pytest
from harness import tmux_worker as tw

def test_exited_proc_poll_and_wait() -> None:
    """poll()/wait() report an immediate clean exit and never block."""
    proc = tw._ExitedProc(work_dir='/some/work')
    result = proc.poll()
    assert result is not None
    assert result == 0
    assert proc.wait() == 0
    assert proc.wait(timeout=5.0) == 0
    assert proc.returncode == 0
    assert proc._work_dir == '/some/work'
    assert '/some/work' in repr(proc)

def test_exited_proc_kill() -> None:
    """kill()/terminate() are no-ops that do not mutate the clean exit code."""
    proc = tw._ExitedProc()
    assert proc._work_dir is None
    assert proc.kill() is None
    assert proc.terminate() is None
    assert proc.returncode == 0
    assert proc.poll() == 0

def test_tmux_worker_result_ok_reflects_returncode() -> None:
    """``ok`` is True only for a zero returncode."""
    clean = tw.TmuxWorkerResult(returncode=0, session_name='s', work_dir='/w')
    assert clean.ok is True
    assert clean.session_name == 's'
    failed = tw.TmuxWorkerResult(returncode=3)
    assert failed.ok is False

def test_as_mapping_coerces_none_object_and_mapping() -> None:
    """_as_mapping tolerates None / objects / mappings without raising."""
    assert tw._as_mapping(None) == {}
    src = {'a': 1, 'b': 2}
    coerced = tw._as_mapping(src)
    assert coerced == src
    assert coerced is not src

    class Cfg:

        def __init__(self) -> None:
            self.claude_bin = 'claude'
            self.extra = 7
    obj = tw._as_mapping(Cfg())
    assert obj['claude_bin'] == 'claude'
    assert obj['extra'] == 7
    assert tw._as_mapping(42) == {}

def test_cfg_get_skips_empty_and_uses_default() -> None:
    """_cfg_get returns first present, non-empty value, else the default."""
    cfg = {'primary': '', 'secondary': 'value', 'blank': None, 'empty': []}
    assert tw._cfg_get(cfg, 'primary', 'secondary') == 'value'
    assert tw._cfg_get(cfg, 'blank', 'empty', default='fallback') == 'fallback'
    assert tw._cfg_get(cfg, 'missing', default='d') == 'd'

def test_default_session_name_sanitizes_task_id() -> None:
    """Session name is derived from JANUSMASK_TASK_ID with unsafe chars scrubbed."""
    assert tw._default_session_name({'JANUSMASK_TASK_ID': 'abc-123'}) == 'janusmask-abc-123'
    assert tw._default_session_name({'JANUSMASK_TASK_ID': 'a b/c.d'}) == 'janusmask-a_b_c_d'
    assert tw._default_session_name({}) == 'janusmask-worker'

def test_seed_from_prompt_file_writes_config_and_credentials(tmp_path) -> None:
    """Config (and credentials, when present) are seeded into the work dir."""
    work = tmp_path / 'wd'
    config = {'claude_config': {'key': 'abc', 'nested': {'x': 1}}, 'credentials': {'token': 'secret'}, 'claude_bin': 'claude'}
    dest = tw.seed_from_prompt_file(config, work)
    assert dest == work / '.claude.json'
    assert dest.exists()
    written = json.loads(dest.read_text())
    assert written == {'key': 'abc', 'nested': {'x': 1}}
    creds_file = work / '.credentials.json'
    assert creds_file.exists()
    assert json.loads(creds_file.read_text()) == {'token': 'secret'}

def test_seed_from_prompt_file_handles_empty_config(tmp_path) -> None:
    """With no explicit sub-config the bin/arg keys are stripped from the seed."""
    work = tmp_path / 'wd2'
    dest = tw.seed_from_prompt_file({'claude_bin': 'claude', 'claude_args': ['-x']}, work)
    assert json.loads(dest.read_text()) == {}
    assert not (work / '.credentials.json').exists()

def test_jail_command_passthrough_without_backend(monkeypatch) -> None:
    """With no jail backend the command is returned unchanged (a fresh list)."""
    monkeypatch.setattr(tw, '_agent_jail', None)
    cmd = ['claude', '--flag']
    out = tw.jail_command(cmd, env={}, work_dir='/w', state_dir='/s')
    assert out == ['claude', '--flag']
    assert out is not cmd

def test_jail_command_uses_backend_when_available(monkeypatch) -> None:
    """When a jail backend exposes a known entrypoint it wraps the command."""
    calls = {}

    class FakeJail:

        @staticmethod
        def build_jail_command(command, *, env, work_dir, state_dir, dbus_sock=None):
            calls['command'] = command
            calls['work_dir'] = work_dir
            return ['bwrap', '--'] + command
    monkeypatch.setattr(tw, '_agent_jail', FakeJail)
    out = tw.jail_command(['claude'], env={'A': '1'}, work_dir='/w', state_dir='/s')
    assert out == ['bwrap', '--', 'claude']
    assert calls['command'] == ['claude']
    assert calls['work_dir'] == '/w'

def test_tmux_executor_raises_when_unconfigured(monkeypatch) -> None:
    """The default executor RAISES (never hangs) when no tmux seam exists."""
    monkeypatch.setattr(tw, '_resolve_tmux_seam', lambda: None)
    with pytest.raises(RuntimeError):
        tw._tmux_executor(['claude'], env={}, work_dir='/w', session_name='s')

def test_tmux_executor_drives_resolved_seam(monkeypatch) -> None:
    """The executor forwards to the resolved seam and coerces its result."""
    seen = {}

    def fake_seam(command, *, env, work_dir, session_name):
        seen['command'] = command
        seen['session_name'] = session_name
        return 7
    monkeypatch.setattr(tw, '_resolve_tmux_seam', lambda: fake_seam)
    rc = tw._tmux_executor(['claude'], env={}, work_dir='/w', session_name='sess')
    assert rc == 7
    assert seen['command'] == ['claude']
    assert seen['session_name'] == 'sess'

def test_run_tmux_worker_uses_injected_executor(tmp_path) -> None:
    """run_tmux_worker delegates to the injected executor and reports its rc."""
    captured = {}

    def fake_executor(cmd, *, env, work_dir, session_name, config):
        captured['cmd'] = cmd
        captured['session_name'] = session_name
        captured['env'] = env
        return 0
    result = tw.run_tmux_worker(['claude', '-p'], env={'JANUSMASK_TASK_ID': 't9'}, work_dir=tmp_path / 'run', executor=fake_executor)
    assert isinstance(result, tw.TmuxWorkerResult)
    assert result.ok is True
    assert result.session_name == 'janusmask-t9'
    assert result.command == ['claude', '-p']
    assert (tmp_path / 'run').is_dir()
    assert captured['cmd'] == ['claude', '-p']
    assert captured['session_name'] == 'janusmask-t9'

def test_run_tmux_worker_propagates_failure_returncode(tmp_path) -> None:
    """A non-zero executor result surfaces as a non-ok TmuxWorkerResult."""
    result = tw.run_tmux_worker(['claude'], env={}, work_dir=tmp_path / 'fail', session_name='explicit-name', executor=lambda cmd, **kw: 5)
    assert result.returncode == 5
    assert result.ok is False
    assert result.session_name == 'explicit-name'

def test_build_claude_command_includes_bin_and_args(tmp_path) -> None:
    """The claude command honours configured binary and extra args."""
    prompt = tmp_path / 'prompt.txt'
    cmd = tw._build_claude_command(agent=object(), config={'claude_bin': '/usr/bin/claude', 'claude_args': ['--dangerously', '-v']}, prompt_file=prompt)
    assert cmd == ['/usr/bin/claude', '--dangerously', '-v']
    assert tw._build_claude_command(object(), {}, prompt) == ['claude']

def test_spawn_claude_tmux_success(tmp_path, monkeypatch) -> None:
    """Full happy path: dirs prepared, config/prompt seeded, seam driven, shim returned."""
    work = tmp_path / 'work'
    state = tmp_path / 'state'
    env = {'JANUSMASK_TASK_ID': 'task42', 'JANUSMASK_WORK_DIR': str(work), 'JANUSMASK_STATE_DIR': str(state)}
    config = {'claude_config': {'flag': True}, 'claude_bin': 'claude'}
    executor_calls = {}

    def fake_executor(cmd, *, env, work_dir, session_name, config):
        executor_calls['cmd'] = cmd
        executor_calls['session_name'] = session_name
        return 0
    monkeypatch.setattr(tw, '_tmux_executor', fake_executor)
    monkeypatch.setattr(tw, '_agent_jail', None)
    proc = tw.spawn_claude_tmux(agent=object(), resolved_prompt='do the thing', env=env, config=config)
    assert isinstance(proc, tw._ExitedProc)
    assert proc._work_dir == str(work)
    assert proc.poll() == 0
    assert proc.wait() == 0
    assert work.is_dir()
    assert state.is_dir()
    prompt_file = work / 'prompt.txt'
    assert prompt_file.read_text() == 'do the thing'
    seeded = json.loads((work / '.claude.json').read_text())
    assert seeded == {'flag': True}
    assert executor_calls['session_name'] == 'janusmask-task42'
    assert executor_calls['cmd'] == ['claude']

def test_spawn_claude_tmux_failure(tmp_path, monkeypatch) -> None:
    """When the tmux seam is unconfigured the spawn RAISES rather than hangs."""
    work = tmp_path / 'work'
    env = {'JANUSMASK_WORK_DIR': str(work), 'JANUSMASK_TASK_ID': 'boom'}
    monkeypatch.setattr(tw, '_resolve_tmux_seam', lambda: None)
    monkeypatch.setattr(tw, '_agent_jail', None)
    with pytest.raises(RuntimeError):
        tw.spawn_claude_tmux(agent=object(), resolved_prompt='hi', env=env, config={})
    assert work.is_dir()
    assert (work / 'prompt.txt').read_text() == 'hi'