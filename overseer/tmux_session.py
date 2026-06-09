"""Deterministic tmux session controller for the ``claude-tmux`` backend.

This module drives a persistent INTERACTIVE ``claude`` running inside a tmux
pane so that a turn bills the Max subscription instead of the headless ``-p``
API. It is a pure, stdlib-only controller: every real ``tmux`` invocation flows
through ONE injected seam ``tmux_exec(argv: list[str]) -> str`` plus an injected
``sleep``. The module itself never calls subprocess, os.system, the network, or
a model.

The pieces:

  * pure argv builders for new-session / capture / send-text / send-keys / kill,
  * ``is_idle`` -- the agent is in-flight iff the pane still shows the
    ``esc to interrupt`` marker; idle once it is gone,
  * ``classify_startup`` + ``startup_keys`` -- recognise the folder-trust
    dialog, the bypass-permissions warning, and the input-ready screen, and the
    deterministic key sequence that advances each,
  * ``start_session`` -- new-session then auto-answer the startup dialogs until
    the input box is ready,
  * ``send_turn`` -- type the user text then Enter,
  * ``wait_idle`` -- poll capture-pane until the in-flight marker has been absent
    for ``settle_k`` consecutive polls, or the poll budget is exhausted.
"""
from __future__ import annotations
import time
from typing import Callable, List
IN_FLIGHT_MARKER = 'esc to interrupt'
READY_MARKER = 'shift+tab to cycle'
TRUST_MARKER = 'trust this folder'
BYPASS_MARKER = 'Bypass Permissions mode'
TmuxExec = Callable[[List[str]], str]
Sleep = Callable[[float], None]

def build_new_session_argv(session: str, inner_argv: List[str], cwd: str, *, cols: int=200, rows: int=50) -> List[str]:
    """Detached (-d), named (-s), sized (-x/-y), cwd (-c); inner cmd after ``--``."""
    return ['tmux', 'new-session', '-d', '-s', session, '-x', str(cols), '-y', str(rows), '-c', str(cwd), '--', *inner_argv]

def build_capture_argv(session: str) -> List[str]:
    """Plain-text snapshot of the pane targeted by ``session``."""
    return ['tmux', 'capture-pane', '-t', session, '-p']

def build_send_text_argv(session: str, text: str) -> List[str]:
    """User text after ``--`` so a leading dash is never read as an option."""
    return ['tmux', 'send-keys', '-t', session, '--', text]

def build_send_keys_argv(session: str, *keys: str) -> List[str]:
    """Named keys (e.g. ``Enter``, ``Down``) sent without the ``--`` guard."""
    return ['tmux', 'send-keys', '-t', session, *keys]

def build_kill_argv(session: str) -> List[str]:
    """Tear the session down."""
    return ['tmux', 'kill-session', '-t', session]

def is_idle(snapshot: str) -> bool:
    """True iff the in-flight marker (``esc to interrupt``) is absent."""
    return IN_FLIGHT_MARKER not in snapshot

def classify_startup(snapshot: str) -> str:
    """Classify a startup snapshot.

    Returns ``'ready'`` (input box idle, positively identified by the
    ``shift+tab to cycle`` footer), ``'trust'`` (folder-trust dialog),
    ``'bypass'`` (Bypass Permissions warning dialog), else ``'unknown'``.

    The ready footer literally contains ``bypass permissions on``; checking the
    ready marker FIRST keeps it from being misread as the bypass DIALOG.
    """
    if READY_MARKER in snapshot:
        return 'ready'
    if TRUST_MARKER in snapshot:
        return 'trust'
    if BYPASS_MARKER in snapshot:
        return 'bypass'
    return 'unknown'

def startup_keys(kind: str) -> List[str]:
    """The deterministic key sequence that advances each startup state."""
    return {'trust': ['Enter'], 'bypass': ['Down', 'Enter'], 'ready': [], 'unknown': []}.get(kind, [])

def start_session(session: str, inner_argv: List[str], cwd: str, *, tmux_exec: TmuxExec, sleep: Sleep=time.sleep, cols: int=200, rows: int=50, max_dialog_rounds: int=10, settle: float=0.3) -> bool:
    """Create the detached session then auto-answer startup dialogs.

    Returns True once the input box is ready, or False if
    ``max_dialog_rounds`` is exhausted first. On an ``unknown`` screen NO key is
    sent (never a blind keypress into the input box).
    """
    tmux_exec(build_new_session_argv(session, inner_argv, cwd, cols=cols, rows=rows))
    for _ in range(max_dialog_rounds):
        snapshot = tmux_exec(build_capture_argv(session))
        kind = classify_startup(snapshot)
        if kind == 'ready':
            return True
        for key in startup_keys(kind):
            tmux_exec(build_send_keys_argv(session, key))
        sleep(settle)
    return False

def send_turn(session: str, text: str, *, tmux_exec: TmuxExec) -> None:
    """Type the user text then send Enter to submit the turn."""
    tmux_exec(build_send_text_argv(session, text))
    tmux_exec(build_send_keys_argv(session, 'Enter'))

def wait_idle(session: str, *, tmux_exec: TmuxExec, sleep: Sleep=time.sleep, poll: float=2.0, timeout: float=600.0, settle_k: int=2) -> bool:
    """Poll capture-pane until idle has held for ``settle_k`` consecutive polls.

    Returns True once the in-flight marker has been absent for ``settle_k``
    consecutive snapshots, else False after ``int(timeout / poll)`` polls. A
    single idle blip followed by in-flight resets the counter.
    """
    max_polls = int(timeout / poll)
    consecutive = 0
    for _ in range(max_polls):
        snapshot = tmux_exec(build_capture_argv(session))
        if is_idle(snapshot):
            consecutive += 1
            if consecutive >= settle_k:
                return True
        else:
            consecutive = 0
        sleep(poll)
    return False

def kill_session(session: str, *, tmux_exec: TmuxExec) -> None:
    """Tear the tmux session down."""
    tmux_exec(build_kill_argv(session))