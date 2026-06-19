"""RED test oracle for spawn_agent HOME argument threading.

This is a source/AST verification oracle (a verification test file), NOT an
implementation module. It asserts that ``harness.orchestrator.spawn_agent``
threads the host ``HOME`` into its ``agent_jail.build_jail_argv`` call, i.e.
that the call carries a ``home=env.get('HOME')`` (or ``home=env['HOME']``)
keyword argument.

On the unpatched HEAD the ``build_jail_argv`` call inside ``spawn_agent`` has
no ``home=`` keyword, so ``test_spawn_agent_source_contains_home_in_build_jail_argv``
FAILS (this is the RED state). Once the fix threads ``home=env.get('HOME')``
into that call, the oracle goes GREEN.

No agent CLI process is ever spawned: every test operates purely on the
function's *source* via ``inspect.getsource`` / ``ast``, and
``test_spawn_agent_no_live_spawn`` installs a fail-closed guard over
``subprocess.Popen`` / the tmux backend to prove it.
"""
from __future__ import annotations
import ast
import inspect
import textwrap
import pytest
import harness.orchestrator as orchestrator
_EXPECTED_PARAMS = ('agent', 'prompt', 'config', 'round_number')

def _spawn_agent_source() -> str:
    """Return the dedented source of harness.orchestrator.spawn_agent."""
    src = inspect.getsource(orchestrator.spawn_agent)
    return textwrap.dedent(src)

def _spawn_agent_funcdef() -> ast.FunctionDef:
    """Parse spawn_agent's source and return its FunctionDef node."""
    tree = ast.parse(_spawn_agent_source())
    funcdefs = [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == 'spawn_agent']
    assert funcdefs, 'spawn_agent FunctionDef not found in parsed source'
    return funcdefs[0]

def _build_jail_argv_calls(funcdef: ast.FunctionDef) -> list[ast.Call]:
    """All Call nodes targeting build_jail_argv within the given function."""
    calls: list[ast.Call] = []
    for node in ast.walk(funcdef):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = None
        if isinstance(func, ast.Attribute):
            name = func.attr
        elif isinstance(func, ast.Name):
            name = func.id
        if name == 'build_jail_argv':
            calls.append(node)
    return calls

def _home_keyword(call: ast.Call) -> ast.keyword | None:
    """Return the ``home=`` keyword of a Call, or None if absent."""
    for kw in call.keywords:
        if kw.arg == 'home':
            return kw
    return None

def test_spawn_agent_source_contains_home_in_build_jail_argv():
    """RED oracle: build_jail_argv must be called with home=env's HOME.

    Fails on the unpatched codebase (no ``home=`` keyword on the call) and
    passes once the fix threads ``home=env.get('HOME')`` / ``home=env['HOME']``.
    """
    funcdef = _spawn_agent_funcdef()
    calls = _build_jail_argv_calls(funcdef)
    assert calls, 'expected a build_jail_argv call inside spawn_agent'
    home_calls = []
    for call in calls:
        kw = _home_keyword(call)
        if kw is None:
            continue
        value_src = ast.unparse(kw.value)
        if 'HOME' in value_src and 'env' in value_src:
            home_calls.append(value_src)
    assert home_calls, "spawn_agent must pass home=env.get('HOME') (or home=env['HOME']) into build_jail_argv; no such keyword found. build_jail_argv keyword args seen: " + repr([sorted((k.arg for k in c.keywords if k.arg)) for c in calls])
    assert any(("get('HOME')" in v or 'get("HOME")' in v or "['HOME']" in v or ('["HOME"]' in v) for v in home_calls)), f'home= keyword present but does not read env HOME: {home_calls!r}'

def test_spawn_agent_signature_preserved():
    """The public signature of spawn_agent must be unchanged by the fix."""
    sig = inspect.signature(orchestrator.spawn_agent)
    assert tuple(sig.parameters) == _EXPECTED_PARAMS, f'spawn_agent signature changed: got {tuple(sig.parameters)!r}, expected {_EXPECTED_PARAMS!r}'
    assert sig.parameters['round_number'].default == 1
    for required in ('agent', 'prompt', 'config'):
        assert sig.parameters[required].default is inspect.Parameter.empty, f'parameter {required!r} unexpectedly gained a default'

def test_spawn_agent_no_live_spawn(monkeypatch):
    """Safety control: inspecting the oracle must spawn no real process.

    Installs a fail-closed guard over every live-spawn entrypoint reachable
    from spawn_agent (``subprocess.Popen`` and the tmux backend). monkeypatch
    tears the guard down automatically. The guard must remain untriggered,
    proving the oracle is purely source-based.
    """
    spawned: list[str] = []

    def _no_popen(*args, **kwargs):
        spawned.append('subprocess.Popen')
        raise AssertionError('live agent spawn attempted during test execution')
    monkeypatch.setattr(orchestrator.subprocess, 'Popen', _no_popen, raising=True)
    try:
        import harness.tmux_worker as tmux_worker
    except Exception:
        tmux_worker = None
    if tmux_worker is not None and hasattr(tmux_worker, 'spawn_claude_tmux'):

        def _no_tmux(*args, **kwargs):
            spawned.append('spawn_claude_tmux')
            raise AssertionError('live tmux agent spawn attempted during test')
        monkeypatch.setattr(tmux_worker, 'spawn_claude_tmux', _no_tmux, raising=True)
    src = _spawn_agent_source()
    assert 'build_jail_argv' in src
    assert spawned == [], f'unexpected live spawn(s): {spawned!r}'

def test_spawn_agent_ast_validity():
    """spawn_agent's source must parse to a single well-formed FunctionDef."""
    funcdef = _spawn_agent_funcdef()
    assert isinstance(funcdef, ast.FunctionDef)
    assert funcdef.name == 'spawn_agent'
    ast.parse(_spawn_agent_source())

def test_regression_no_unrelated_changes():
    """The fix must ADD home= without dropping the existing keyword args.

    Guards against a regression where threading HOME accidentally removes the
    repo_root / work_dir / state_dir wiring the jail depends on.
    """
    funcdef = _spawn_agent_funcdef()
    calls = _build_jail_argv_calls(funcdef)
    assert len(calls) == 1, 'expected exactly one build_jail_argv call in spawn_agent'
    kw_names = {kw.arg for kw in calls[0].keywords if kw.arg}
    for required in ('repo_root', 'work_dir', 'state_dir'):
        assert required in kw_names, f'build_jail_argv lost required keyword {required!r}; present keywords: {sorted(kw_names)!r}'
    assert calls[0].args, 'build_jail_argv lost its positional command argv'

def test_regression_only_one_build_jail_argv():
    """spawn_agent must contain exactly one build_jail_argv call.

    The fix threads HOME into the *existing* call rather than introducing a
    second jail-build code path.
    """
    funcdef = _spawn_agent_funcdef()
    calls = _build_jail_argv_calls(funcdef)
    assert len(calls) == 1, f'expected exactly one build_jail_argv call inside spawn_agent, found {len(calls)}'
if __name__ == '__main__':
    raise SystemExit(pytest.main([__file__, '-q']))