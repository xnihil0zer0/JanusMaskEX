"""RED oracle — authoritative contract for autocompiler/js/js_fork_policy.py (leaf ac-js-fork-policy).

Contract: the PURE spawn-policy descriptor for the JS runner — data only, no
process is ever created here (the spawn itself is injected at the js_sandbox
seam and, at runtime, routed through the bwrap agent jail; the seccomp fuzz
sandbox blocks execve/fork by design). Exposes:

``fork_spec(node_bin, runner_path, batch_file, timeout_ms=5000) -> dict`` with
EXACTLY these keys:

- ``argv``: ``[node_bin, runner_path, batch_file]`` (all str, order pinned)
- ``start_new_session``: ``True`` — the child gets its OWN process group so a
  hung runner can be reaped wholesale
- ``result_fd``: ``3`` — results channel (stdout belongs to candidate noise)
- ``timeout_ms``: the positive int budget
- ``kill``: ``{'signal': 'SIGKILL', 'scope': 'process_group'}`` — on timeout
  the WHOLE group is SIGKILLed (no graceful-but-ignorable TERM-only plan)

Invalid inputs (empty/non-str path parts, non-positive/non-int timeout) raise
``ValueError`` — a malformed spawn plan must never silently launch.
"""
import inspect

import pytest

import autocompiler.js.js_fork_policy as policy_mod
from autocompiler.js.js_fork_policy import fork_spec


def test_spec_shape_is_exact():
    spec = fork_spec('/nvm/versions/node/v22.17.0/bin/node',
                     '/repo/autocompiler/js/js_runner.js',
                     '/tmp/batch.json', timeout_ms=2000)
    assert set(spec) == {'argv', 'start_new_session', 'result_fd', 'timeout_ms', 'kill'}
    assert spec['argv'] == ['/nvm/versions/node/v22.17.0/bin/node',
                            '/repo/autocompiler/js/js_runner.js',
                            '/tmp/batch.json']
    assert spec['start_new_session'] is True
    assert spec['result_fd'] == 3
    assert spec['timeout_ms'] == 2000
    assert spec['kill'] == {'signal': 'SIGKILL', 'scope': 'process_group'}


def test_default_timeout_positive():
    spec = fork_spec('/n', '/r.js', '/b.json')
    assert isinstance(spec['timeout_ms'], int) and spec['timeout_ms'] > 0


def test_empty_path_parts_rejected():
    # Edge case: a blank argv element must never silently launch.
    with pytest.raises(ValueError):
        fork_spec('', '/r.js', '/b.json')
    with pytest.raises(ValueError):
        fork_spec('/n', '', '/b.json')
    with pytest.raises(ValueError):
        fork_spec('/n', '/r.js', '')


def test_non_str_paths_rejected():
    with pytest.raises(ValueError):
        fork_spec(None, '/r.js', '/b.json')
    with pytest.raises(ValueError):
        fork_spec('/n', 42, '/b.json')


def test_bad_timeout_rejected():
    # Edge case: zero/negative/bool timeouts are invalid plans.
    for bad in (0, -1, True, 'soon', 1.5):
        with pytest.raises(ValueError):
            fork_spec('/n', '/r.js', '/b.json', timeout_ms=bad)


def test_module_is_pure_no_spawn():
    src = inspect.getsource(policy_mod)
    for forbidden in ('subprocess', 'Popen', 'os.fork', 'os.spawn', 'os.exec'):
        assert forbidden not in src, f'fork policy must not reference {forbidden}'
