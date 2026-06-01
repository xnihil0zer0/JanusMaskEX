"""Phase-A jail write-DENIAL regression test.

This module is a verification oracle (a pytest test file) for the REAL bwrap
jail that already exists in this repository.  It proves that a self-heal agent
spawned through the jail pipeline

    harness.autowork_daemon._escalate_to_autobrief
        -> harness.autowork_daemon._contain_selfheal
            -> harness.agent_jail.build_jail_argv

is sandboxed so that it CANNOT write the protected tree (the repo ``harness/**``
sources, ``state/control/**``, ``~/.claude/.../memory/*.md`` and it cannot
commit to the read-only git repo) while it CAN write its per-spawn ``work_dir``
and ``state/sessions/``.

NON-VACUITY (load bearing).  ``_escalate_to_autobrief`` resolves the sandbox
gate from ``pathlib.Path('harness/config.yaml')`` relative to the process CWD
and gates the jail on ``agent_sandbox.bwrap``.  The declared mutant flips that
flag ``true -> false`` in the staging copy of ``harness/config.yaml`` and runs
this test with the CWD already at the staging root, so when the gate is false
``_contain_selfheal`` skips ``build_jail_argv`` and the captured spawn argv is
the raw, UNJAILED command.  Every probe here therefore first asserts that the
captured argv is genuinely ``bwrap``-wrapped (``argv[0]`` endswith ``bwrap`` and
the tmp repo appears as a ``--ro-bind`` pair); that assertion fails under the
mutant, and the real-subprocess denial probes built from the captured argv fail
too.  We deliberately let the gate value flow from the CWD-relative
``harness/config.yaml`` (we do NOT inject a tmp config hardcoding
``bwrap: true``) so the mutant stays coupled to the test, while HOME / state /
work_dir / PROJECT_ROOT topology is redirected to tmp fixtures so the probes
never touch the operator's real tree.

All rationale lives in docstrings because ``#`` comments are stripped during
pipeline processing.
"""
from __future__ import annotations
import json
import shutil
import subprocess
from pathlib import Path
import pytest
import harness.agent_jail as aj
import harness.autowork_daemon as dae
import harness.orchestrator as orch
import harness.paths
requires_bwrap = pytest.mark.skipif(shutil.which('bwrap') is None, reason='bwrap not installed')

def _pairs(argv, flag):
    """Return the (src, dst) operand pairs for ``flag`` in a bwrap argv.

    Mirrors the ``_pairs`` helper in tests/adversarial/test_agent_jail.py: for
    every token equal to ``flag`` the following two tokens are its source and
    destination operands.
    """
    out = []
    for i, tok in enumerate(argv):
        if tok == flag and i + 2 < len(argv):
            out.append((argv[i + 1], argv[i + 2]))
    return out

def _assert_bwrap_argv(argv, repo_root):
    """Assert the captured spawn argv is a real bwrap-wrapped jail argv.

    This is the non-vacuity anchor: under the bwrap-flip mutant
    ``_contain_selfheal`` returns the raw claude command and these assertions
    fail (``argv[0]`` is not ``bwrap`` and the tmp repo is not ``--ro-bind``ed).
    """
    assert argv, 'no spawn argv was captured from Popen'
    assert str(argv[0]).endswith('bwrap'), 'captured spawn argv is not bwrap-wrapped -- agent_sandbox.bwrap must be true for the jail to be applied (mutant flips it false)'
    pairs = _pairs(argv, '--ro-bind')
    assert any((src == str(repo_root) for src, _dst in pairs)), 'the tmp repo_root is not --ro-bind mounted in the captured jail argv'
    assert any((tok == '--' for tok in argv)), "the captured jail argv has no '--' command separator"

def _inner_split(argv):
    """Index of the final ``--`` separator that precedes the inner command."""
    return max((i for i, tok in enumerate(argv) if tok == '--'))

def _run_probe(argv, repo_root, shell_cmd):
    """Run a REAL host bwrap subprocess using the captured jail topology.

    The captured jail argv is reused verbatim up to and including its final
    ``--`` separator, then the inner command is replaced with a ``/bin/sh -c``
    invocation that attempts ``shell_cmd``.  This exercises the genuine kernel
    write-denial of the jail (the probe is a real host ``subprocess.run`` of the
    captured bwrap argv, not a topology-only or config-flag-only check).
    """
    _assert_bwrap_argv(argv, repo_root)
    sep = _inner_split(argv)
    probe = list(argv[:sep + 1]) + ['/bin/sh', '-c', shell_cmd]
    return subprocess.run(probe, capture_output=True, text=True, timeout=120)

class _Ctx:
    """Plain attribute bag holding the captured jail run + tmp topology."""

@pytest.fixture
def ctx(tmp_path, monkeypatch):
    """Build a tmp repo/state/home topology, drive the REAL escalation once.

    The fixture:

    * lays out a tmp repo (with ``harness/`` sources), a tmp state dir (with
      ``control/``, ``sessions/`` and ``planning/sessions/`` and a populated
      ``tasks/blocked/<id>.json``), a tmp HOME (with a ``~/.claude/.../memory``
      note) and a tmp config dir holding the post-rewire claude settings file
      that declares ``hooks.PreToolUse`` so the real assertion passes;
    * monkeypatches ``harness.paths.PROJECT_ROOT_STR`` / ``CONFIG_DIR_STR`` /
      ``HARNESS_DIR_STR`` and the ``harness.paths.agent_work_dir`` CALLABLE (the
      real signature ``(agent, session_slug) -> Path``) plus ``HOME`` so the
      in-function imports inside ``_contain_selfheal`` / ``_escalate_to_autobrief``
      resolve to the tmp tree;
    * installs a DELEGATING SPY over ``harness.orchestrator._assert_claude_hook_config``
      (records the call, then calls the real function) -- never a no-op stub;
    * captures the spawn argv by replacing ``harness.autowork_daemon.subprocess.Popen``
      with a fake that records cmd/env/cwd;
    * runs the REAL ``_escalate_to_autobrief`` so the real machinery builds the
      jailed cmd, then ``monkeypatch.undo()`` restores the real Popen (and the
      paths/HOME) BEFORE any host denial probe runs.

    The ``agent_sandbox.bwrap`` gate value is intentionally NOT supplied by the
    fixture: ``_escalate_to_autobrief`` reads it from the CWD-relative
    ``harness/config.yaml`` so the staging mutant stays coupled.
    """
    repo_root = tmp_path / 'repo'
    state_dir = tmp_path / 'state'
    home = tmp_path / 'home'
    config_dir = tmp_path / 'config'
    work_base = tmp_path / 'agentwork'
    (repo_root / 'harness').mkdir(parents=True)
    for sub in ('sessions', 'planning/sessions', 'control/autowork', 'tasks/blocked', 'tasks/active', 'tasks/escalated', 'tasks/autobrief', 'briefs'):
        (state_dir / sub).mkdir(parents=True, exist_ok=True)
    (home / '.claude' / 'projects' / 'proj1' / 'memory').mkdir(parents=True)
    (home / '.claude' / 'scratch').mkdir(parents=True)
    config_dir.mkdir(parents=True)
    work_base.mkdir(parents=True)
    harness_file = repo_root / 'harness' / 'guard.py'
    harness_file.write_text('ORIGINAL_HARNESS_SOURCE\n')
    full_stop = state_dir / 'control' / 'full_stop'
    full_stop.write_text('STOP_ORIGINAL\n')
    allowlist = state_dir / 'control' / 'autowork' / 'auto_promote.allowlist'
    allowlist.write_text('ALLOWLIST_ORIGINAL\n')
    memory_md = home / '.claude' / 'projects' / 'proj1' / 'memory' / 'note.md'
    memory_md.write_text('MEMORY_ORIGINAL\n')
    hook_cfg = {'hooks': {'PreToolUse': [{'matcher': '*', 'hooks': [{'type': 'command', 'command': 'true'}]}]}}
    (config_dir / 'claude_worker.json').write_text(json.dumps(hook_cfg))
    (config_dir / 'claude_worker_planning_hooks.json').write_text(json.dumps(hook_cfg))
    task_id = 'T-PHASEA-WRITEDENIAL-001'
    blocked = state_dir / 'tasks' / 'blocked' / (task_id + '.json')
    blocked.write_text(json.dumps({'task_id': task_id, 'title': 'Phase-A blocked self-heal task', 'objective': 'Repair the regression that blocked the harness build.', 'files_touched': ['harness/guard.py'], 'spec': {'objective': 'Repair the regression that blocked the harness build.'}, 'acceptance_criteria': ['build passes']}))
    git_head_path = repo_root / '.git' / 'HEAD'
    git_head_before = None
    if shutil.which('git') is not None:
        ident = ['-c', 'user.name=phasea', '-c', 'user.email=phasea@example.com']
        subprocess.run(['git', '-C', str(repo_root), 'init', '-q'], capture_output=True, text=True)
        (repo_root / 'README').write_text('seed\n')
        subprocess.run(['git', '-C', str(repo_root), 'add', '-A'], capture_output=True, text=True)
        subprocess.run(['git', '-C', str(repo_root)] + ident + ['commit', '-q', '-m', 'seed'], capture_output=True, text=True)
        if git_head_path.exists():
            git_head_before = git_head_path.read_bytes()
    work_dirs = {}

    def fake_agent_work_dir(agent, session_slug):
        wd = work_base / agent / session_slug
        wd.mkdir(parents=True, exist_ok=True)
        work_dirs['wd'] = wd
        return wd
    monkeypatch.setattr(harness.paths, 'PROJECT_ROOT_STR', str(repo_root))
    monkeypatch.setattr(harness.paths, 'CONFIG_DIR_STR', str(config_dir))
    monkeypatch.setattr(harness.paths, 'HARNESS_DIR_STR', str(repo_root / 'harness'))
    monkeypatch.setattr(harness.paths, 'agent_work_dir', fake_agent_work_dir)
    monkeypatch.setenv('HOME', str(home))
    real_assert = orch._assert_claude_hook_config
    spy_calls = []

    def spy(cmd):
        spy_calls.append(list(cmd))
        return real_assert(cmd)
    monkeypatch.setattr(orch, '_assert_claude_hook_config', spy)
    captured = {}

    class _FakePopen:

        def __init__(self, cmd, *args, **kwargs):
            captured['cmd'] = list(cmd)
            captured['env'] = kwargs.get('env')
            captured['cwd'] = kwargs.get('cwd')
            self.args = cmd
            self.pid = 424242
            self.returncode = 0

        def wait(self, timeout=None):
            return 0

        def poll(self):
            return 0

        def communicate(self, *args, **kwargs):
            return ('', '')

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False
    monkeypatch.setattr(dae.subprocess, 'Popen', _FakePopen)
    dae._escalate_to_autobrief(state_dir, task_id, 'failed')
    monkeypatch.undo()
    c = _Ctx()
    c.repo_root = repo_root
    c.state_dir = state_dir
    c.home = home
    c.config_dir = config_dir
    c.work_dir = work_dirs.get('wd')
    c.argv = captured.get('cmd')
    c.env = captured.get('env')
    c.cwd = captured.get('cwd')
    c.spy_calls = spy_calls
    c.harness_file = harness_file
    c.full_stop = full_stop
    c.allowlist = allowlist
    c.memory_md = memory_md
    c.git_head_path = git_head_path
    c.git_head_before = git_head_before
    return c

@requires_bwrap
def test_jail_denies_write_to_repo_harness(ctx):
    """Negative control: a write to the ro repo ``harness/**`` is DENIED."""
    target = ctx.harness_file
    before = target.read_bytes()
    r = _run_probe(ctx.argv, ctx.repo_root, 'echo tampered > %s' % target)
    assert r.returncode != 0, 'jail allowed a write into the read-only repo harness/ tree'
    assert 'Read-only file system' in r.stderr or 'Permission denied' in r.stderr, 'write denial was not an EROFS/EACCES jail denial: %s' % r.stderr
    assert target.read_bytes() == before, 'harness source byte content changed inside jail'

@requires_bwrap
def test_jail_denies_write_to_state_control_full_stop_and_allowlist(ctx):
    """Negative control: writes to state/control/full_stop and to
    state/control/autowork/auto_promote.allowlist are both DENIED."""
    fs_before = ctx.full_stop.read_bytes()
    al_before = ctx.allowlist.read_bytes()
    r1 = _run_probe(ctx.argv, ctx.repo_root, 'echo tampered > %s' % ctx.full_stop)
    assert r1.returncode != 0, 'jail allowed a write to state/control/full_stop'
    assert 'Read-only file system' in r1.stderr or 'Permission denied' in r1.stderr, 'full_stop write denial was not an EROFS/EACCES jail denial: %s' % r1.stderr
    assert ctx.full_stop.read_bytes() == fs_before, 'full_stop content changed inside jail'
    r2 = _run_probe(ctx.argv, ctx.repo_root, 'echo tampered > %s' % ctx.allowlist)
    assert r2.returncode != 0, 'jail allowed a write to auto_promote.allowlist'
    assert 'Read-only file system' in r2.stderr or 'Permission denied' in r2.stderr, 'allowlist write denial was not an EROFS/EACCES jail denial: %s' % r2.stderr
    assert ctx.allowlist.read_bytes() == al_before, 'allowlist content changed inside jail'

@requires_bwrap
def test_jail_denies_write_to_claude_memory_md(ctx):
    """Negative control: a write to ``~/.claude/projects/*/memory/*.md`` is DENIED."""
    target = ctx.memory_md
    before = target.read_bytes()
    r = _run_probe(ctx.argv, ctx.repo_root, 'echo tampered > %s' % target)
    assert r.returncode != 0, 'jail allowed a write to a ~/.claude memory markdown file'
    assert 'Read-only file system' in r.stderr or 'Permission denied' in r.stderr, 'memory markdown write denial was not an EROFS/EACCES jail denial: %s' % r.stderr
    assert target.read_bytes() == before, 'memory markdown content changed inside jail'

@pytest.mark.skipif(shutil.which('bwrap') is None or shutil.which('git') is None, reason='bwrap and git both required')
def test_jail_denies_git_commit_on_repo(ctx):
    """Negative control: a ``git commit`` against the ro repo is DENIED.

    The repo is ``--ro-bind`` mounted, so committing must fail (non-zero) and
    the HEAD ref must remain byte-unchanged.
    """
    shell = 'cd %s && git -c user.name=x -c user.email=x@x commit --allow-empty -m tampered' % ctx.repo_root
    r = _run_probe(ctx.argv, ctx.repo_root, shell)
    assert r.returncode != 0, 'jail allowed a git commit on the read-only repo'
    assert 'Read-only file system' in r.stderr or 'Permission denied' in r.stderr, 'git commit denial was not an EROFS/EACCES jail denial: %s' % r.stderr
    if ctx.git_head_before is not None:
        assert ctx.git_head_path.read_bytes() == ctx.git_head_before, 'HEAD ref changed inside jail'

@requires_bwrap
def test_jail_allows_write_to_work_dir(ctx):
    """Positive control: a write to the per-spawn work_dir is ALLOWED."""
    assert ctx.work_dir is not None, 'agent_work_dir was never resolved during escalation'
    out = ctx.work_dir / 'agent_out.txt'
    r = _run_probe(ctx.argv, ctx.repo_root, 'echo OK_WORKDIR > %s' % out)
    assert r.returncode == 0, 'jail denied a legitimate write to the work_dir: %s' % r.stderr
    assert out.exists(), 'work_dir file was not created'
    assert out.read_text().strip() == 'OK_WORKDIR'

@requires_bwrap
def test_jail_allows_write_to_state_sessions(ctx):
    """Positive control: a write under ``state/sessions/`` is ALLOWED."""
    out = ctx.state_dir / 'sessions' / 'probe.txt'
    r = _run_probe(ctx.argv, ctx.repo_root, 'echo OK_SESSIONS > %s' % out)
    assert r.returncode == 0, 'jail denied a legitimate write to state/sessions: %s' % r.stderr
    assert out.exists(), 'state/sessions file was not created'
    assert out.read_text().strip() == 'OK_SESSIONS'

@requires_bwrap
def test_escalate_builds_real_jailed_argv_and_calls_hook_assert(ctx):
    """The REAL escalation built a bwrap-wrapped argv and ran the hook assert.

    Drives ``_escalate_to_autobrief`` (via the fixture), asserts the delegating
    spy recorded a call to the REAL ``_assert_claude_hook_config`` (proving the
    real assertion ran, not a stub), and asserts the captured spawn argv is
    genuinely bwrap-wrapped with the tmp repo ``--ro-bind``ed.  Under the
    bwrap-flip mutant ``_contain_selfheal`` returns the unjailed command and the
    argv assertions fail -- this is the non-vacuity anchor.
    """
    assert ctx.spy_calls, 'the delegating spy was never called -- _assert_claude_hook_config did not run'
    _assert_bwrap_argv(ctx.argv, ctx.repo_root)
    sep = _inner_split(ctx.argv)
    inner = ctx.argv[sep + 1:]
    assert inner, "no inner command survives after the jail '--' separator"
    assert callable(aj.build_jail_argv) and callable(aj.sandbox_enabled)