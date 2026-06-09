"""claude-tmux turn orchestration for the overseer.

``run_tmux_turn`` is the additive sibling of ``run_turn`` for the
``agent_backend == 'claude-tmux'`` path. Rather than spawning ``claude -p`` and
folding NDJSON, it drives a persistent INTERACTIVE claude living in a tmux pane
and reads the reply from the structured session transcript, composing the two
already-built substrate modules:

  * ``overseer.tmux_session`` -- ``start_session`` / ``send_turn`` /
    ``wait_idle`` over an injected ``tmux_exec`` seam,
  * ``overseer.tmux_transcript`` -- ``read_new_turn`` over injected
    ``read_text`` / ``list_dir`` seams.

A single turn:

  1. if the session is not yet started, start it (auto-answering the startup
     dialogs);
  2. send the user text;
  3. wait for idle;
  4. read the NEW assistant records from the transcript since the
     conversation's stored marker;
  5. advance that marker and return an ``AssistantTurn``.

All tmux + filesystem I/O flows through the injected seams; this module never
spawns a process, sleeps for real, or touches the network. Stdlib only.
"""
from __future__ import annotations
from typing import Any, Callable, Dict, Iterable, List, Sequence
from overseer import tmux_session, tmux_transcript
from overseer.driver import AssistantTurn

def run_tmux_turn(conversation: Dict[str, Any], user_text: str, *, session: str, start_argv: Sequence[str], cwd: str, config_dir: str, tmux_exec: Callable[[Sequence[str]], str], sleep: Callable[[float], Any], read_text: Callable[[str], str], list_dir: Callable[[str], List[str]], session_started: bool=False, poll: float=2.0, timeout: float=600.0) -> AssistantTurn:
    """Drive one claude-tmux turn and return the new ``AssistantTurn``.

    When ``session_started`` is ``False`` a fresh tmux session is created via
    ``tmux_session.start_session``; when ``True`` the live pane is reused. The
    user text is always sent (``send_turn``) and we then wait for the pane to go
    idle (``wait_idle``) before reading the NEW assistant records from the
    transcript (``tmux_transcript.read_new_turn``) starting at the
    conversation's stored ``tmux_marker``. The returned line-count marker is
    persisted back onto ``conversation`` so a later turn only reads new records.
    """
    if not session_started:
        tmux_session.start_session(session, list(start_argv), cwd, tmux_exec=tmux_exec, sleep=sleep)
    tmux_session.send_turn(session, user_text, tmux_exec=tmux_exec)
    tmux_session.wait_idle(session, tmux_exec=tmux_exec, sleep=sleep, poll=poll, timeout=timeout)
    marker = conversation.get('tmux_marker', 0)
    turn, new_marker = tmux_transcript.read_new_turn(config_dir, cwd, marker=marker, read_text=read_text, list_dir=list_dir, session_pref=conversation.get('claude_session_id'))
    conversation['tmux_marker'] = new_marker
    return turn