"""RED oracle — authoritative contract for the ac-js-jail-mount leaf
(harness/agent_jail.py::build_jail_argv — Phase D, OWNER HAND-EDIT, irreducible tier).

Contract: a NEW keyword-only parameter ``js_node_bin_dir: str | Path | None =
None`` on ``build_jail_argv``. Behavior:

- ``None`` (every existing caller): byte-identical argv — the whole ``~/.nvm``
  tree keeps its single ``--ro-bind`` exactly as today.
- Pinned (the JS execute path): the ``~/.nvm`` WHOLE-TREE bind is REPLACED by
  a ``--ro-bind`` of ONLY the pinned ``.../versions/node/<v>/bin`` dir — the
  jail never exposes the full version-manager installation to a JS candidate.
- FAIL-CLOSED: a pin that does not resolve to a real directory STRICTLY under
  ``<home>/.nvm`` binds NOTHING nvm-related (no node rather than the whole
  tree).
- The execute-path namespace policy is untouched: ``--unshare-net`` and
  ``--unshare-ipc`` stay present when ``bind_credentials=False``.
"""
import shutil

import pytest

from harness.agent_jail import build_jail_argv

pytestmark = pytest.mark.skipif(shutil.which('bwrap') is None,
                                reason='bwrap unavailable')


def _mk_home(tmp_path):
    home = tmp_path / 'home'
    bin_dir = home / '.nvm' / 'versions' / 'node' / 'v22.17.0' / 'bin'
    bin_dir.mkdir(parents=True)
    (bin_dir / 'node').write_text('#!/bin/sh\n')
    return home, bin_dir


def _argv(tmp_path, home, **kw):
    for sub in ('repo', 'work', 'state'):
        (tmp_path / sub).mkdir(exist_ok=True)
    return build_jail_argv(['true'], repo_root=str(tmp_path / 'repo'),
                           work_dir=str(tmp_path / 'work'),
                           state_dir=str(tmp_path / 'state'),
                           home=str(home), bind_credentials=False, **kw)


def _ro_bind_targets(argv):
    return {argv[i + 1] for i, a in enumerate(argv) if a == '--ro-bind'}


def test_default_keeps_whole_nvm_robind(tmp_path):
    home, _ = _mk_home(tmp_path)
    argv = _argv(tmp_path, home)
    assert str((home / '.nvm').resolve()) in _ro_bind_targets(argv)


def test_default_kwarg_is_byte_identical(tmp_path):
    home, _ = _mk_home(tmp_path)
    assert _argv(tmp_path, home) == _argv(tmp_path, home, js_node_bin_dir=None)


def test_pinned_binds_only_node_bin_dir(tmp_path):
    home, bin_dir = _mk_home(tmp_path)
    argv = _argv(tmp_path, home, js_node_bin_dir=str(bin_dir))
    targets = _ro_bind_targets(argv)
    assert str(bin_dir.resolve()) in targets, 'pinned node bin dir must be ro-bound'
    assert str((home / '.nvm').resolve()) not in targets, \
        'the whole ~/.nvm tree must NOT be bound on the pinned JS execute path'


def test_escaping_pin_binds_nothing_nvm(tmp_path):
    # Edge case: a pin outside <home>/.nvm fails CLOSED — no node, not the tree.
    home, _ = _mk_home(tmp_path)
    evil = tmp_path / 'evil-bin'
    evil.mkdir()
    argv = _argv(tmp_path, home, js_node_bin_dir=str(evil))
    targets = _ro_bind_targets(argv)
    assert str(evil.resolve()) not in targets
    assert str((home / '.nvm').resolve()) not in targets
    assert not any('.nvm' in t for t in targets)


def test_missing_pin_dir_binds_nothing_nvm(tmp_path):
    # Edge case: a pin under .nvm that does not exist binds nothing nvm-related.
    home, _ = _mk_home(tmp_path)
    ghost = home / '.nvm' / 'versions' / 'node' / 'v99.0.0' / 'bin'
    argv = _argv(tmp_path, home, js_node_bin_dir=str(ghost))
    assert not any('.nvm' in t for t in _ro_bind_targets(argv))


def test_execute_path_namespace_policy_preserved(tmp_path):
    home, bin_dir = _mk_home(tmp_path)
    argv = _argv(tmp_path, home, js_node_bin_dir=str(bin_dir))
    assert '--unshare-net' in argv and '--unshare-ipc' in argv
