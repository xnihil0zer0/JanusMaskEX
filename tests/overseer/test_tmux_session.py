"""Oracle: the tmux session controller for the ``claude-tmux`` backend.

``overseer.tmux_session`` drives a persistent INTERACTIVE ``claude`` running in a
tmux pane (so the turn bills the Max subscription, not the headless ``-p`` API).
It is a DETERMINISTIC controller over ONE injected I/O seam ``tmux_exec(argv) ->
str`` (the only place real ``tmux`` runs) plus an injected ``sleep``. Everything
here is pure/stdlib and hermetic: a fake ``tmux_exec`` returns scripted pane
snapshots, so a whole start->send->wait cycle is exercised with no real tmux, no
real claude, no network, and no model call.

The contract pinned here:

  * pure argv builders for new-session / capture / send-text / send-keys / kill,
  * ``is_idle(snapshot)`` -- the agent is in-flight iff the pane still shows the
    ``esc to interrupt`` marker; idle once it is gone,
  * ``classify_startup(snapshot)`` + ``startup_keys(kind)`` -- recognise the
    folder-trust dialog, the bypass-permissions warning, and the input-ready
    screen, and return the deterministic key sequence that advances each,
  * ``start_session`` -- new-session then auto-answer the startup dialogs until
    the input box is ready,
  * ``send_turn`` -- type the user text then Enter,
  * ``wait_idle`` -- poll capture-pane until the in-flight marker has been absent
    for ``settle_k`` consecutive polls (idle), or the poll budget is exhausted
    (timeout) -> bool.

The pane fixtures below are the REAL Claude Code v2.1 TUI screens captured from a
live tmux drive, trimmed to their identifying lines.
"""
from __future__ import annotations

import pytest

from overseer import tmux_session as ts


# --- real captured TUI screens (trimmed) -----------------------------------

TRUST_SCREEN = """\
 Accessing workspace:
 /tmp/jm_tmux_spike
 Quick safety check: Is this a project you created or one you trust?
 Claude Code'll be able to read, edit, and execute files here.
 > 1. Yes, I trust this folder
   2. No, exit
 Enter to confirm . Esc to cancel
"""

BYPASS_SCREEN = """\
  WARNING: Claude Code running in Bypass Permissions mode
  In Bypass Permissions mode, Claude Code will not ask for your approval.
  > 1. No, exit
    2. Yes, I accept
  Enter to confirm . Esc to cancel
"""

READY_SCREEN = """\
 Welcome back Kevin!
 Opus 4.8 (1M context) with high . Claude Max . Kevin Lindmark
 > Try "how do I log an error?"
   bypass permissions on (shift+tab to cycle) . <- for agents      0 tokens
"""

THINKING_SCREEN = """\
 > Reply with ONLY the number: what is 19 times 23?
   * Cogitating... (esc to interrupt)                              1234 tokens
"""

REPLIED_SCREEN = """\
 > Reply with ONLY the number: what is 19 times 23?
 * 437
 * Cogitated for 1s
 >
   bypass permissions on (shift+tab to cycle) . <- for agents   21939 tokens
"""


# --- fake tmux_exec seam ----------------------------------------------------

class FakeTmux:
    """Records every argv; returns scripted snapshots for capture-pane calls."""

    def __init__(self, captures=()):
        self._captures = list(captures)
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if "capture-pane" in argv:
            return self._captures.pop(0) if self._captures else READY_SCREEN
        return ""

    def sent_texts(self):
        """The text payloads sent via ``send-keys ... -- <text>``."""
        out = []
        for c in self.calls:
            if "send-keys" in c and "--" in c:
                out.append(c[c.index("--") + 1])
        return out

    def sent_keys(self):
        """Named keys sent via ``send-keys -t <s> <Key>`` (no ``--`` literal)."""
        out = []
        for c in self.calls:
            if "send-keys" in c and "--" not in c:
                out.extend(c[c.index(self._target(c)) + 1:])
        return out

    @staticmethod
    def _target(argv):
        return argv[argv.index("-t") + 1]


def _nosleep(_seconds):
    return None


# --- pure argv builders -----------------------------------------------------

def test_new_session_argv_is_detached_named_and_runs_inner():
    argv = ts.build_new_session_argv("ovr_c1", ["claude", "--foo"], "/work", cols=200, rows=50)
    assert argv[:4] == ["tmux", "new-session", "-d", "-s"]
    assert "ovr_c1" in argv
    # geometry + cwd present
    assert "-x" in argv and "200" in argv and "-y" in argv and "50" in argv
    assert "-c" in argv and "/work" in argv
    # the inner command runs after the `--` separator, verbatim and last
    assert argv[argv.index("--") + 1:] == ["claude", "--foo"]


def test_capture_argv_targets_session_plaintext():
    assert ts.build_capture_argv("ovr_c1") == ["tmux", "capture-pane", "-t", "ovr_c1", "-p"]


def test_send_text_argv_uses_double_dash_guard():
    # user text after `--` so a leading dash / control token is never an option
    argv = ts.build_send_text_argv("ovr_c1", "-rm -rf is just text")
    assert argv[:4] == ["tmux", "send-keys", "-t", "ovr_c1"]
    assert argv[-2] == "--"
    assert argv[-1] == "-rm -rf is just text"


def test_send_keys_argv_passes_named_keys():
    argv = ts.build_send_keys_argv("ovr_c1", "Enter")
    assert argv == ["tmux", "send-keys", "-t", "ovr_c1", "Enter"]


def test_kill_argv():
    assert ts.build_kill_argv("ovr_c1") == ["tmux", "kill-session", "-t", "ovr_c1"]


# --- idle detection ---------------------------------------------------------

def test_is_idle_false_while_in_flight():
    assert ts.is_idle(THINKING_SCREEN) is False


def test_is_idle_true_when_marker_absent():
    assert ts.is_idle(READY_SCREEN) is True
    assert ts.is_idle(REPLIED_SCREEN) is True


# --- startup dialog classification + keys -----------------------------------

def test_classify_trust_screen():
    assert ts.classify_startup(TRUST_SCREEN) == "trust"


def test_classify_bypass_screen():
    assert ts.classify_startup(BYPASS_SCREEN) == "bypass"


def test_classify_ready_screen_not_confused_by_bypass_footer():
    # the ready screen literally contains "bypass permissions on" in its footer;
    # it must NOT be misread as the bypass DIALOG. It is positively identified by
    # the idle-input footer ("shift+tab to cycle"), present once the box is ready.
    assert ts.classify_startup(READY_SCREEN) == "ready"
    assert ts.classify_startup(REPLIED_SCREEN) == "ready"


def test_classify_unknown_screen_is_not_ready():
    # an unrecognised splash is 'unknown' -- NOT 'ready' -- so start_session does
    # not falsely believe the box is ready, and sends no blind key.
    assert ts.classify_startup("...some unrecognised splash...") == "unknown"


def test_startup_keys_mapping():
    assert ts.startup_keys("trust") == ["Enter"]
    assert ts.startup_keys("bypass") == ["Down", "Enter"]
    assert ts.startup_keys("ready") == []
    assert ts.startup_keys("unknown") == []


# --- start_session: drive the dialogs to the input box ----------------------

def test_start_session_answers_trust_then_bypass_then_ready():
    fake = FakeTmux(captures=[TRUST_SCREEN, BYPASS_SCREEN, READY_SCREEN])
    ok = ts.start_session("ovr_c1", ["claude"], "/work",
                          tmux_exec=fake, sleep=_nosleep)
    assert ok is True
    # new-session was created exactly once, first
    assert fake.calls[0][:2] == ["tmux", "new-session"]
    # it sent Enter (trust) then Down+Enter (bypass), in order
    assert fake.sent_keys() == ["Enter", "Down", "Enter"]


def test_start_session_ready_immediately_sends_no_keys():
    fake = FakeTmux(captures=[READY_SCREEN])
    ok = ts.start_session("ovr_c1", ["claude"], "/work",
                          tmux_exec=fake, sleep=_nosleep)
    assert ok is True
    assert fake.sent_keys() == []


def test_start_session_times_out_on_unknown_screen_without_blind_keys():
    # an unrecognised screen must NOT send a blind key into the input box.
    fake = FakeTmux(captures=["...some unrecognised splash..."] * 50)
    ok = ts.start_session("ovr_c1", ["claude"], "/work",
                          tmux_exec=fake, sleep=_nosleep, max_dialog_rounds=5)
    assert ok is False
    assert fake.sent_keys() == []


# --- send_turn --------------------------------------------------------------

def test_send_turn_types_text_then_enter():
    fake = FakeTmux()
    ts.send_turn("ovr_c1", "hello world", tmux_exec=fake)
    assert fake.sent_texts() == ["hello world"]
    assert fake.sent_keys() == ["Enter"]


# --- wait_idle --------------------------------------------------------------

def test_wait_idle_returns_true_after_settle():
    # busy, busy, then idle twice -> settles
    fake = FakeTmux(captures=[THINKING_SCREEN, THINKING_SCREEN,
                              REPLIED_SCREEN, REPLIED_SCREEN])
    ok = ts.wait_idle("ovr_c1", tmux_exec=fake, sleep=_nosleep,
                      poll=0.01, timeout=10.0, settle_k=2)
    assert ok is True


def test_wait_idle_times_out_when_never_idle():
    fake = FakeTmux(captures=[THINKING_SCREEN] * 1000)
    ok = ts.wait_idle("ovr_c1", tmux_exec=fake, sleep=_nosleep,
                      poll=0.01, timeout=0.05, settle_k=2)
    assert ok is False


def test_wait_idle_requires_consecutive_idle_not_a_single_blip():
    # idle once (blip) then busy again -> must NOT declare done at settle_k=2
    fake = FakeTmux(captures=[REPLIED_SCREEN, THINKING_SCREEN, THINKING_SCREEN])
    ok = ts.wait_idle("ovr_c1", tmux_exec=fake, sleep=_nosleep,
                      poll=0.01, timeout=0.04, settle_k=2)
    assert ok is False


# --- kill_session -----------------------------------------------------------

def test_kill_session_issues_kill():
    fake = FakeTmux()
    ts.kill_session("ovr_c1", tmux_exec=fake)
    assert fake.calls == [["tmux", "kill-session", "-t", "ovr_c1"]]
