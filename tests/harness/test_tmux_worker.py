"""Oracle for the PTY-driven jailed-interactive-claude worker backend.

Exercises the REAL orchestration API of ``harness.tmux_worker`` over injected
fakes -- no real PTY, bwrap, or claude process is ever spawned:

  * ``run_pty_worker`` drives spawn -> reach-ready (auto-answering startup
    dialogs) -> send-seed -> complete-on-stable-deliverable, always tearing the
    child down.
  * ``spawn_claude_tmux`` wires the real jail + interactive (never ``-p``) argv
    and hands a jailed argv to ``run_pty_worker``.
  * marker matching is whitespace/case-insensitive (the raw PTY render drops the
    literal spaces a tmux capture would show).

These tests are NON-VACUOUS: each asserts an observable behaviour that a broken
mutant (e.g. emitting ``-p``, not jailing, never sending the seed, space-sensitive
marker matching, or leaking the child) would violate.
"""
from __future__ import annotations
import os
from pathlib import Path

import pytest

import harness.tmux_worker as tw


# --------------------------------------------------------------------------- #
# Fake PTY environment shared by the run_pty_worker tests.
# --------------------------------------------------------------------------- #
class FakePty:
    """A scripted PTY whose seams feed run_pty_worker deterministically."""

    def __init__(self, *, startup_frames, work_frames, deliver_after=0.6,
                 deliver_size=42, fd=7, pid=4242):
        self._startup = list(startup_frames)
        self._work = list(work_frames)
        self.fd = fd
        self.pid = pid
        self.t = 1000.0
        self.writes = []
        self.kills = []
        self.waited = []
        self.spawned = None
        self.geometry = None
        self.seed_sent = False
        self._seed_text_seen = False
        self._deliver_at = None
        self._deliver_after = deliver_after
        self._deliver_size = deliver_size
        self._startup_last = b''

    # clock ------------------------------------------------------------------ #
    def monotonic(self):
        v = self.t
        self.t += 0.2
        return v

    def sleep(self, _seconds):
        return None

    # process / pty ---------------------------------------------------------- #
    def spawn(self, argv, cwd):
        self.spawned = (list(argv), cwd)
        return self.pid, self.fd

    def set_geometry(self, fd, cols, rows):
        self.geometry = (fd, cols, rows)

    def select(self, rlist, _w, _x, _timeout):
        return list(rlist), [], []

    def read(self, _fd, _n):
        if not self.seed_sent:
            if self._startup:
                self._startup_last = self._startup.pop(0)
            return self._startup_last
        if self._work:
            return self._work.pop(0)
        return b' working (esc to interrupt) '

    def write(self, _fd, data):
        self.writes.append(data)
        if b'Read the file' in data:
            self._seed_text_seen = True
        elif data == b'\r' and self._seed_text_seen and not self.seed_sent:
            self.seed_sent = True
            self._deliver_at = self.t + self._deliver_after
        return len(data)

    def kill(self, pid, sig):
        self.kills.append((pid, sig))

    def waitpid(self, pid, flags):
        self.waited.append((pid, flags))
        return pid, 0

    def close(self, _fd):
        return None

    # deliverable ------------------------------------------------------------ #
    def exists(self, _path):
        return self.seed_sent and self._deliver_at is not None and self.t >= self._deliver_at

    def getsize(self, _path):
        return self._deliver_size

    # convenience ------------------------------------------------------------ #
    def run(self, **overrides):
        kwargs = dict(
            jailed_argv=['/usr/bin/bwrap', 'claude'], work_dir='/tmp/wd', seed=tw.seed_from_prompt_file(),
            deliverable='/tmp/wd/outbox/submission.py', startup_timeout=20.0, idle_timeout=60.0,
            poll=0.5, settle_k=2, min_work=0.0, grace=2.0,
            spawn=self.spawn, os_read=self.read, os_write=self.write, select_fn=self.select,
            os_kill=self.kill, os_waitpid=self.waitpid, os_close=self.close,
            monotonic=self.monotonic, sleep=self.sleep,
            exists=self.exists, getsize=self.getsize, set_geometry=self.set_geometry,
        )
        kwargs.update(overrides)
        return tw.run_pty_worker(**kwargs)


def test_run_pty_worker_reaches_ready_sends_seed_completes_on_deliverable():
    fake = FakePty(
        startup_frames=[b'\x1b[2J Welcome back  (shift+tab to cycle) '],
        work_frames=[b' Thinking (esc to interrupt) ', b' Working (esc to interrupt) '],
    )
    result = fake.run()
    assert result.started is True
    assert result.idle is True
    # the seed turn text was typed, followed by an Enter to submit it
    assert any(b'Read the file' in w for w in fake.writes)
    assert b'\r' in fake.writes
    # child was torn down
    assert fake.kills, 'child process must be killed on teardown'
    assert fake.kills[0][0] == fake.pid


def test_run_pty_worker_does_not_send_seed_before_ready():
    # never renders the ready marker -> startup must time out, seed never sent
    fake = FakePty(startup_frames=[b' loading... '], work_frames=[])
    result = fake.run(startup_timeout=3.0)
    assert result.idle is False
    assert not any(b'Read the file' in w for w in fake.writes), 'seed sent before ready'
    # even on the timeout path the child is killed
    assert fake.kills, 'child must be killed even when startup times out'


def test_run_pty_worker_answers_trust_dialog_before_ready():
    fake = FakePty(
        startup_frames=[b' Do you trust this folder? ', b' (shift+tab to cycle) '],
        work_frames=[b' (esc to interrupt) '],
    )
    fake.run()
    # the trust dialog is answered with Enter BEFORE the seed text is typed
    first_enter = fake.writes.index(b'\r') if b'\r' in fake.writes else -1
    first_seed = next((i for i, w in enumerate(fake.writes) if b'Read the file' in w), -1)
    assert first_enter != -1, 'trust dialog must be answered with Enter'
    assert first_seed == -1 or first_enter < first_seed


def test_run_pty_worker_kills_child_when_spawn_succeeds_then_select_dies():
    fake = FakePty(startup_frames=[b' x '], work_frames=[])

    def dying_select(*_a, **_k):
        raise OSError('pty closed')

    result = fake.run(select_fn=dying_select, startup_timeout=3.0)
    assert result.started is True
    assert fake.kills, 'child must be killed even if select raises'


def test_run_pty_worker_returns_not_idle_when_deliverable_never_appears():
    fake = FakePty(
        startup_frames=[b' (shift+tab to cycle) '],
        work_frames=[b' (esc to interrupt) '],
        deliver_after=10_000.0,  # effectively never within idle_timeout
    )
    result = fake.run(idle_timeout=5.0)
    assert result.started is True
    assert result.idle is False


# --------------------------------------------------------------------------- #
# marker normalisation: the raw PTY stream has no literal spaces between words.
# --------------------------------------------------------------------------- #
def test_marker_matching_is_whitespace_and_case_insensitive():
    # 'shift+tabtocycle' (spaces collapsed) must still match the READY marker
    assert tw._has(b'foo shift+tabtocycle bar', tw.READY_MARKER)
    assert tw._has(b'ESCTOINTERRUPT', tw.IN_FLIGHT_MARKER)
    assert not tw._has(b'nothing here', tw.READY_MARKER)


def test_latest_idle_reflects_most_recent_footer():
    # working footer renders BOTH markers with in-flight LAST -> not idle
    assert tw._latest_idle(b'(shift+tab to cycle) ... (esc to interrupt)') is False
    # finished -> ready footer is the most recent
    assert tw._latest_idle(b'(esc to interrupt) ...later... (shift+tab to cycle)') is True
    # neither marker -> not idle
    assert tw._latest_idle(b'just booting') is False


# --------------------------------------------------------------------------- #
# seed text points claude at the on-disk prompt file (small typed turn).
# --------------------------------------------------------------------------- #
def test_seed_from_prompt_file_references_the_file():
    seed = tw.seed_from_prompt_file('.tmux_prompt.txt')
    assert '.tmux_prompt.txt' in seed
    assert seed.strip(), 'seed must not be empty'


# --------------------------------------------------------------------------- #
# spawn_claude_tmux real-wiring: jailed INTERACTIVE argv, never headless -p.
# --------------------------------------------------------------------------- #
def test_spawn_claude_tmux_builds_jailed_interactive_argv(tmp_path, monkeypatch):
    work_dir = tmp_path / 'wd'
    (work_dir / 'outbox').mkdir(parents=True)
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    # empty fake HOME so seed_config_dir finds no creds to copy (no real I/O)
    fake_home = tmp_path / 'home'
    fake_home.mkdir()
    monkeypatch.setenv('HOME', str(fake_home))
    monkeypatch.delenv('JANUSMASK_WORKING_DIR', raising=False)

    captured = {}

    def spy_build_jail_argv(cmd, **kwargs):
        captured['interactive'] = list(cmd)
        captured['jail_kwargs'] = kwargs
        return ['/usr/bin/bwrap', '--JAILED--', *cmd]

    def spy_run(**kwargs):
        captured['run_kwargs'] = kwargs
        return tw.TmuxWorkerResult(started=True, idle=True, snapshot='')

    monkeypatch.setattr(tw.agent_jail, 'build_jail_argv', spy_build_jail_argv)
    monkeypatch.setattr(tw, 'run_pty_worker', spy_run)

    config = {
        'agents': {'claude': {
            'command': '/opt/claude/bin/claude',
            'args': ['-p', '--model', 'opus', '--tools', 'Read,Glob,Grep,Write', '--output-format', 'stream-json'],
        }},
        'synthesis': {'timeout_seconds': 999},
    }
    env = {
        'JANUSMASK_WORK_DIR': str(work_dir),
        'JANUSMASK_STATE_DIR': str(state_dir),
        'JANUSMASK_TASK_ID': 'leaf-x',
    }
    proc = tw.spawn_claude_tmux('claude', 'FULL PROMPT BODY', env, config, dbus_sock=None)

    # returns an exited-proc shim stamped with the work dir
    assert isinstance(proc, tw._ExitedProc)
    assert proc.poll() == 0
    assert proc._work_dir == str(work_dir)

    # run_pty_worker was handed the JAILED argv (not the bare interactive one)
    jailed = captured['run_kwargs']['jailed_argv']
    assert jailed[:2] == ['/usr/bin/bwrap', '--JAILED--']

    # the INTERACTIVE argv given to the jail is interactive, NEVER headless
    interactive = captured['interactive']
    assert '-p' not in interactive
    assert '--print' not in interactive
    assert '--output-format' not in interactive
    assert '/opt/claude/bin/claude' in interactive
    assert '--model' in interactive and 'opus' in interactive
    # per-task CLAUDE_CONFIG_DIR lives UNDER the jailed work dir
    cfg_dir_tokens = [a for a in interactive if a.startswith('CLAUDE_CONFIG_DIR=')]
    assert cfg_dir_tokens, 'interactive argv must set CLAUDE_CONFIG_DIR'
    assert str(work_dir) in cfg_dir_tokens[0]

    # the jail was scoped to the work/state dirs
    assert captured['jail_kwargs'].get('work_dir') == str(work_dir)
    assert captured['jail_kwargs'].get('state_dir') == str(state_dir)

    # the full prompt was written to the file the seed points at, with an
    # appended deliverable directive: the PTY claude has NO submit/stdout channel
    # (unlike headless -p / agy), so it MUST be told to write its submission to
    # outbox/submission.py via the Write tool, or it delivers nothing and the
    # orchestrator silently falls back to agy.
    prompt_file = work_dir / '.tmux_prompt.txt'
    written = prompt_file.read_text()
    assert 'FULL PROMPT BODY' in written
    assert 'outbox/submission.py' in written
    assert 'Write tool' in written

    # the configured synthesis timeout is honored as the idle budget
    assert captured['run_kwargs']['idle_timeout'] == 999.0
    # run_pty_worker is told which deliverable to watch (the harvested submission)
    assert captured['run_kwargs']['deliverable'].endswith('outbox/submission.py')


def test_spawn_claude_tmux_persists_snapshot_for_diagnosis(tmp_path, monkeypatch):
    """A failed PTY turn (started, no deliverable) must leave a persisted snapshot
    under state_dir/sessions so the silent agy-fallback is diagnosable -- the live
    bug was that run_pty_worker's TmuxWorkerResult/snapshot was discarded."""
    work_dir = tmp_path / 'wd'
    (work_dir / 'outbox').mkdir(parents=True)
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    fake_home = tmp_path / 'home'
    fake_home.mkdir()
    monkeypatch.setenv('HOME', str(fake_home))
    monkeypatch.delenv('JANUSMASK_WORKING_DIR', raising=False)
    monkeypatch.setattr(tw.agent_jail, 'build_jail_argv', lambda cmd, **k: ['/usr/bin/bwrap', *cmd])
    monkeypatch.setattr(
        tw, 'run_pty_worker',
        lambda **k: tw.TmuxWorkerResult(started=True, idle=False, snapshot='CLAUDE-TUI-DUMP-ZZZ'),
    )
    config = {
        'agents': {'claude': {'command': '/opt/claude/bin/claude', 'args': ['--model', 'opus']}},
        'synthesis': {'timeout_seconds': 5},
    }
    env = {
        'JANUSMASK_WORK_DIR': str(work_dir),
        'JANUSMASK_STATE_DIR': str(state_dir),
        'JANUSMASK_TASK_ID': 'leaf-z',
    }
    tw.spawn_claude_tmux('claude', 'BODY', env, config, dbus_sock=None)
    snaps = list((state_dir / 'sessions').glob('pty_claude_leaf-z*'))
    assert snaps, 'a PTY snapshot must be persisted for diagnosis'
    text = snaps[0].read_text()
    assert 'CLAUDE-TUI-DUMP-ZZZ' in text
    assert 'NO_DELIVERABLE' in text or 'idle=False' in text
