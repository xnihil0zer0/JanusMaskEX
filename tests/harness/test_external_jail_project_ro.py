"""RED oracle for NGv2 external-build BUG #1: jail T_RETARGET drops PROJECT_ROOT.

For an EXTERNAL task (``JANUSMASK_WORKING_DIR`` set, not self) ``spawn_agent``
retargets the jail ``repo_root`` onto the external tree, and
``agent_jail.build_jail_argv`` then ro-binds only that external ``repo_root`` +
``_SYSTEM_RO`` + HOME subdirs. But the vendored claude binary lives at
``${PROJECT_ROOT}/.agents/claude-code/node_modules/.bin/claude`` and the hooks
run ``python3 -m harness.hooks.*`` -- BOTH under the JM repo, which is NOT bound
when ``repo_root`` is external. The agent then dies silently
(``bwrap: execvp ...claude: No such file or directory``).

Fix: a top-level helper ``orchestrator._external_jail_extra_ro(jail_repo_root)``
returns ``[str(PROJECT_DIR)]`` when the jail repo_root is external (resolves to
something other than the JM PROJECT_DIR) and ``[]`` for a self build; spawn_agent
passes its result as ``extra_ro=`` to the synthesis ``build_jail_argv`` call so
the vendored binary + harness package are ro-bound inside an external jail.
"""
import os
import shutil

import pytest

from harness.paths import PROJECT_ROOT


def test_helper_returns_project_dir_for_external_repo_root(tmp_path):
    from harness.orchestrator import _external_jail_extra_ro
    ext = tmp_path / 'NobleGreedv2'
    ext.mkdir()
    out = _external_jail_extra_ro(str(ext))
    assert out == [str(PROJECT_ROOT)]


def test_helper_returns_empty_for_self_repo_root():
    from harness.orchestrator import _external_jail_extra_ro
    # The JM project dir itself (self build) must NOT add an extra ro-bind --
    # build_jail_argv already ro-binds repo_root==PROJECT_ROOT directly.
    assert _external_jail_extra_ro(str(PROJECT_ROOT)) == []
    # A path that resolves to PROJECT_ROOT (e.g. with a trailing slash) is self too.
    assert _external_jail_extra_ro(str(PROJECT_ROOT) + os.sep) == []


@pytest.mark.skipif(shutil.which('bwrap') is None, reason='bwrap not on PATH')
def test_external_jail_argv_ro_binds_project_dir(tmp_path):
    """End-to-end: feeding the helper output into build_jail_argv ro-binds PROJECT_ROOT."""
    from harness import agent_jail
    from harness.orchestrator import _external_jail_extra_ro
    ext = tmp_path / 'ext_repo'
    ext.mkdir()
    work = tmp_path / 'work'
    work.mkdir()
    state = tmp_path / 'state'
    state.mkdir()
    argv = agent_jail.build_jail_argv(
        ['true'],
        repo_root=str(ext),
        work_dir=str(work),
        state_dir=str(state),
        extra_ro=_external_jail_extra_ro(str(ext)),
    )
    # The vendored-binary/harness root must be ro-bound as a `--ro-bind P P` pair.
    pr = str(PROJECT_ROOT)
    pairs = [(argv[i + 1], argv[i + 2]) for i, a in enumerate(argv[:-2]) if a == '--ro-bind']
    assert (pr, pr) in pairs
