"""RED test oracle for the agent-jail slot-HOME credential re-carve.

Module under test: ``harness.agent_jail`` -- specifically
:func:`harness.agent_jail.build_jail_argv`.

The defect this oracle pins: the writable HOME credential subdir binds
(``~/.gemini`` / ``~/.claude``, emitted with ``--bind``) are appended to the
argv BEFORE the load-bearing ``--ro-bind <repo_root>``. bubblewrap applies
binds in order and a later bind over an overlapping path wins, so when the
slot ``home`` lives strictly UNDER ``repo_root`` the repo ro-bind silently
re-mounts those credential subtrees read-only -- the jailed agent can no
longer refresh OAuth / write cached state. The fix must RE-CARVE the slot's
credential subdirs (a fresh ``--bind``) AFTER the repo ro-bind so the
read-write surface wins again. For the operator ``$HOME`` (which is not under
``repo_root``) nothing changes -- the argv stays byte-identical.
"""
from __future__ import annotations
import inspect
import os
from pathlib import Path
import pytest
from harness import agent_jail

def _flag_indices(argv: list[str], flag: str, src: str) -> list[int]:
    """Indices i where argv[i:i+3] == [flag, src, src] (a self-bind of src)."""
    return [i for i in range(len(argv) - 2) if argv[i] == flag and argv[i + 1] == src and (argv[i + 2] == src)]

@pytest.fixture
def jail_env(tmp_path, monkeypatch):
    """A repo_root / state_dir / work_dir scaffold with bwrap stubbed present.

    build_jail_argv() fail-closes (FileNotFoundError) when ``bwrap`` is not on
    PATH, so we redirect the module's ``shutil.which`` to a stub. Operator HOME
    is pinned OUTSIDE repo_root so the no-home / operator-home calls do not
    trigger the re-carve.
    """
    monkeypatch.setattr(agent_jail.shutil, 'which', lambda name: '/usr/bin/bwrap' if name == 'bwrap' else None)
    repo_root = tmp_path / 'repo'
    state_dir = repo_root / 'state'
    work_dir = tmp_path / 'work'
    op_home = tmp_path / 'operator_home'
    for d in (repo_root, state_dir, work_dir, op_home):
        d.mkdir(parents=True, exist_ok=True)
    for sub in ('.nvm', '.gemini', '.claude'):
        (op_home / sub).mkdir()
    monkeypatch.setenv('HOME', str(op_home))
    return {'cmd': ['claude', '--print'], 'repo_root': repo_root, 'state_dir': state_dir, 'work_dir': work_dir, 'op_home': op_home}

def _slot_home_under_repo(jail_env):
    """Create a slot home strictly UNDER repo_root with credential subdirs."""
    home = jail_env['repo_root'] / 'agent_home'
    home.mkdir()
    for sub in ('.nvm', '.gemini', '.claude'):
        (home / sub).mkdir()
    return home

def _build(jail_env, **kw):
    return agent_jail.build_jail_argv(jail_env['cmd'], repo_root=jail_env['repo_root'], work_dir=jail_env['work_dir'], state_dir=jail_env['state_dir'], **kw)

def test_signature_accepted_home_parameter(jail_env):
    """build_jail_argv must still accept a keyword ``home`` parameter."""
    params = inspect.signature(agent_jail.build_jail_argv).parameters
    assert 'home' in params, "build_jail_argv lost its 'home' parameter"
    argv = _build(jail_env, home=jail_env['op_home'])
    assert isinstance(argv, list) and argv[0] == '/usr/bin/bwrap'

def test_operator_home_byte_identical_to_head(jail_env):
    """home == operator $HOME (outside repo_root) is byte-identical to no-home."""
    argv_with_home = _build(jail_env, home=os.environ['HOME'])
    argv_no_home = _build(jail_env)
    assert argv_with_home == argv_no_home

def test_slot_home_recarves_credentials_after_repo_ro_bind(jail_env):
    """A slot home under repo_root must re-carve ~/.gemini AFTER the repo ro-bind."""
    home = _slot_home_under_repo(jail_env)
    argv = _build(jail_env, home=home)
    repo_r = str(Path(jail_env['repo_root']).resolve())
    gemini = os.path.join(str(Path(home).resolve()), '.gemini')
    repo_ro = _flag_indices(argv, '--ro-bind', repo_r)
    gemini_rw = _flag_indices(argv, '--bind', gemini)
    assert repo_ro, 'repo_root must be --ro-bind mounted'
    assert gemini_rw, 'slot ~/.gemini must be --bind (read-write) mounted'
    assert max(gemini_rw) > repo_ro[0], 'slot ~/.gemini read-write bind must come AFTER the repo_root ro-bind (otherwise the repo ro-bind re-mounts the credential dir read-only)'

def test_regression_nvm_stays_ro(jail_env):
    """~/.nvm is a read-only runtime: it must never be emitted as a rw --bind."""
    home = _slot_home_under_repo(jail_env)
    argv = _build(jail_env, home=home)
    nvm = os.path.join(str(Path(home).resolve()), '.nvm')
    assert _flag_indices(argv, '--ro-bind', nvm), '~/.nvm must be ro-bound'
    assert not _flag_indices(argv, '--bind', nvm), '~/.nvm must never be re-carved read-write'

def test_regression_bind_credentials_false_skips_recarve(jail_env):
    """Execute path (bind_credentials=False) drops creds: no ~/.gemini bind at all."""
    home = _slot_home_under_repo(jail_env)
    argv = _build(jail_env, home=home, bind_credentials=False)
    home_r = str(Path(home).resolve())
    gemini = os.path.join(home_r, '.gemini')
    claude = os.path.join(home_r, '.claude')
    assert not _flag_indices(argv, '--bind', gemini)
    assert not _flag_indices(argv, '--ro-bind', gemini)
    assert not _flag_indices(argv, '--bind', claude)
    assert '--unshare-net' in argv