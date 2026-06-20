"""Regression oracle for the headless session-resume (``--continue``) logic.

These tests pin the contract of ``harness.orchestrator._headless_resume_argv``
(the headless claude resume helper) and its wiring into ``spawn_agent``:

  * headless + resume-flag ON + pin-cwd ON + a prior transcript present
    -> the built headless claude argv gains ``--continue`` (warm resume),
  * any single predicate failing -> ``--continue`` is NOT added (fail-safe),
  * the tmux backend path is left byte-identical (helper is a no-op for tmux),
  * ``spawn_agent`` actually calls ``_headless_resume_argv`` and the helper's
    guards reference the 4 required predicates.

The tests drive the helper directly (signature-agnostically, via
``inspect.signature``) and stub ``load_config`` / ``os.path.exists`` /
``os.listdir`` so no real claude / PTY / subprocess is ever spawned.
"""
import inspect
import os
import pytest
import harness.orchestrator as orch

def _base_cmd(prompt='solve the staged task'):
    """A representative headless claude argv (contains -p and the prompt)."""
    return ['claude', '-p', prompt, '--output-format', 'stream-json', '--verbose']

def _make_config(resume=True, pin_cwd=True, backend='headless'):
    """Build an orchestrator config with the resume/pin/backend predicates.

    Several plausible flag-key spellings are populated together so that the
    behavioural tests stay robust to the exact key the implementation reads;
    every spelling is toggled in lock-step so a "flag OFF" config never leaves
    a stray "ON" alias behind.
    """
    return {'state_dir': '/tmp/jm-state', 'workers': {'claude_backend': backend, 'pin_task_cwd': pin_cwd, 'pin_cwd': pin_cwd, 'headless_resume': resume, 'headless_continue': resume, 'resume': resume, 'claude_resume': resume}}

def _invoke(cmd, agent='claude', config=None, work_dir='/tmp/jm-work'):
    """Call ``_headless_resume_argv`` regardless of its exact parameter list.

    The helper's signature is resolved at runtime and each parameter is bound
    by a substring heuristic on its name, so the oracle keeps working whether
    the implementation is ``(cmd, agent)``, ``(cmd, agent, config)``,
    ``(argv, agent, work_dir)``, etc.
    """
    func = orch._headless_resume_argv
    sig = inspect.signature(func)
    kwargs = {}
    for name, param in sig.parameters.items():
        if param.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        ln = name.lower()
        if 'cmd' in ln or 'argv' in ln or 'command' in ln:
            value = list(cmd)
        elif 'agent' in ln:
            value = agent
        elif 'cfg' in ln or 'config' in ln:
            value = config if config is not None else {}
        elif 'round' in ln:
            value = 1
        elif any((tok in ln for tok in ('dir', 'cwd', 'work', 'project', 'path', 'slug', 'root', 'home'))):
            value = work_dir
        else:
            if param.default is not inspect.Parameter.empty:
                continue
            value = None
        kwargs[name] = value
    return func(**kwargs)

def _scoped_exists(present):
    """os.path.exists stub: forces ``present`` only for config/projects paths."""
    real = os.path.exists

    def _exists(path):
        s = str(path)
        if '.claude' in s or 'projects' in s:
            return bool(present)
        return real(path)
    return _exists

def _scoped_listdir(entries):
    """os.listdir stub: returns ``entries`` only for config/projects paths."""
    real = os.listdir

    def _listdir(path):
        s = str(path)
        if '.claude' in s or 'projects' in s:
            return list(entries)
        return real(path)
    return _listdir

def _setup_env(monkeypatch, tmp_path, config, transcript_present):
    """Wire env, real temp dirs, and the load_config/exists/listdir stubs.

    Sets up both a real ``~/.claude/projects`` tree (for a pathlib-based
    implementation) and consistent ``os.path.exists`` / ``os.listdir`` stubs
    (for an os-based implementation), so the oracle exercises the helper's
    real transcript-presence branch either way.
    """
    config_dir = tmp_path / '.claude'
    projects = config_dir / 'projects'
    projects.mkdir(parents=True, exist_ok=True)
    if transcript_present:
        proj = projects / '-tmp-jm-work'
        proj.mkdir(parents=True, exist_ok=True)
        (proj / 'session-abc123.jsonl').write_text('{"type":"user"}\n')
        entries = ['session-abc123.jsonl']
    else:
        entries = []
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(config_dir))
    monkeypatch.setattr(orch, 'load_config', lambda *a, **k: config, raising=False)
    monkeypatch.setattr(orch.os.path, 'exists', _scoped_exists(transcript_present))
    monkeypatch.setattr(orch.os, 'listdir', _scoped_listdir(entries))

def test_headless_resume_fires_when_all_predicates_hold(monkeypatch, tmp_path):
    """All 4 predicates true -> argv gains --continue, keeps -p and prompt."""
    config = _make_config(resume=True, pin_cwd=True, backend='headless')
    _setup_env(monkeypatch, tmp_path, config, transcript_present=True)
    cmd = _base_cmd('solve the staged task')
    result = _invoke(cmd, agent='claude', config=config)
    assert '--continue' in result, 'warm resume must inject --continue'
    assert '-p' in result, 'headless -p flag must be preserved'
    assert 'solve the staged task' in result, 'prompt must be preserved'

def test_headless_resume_does_not_fire_when_resume_flag_off(monkeypatch, tmp_path):
    """Resume flag OFF -> cold start, --continue NOT added."""
    config = _make_config(resume=False, pin_cwd=True, backend='headless')
    _setup_env(monkeypatch, tmp_path, config, transcript_present=True)
    result = _invoke(_base_cmd(), agent='claude', config=config)
    assert '--continue' not in result

def test_headless_resume_does_not_fire_when_pin_cwd_flag_off(monkeypatch, tmp_path):
    """pin-cwd flag OFF -> transcript path is non-deterministic, no --continue."""
    config = _make_config(resume=True, pin_cwd=False, backend='headless')
    _setup_env(monkeypatch, tmp_path, config, transcript_present=True)
    result = _invoke(_base_cmd(), agent='claude', config=config)
    assert '--continue' not in result

def test_headless_resume_does_not_fire_when_transcript_absent(monkeypatch, tmp_path):
    """No prior transcript -> fresh-task safety, --continue NOT added."""
    config = _make_config(resume=True, pin_cwd=True, backend='headless')
    _setup_env(monkeypatch, tmp_path, config, transcript_present=False)
    result = _invoke(_base_cmd(), agent='claude', config=config)
    assert '--continue' not in result

def test_headless_resume_does_not_fire_for_tmux_backend(monkeypatch, tmp_path):
    """tmux backend -> helper is a no-op (continue handled by the tmux path)."""
    config = _make_config(resume=True, pin_cwd=True, backend='tmux')
    _setup_env(monkeypatch, tmp_path, config, transcript_present=True)
    cmd = _base_cmd()
    result = _invoke(cmd, agent='claude', config=config)
    helper_is_noop = '--continue' not in result
    src = inspect.getsource(orch.spawn_agent)
    tmux_dispatch_precedes_resume = '_use_tmux_claude' in src and '_headless_resume_argv' in src and (src.index('_use_tmux_claude') < src.index('_headless_resume_argv'))
    assert helper_is_noop or tmux_dispatch_precedes_resume, 'tmux backend must not gain a headless --continue'

def test_headless_resume_does_not_fire_for_non_claude_agent(monkeypatch, tmp_path):
    """Non-claude agents never get the headless claude --continue flag."""
    config = _make_config(resume=True, pin_cwd=True, backend='headless')
    _setup_env(monkeypatch, tmp_path, config, transcript_present=True)
    result = _invoke(_base_cmd(), agent='gemini', config=config)
    assert '--continue' not in result

def test_headless_resume_argv_is_idempotent(monkeypatch, tmp_path):
    """If --continue is already present it is not duplicated."""
    config = _make_config(resume=True, pin_cwd=True, backend='headless')
    _setup_env(monkeypatch, tmp_path, config, transcript_present=True)
    cmd = _base_cmd() + ['--continue']
    result = _invoke(cmd, agent='claude', config=config)
    assert result.count('--continue') == 1

def test_headless_resume_argv_is_fail_safe_on_exception(monkeypatch, tmp_path):
    """Any internal error -> return the argv unchanged, never raise."""
    config = _make_config(resume=True, pin_cwd=True, backend='headless')
    config_dir = tmp_path / '.claude'
    (config_dir / 'projects').mkdir(parents=True, exist_ok=True)
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('CLAUDE_CONFIG_DIR', str(config_dir))

    def _boom(*a, **k):
        raise OSError('simulated config/transcript failure')
    monkeypatch.setattr(orch, 'load_config', _boom, raising=False)
    real_exists = os.path.exists
    real_listdir = os.listdir

    def _exists(path):
        s = str(path)
        if '.claude' in s or 'projects' in s:
            raise OSError('boom')
        return real_exists(path)

    def _listdir(path):
        s = str(path)
        if '.claude' in s or 'projects' in s:
            raise OSError('boom')
        return real_listdir(path)
    monkeypatch.setattr(orch.os.path, 'exists', _exists)
    monkeypatch.setattr(orch.os, 'listdir', _listdir)
    cmd = _base_cmd()
    try:
        result = _invoke(cmd, agent='claude', config=config)
    except Exception as exc:
        pytest.fail(f'_headless_resume_argv must be fail-safe, raised: {exc!r}')
    assert '--continue' not in result, 'fail-safe must default to cold start'

def test_spawn_agent_source_code_wiring_and_helper_guards():
    """spawn_agent wires the helper; the helper guards the 4 predicates."""
    spawn_src = inspect.getsource(orch.spawn_agent)
    assert '_headless_resume_argv' in spawn_src, 'spawn_agent must call _headless_resume_argv'
    helper_src = inspect.getsource(orch._headless_resume_argv)
    lowered = helper_src.lower()
    predicates = {'resume_flag': ('headless_resume', 'headless_continue', 'resume'), 'pin_cwd_flag': ('pin_task_cwd', 'pin_cwd'), 'prior_transcript': ('listdir', 'exists', 'glob', 'iterdir', 'jsonl', 'projects', 'transcript'), 'claude_agent': ('claude',)}
    assert len(predicates) == 4
    for predicate, needles in predicates.items():
        assert any((n in lowered for n in needles)), f'_headless_resume_argv must reference predicate {predicate!r}'
    assert '--continue' in helper_src, '_headless_resume_argv must reference the --continue flag it injects'

def test_regression_tmux_backend_behavior_remains_byte_identical(monkeypatch, tmp_path):
    """The tmux argv must be returned byte-identical by the resume helper."""
    config = _make_config(resume=True, pin_cwd=True, backend='tmux')
    _setup_env(monkeypatch, tmp_path, config, transcript_present=True)
    cmd = _base_cmd()
    original = list(cmd)
    result = _invoke(cmd, agent='claude', config=config)
    src = inspect.getsource(orch.spawn_agent)
    tmux_dispatch_precedes_resume = '_use_tmux_claude' in src and '_headless_resume_argv' in src and (src.index('_use_tmux_claude') < src.index('_headless_resume_argv'))
    assert list(result) == original or tmux_dispatch_precedes_resume

def test_regression_no_unapproved_or_manifest_files_created(monkeypatch, tmp_path):
    """The resume helper is pure argv work and must not write any files."""
    work = tmp_path / 'cwd'
    work.mkdir()
    monkeypatch.chdir(work)
    config = _make_config(resume=True, pin_cwd=True, backend='headless')
    _setup_env(monkeypatch, tmp_path, config, transcript_present=True)
    before = set(os.listdir(work))
    _invoke(_base_cmd(), agent='claude', config=config)
    after = set(os.listdir(work))
    assert before == after, 'helper must not create files in the cwd'
    assert not any(('manifest' in f.lower() or 'patch' in f.lower() for f in after)), 'no manifest/patch artefacts may be created'