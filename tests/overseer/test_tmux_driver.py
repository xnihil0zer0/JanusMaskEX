"""Oracle: the claude-tmux turn orchestration in overseer.driver.

``run_tmux_turn`` is the additive sibling of ``run_turn`` for the
``agent_backend == 'claude-tmux'`` path. It does NOT spawn ``claude -p`` or fold
NDJSON; instead it drives a persistent INTERACTIVE claude in a tmux pane and
reads the reply from the structured session transcript, composing the two
substrate modules already built:

  * ``overseer.tmux_session`` -- start_session / send_turn / wait_idle, over an
    injected ``tmux_exec`` seam,
  * ``overseer.tmux_transcript`` -- read_new_turn, over injected
    ``read_text`` / ``list_dir`` seams.

A turn: (1) if the session is not yet started, start it (auto-answering the
startup dialogs); (2) send the user text; (3) wait for idle; (4) read the NEW
assistant records from the transcript since the conversation's stored marker;
(5) advance that marker and return an ``AssistantTurn``. ``run_turn`` (the
claude/agy NDJSON path) is untouched.

Everything is hermetic: a fake ``tmux_exec`` returns an always-idle ready pane,
a fake fs returns a one-line transcript. No real tmux, claude, network, or
model call.
"""
from __future__ import annotations

import json

from overseer.tmux_driver import run_tmux_turn
from overseer.driver import AssistantTurn


READY = (" Welcome back\n > \n   bypass permissions on (shift+tab to cycle) . 0 tokens\n")


class FakeTmux:
    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if "capture-pane" in argv:
            return READY            # always ready/idle: start + wait_idle both settle
        return ""

    def has(self, *needles):
        return any(all(n in c for n in needles) for c in self.calls)

    def sent_text(self):
        for c in self.calls:
            if "send-keys" in c and "--" in c:
                return c[c.index("--") + 1]
        return None


class FakeFS:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, path):
        return list(self.tree.get(str(path), {}).keys())

    def read_text(self, path):
        import os
        d, n = os.path.split(str(path))
        return self.tree[d][n]


def _transcript(slug_dir, fname, *records):
    return {slug_dir: {fname: "\n".join(json.dumps(r) for r in records) + "\n"}}


def _assistant(text):
    return {"type": "assistant",
            "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}


def _nosleep(_):
    return None


def _fs_with_reply(text="437", session="sess-1", cwd="/work", cfg="/cfg"):
    # project dir for cwd '/work' is '<cfg>/projects/-work'
    from overseer import tmux_transcript as tt
    pdir = str(tt.project_dir(cfg, cwd))
    return FakeFS(_transcript(pdir, session + ".jsonl",
                              {"type": "user", "message": {"role": "user", "content": "q"}},
                              _assistant(text)))


def test_run_tmux_turn_returns_transcript_reply():
    conv = {"claude_session_id": "sess-1"}
    fake = FakeTmux()
    fs = _fs_with_reply(text="437")
    turn = run_tmux_turn(
        conv, "what is 19*23?", session="ovr_c1", start_argv=["claude"],
        cwd="/work", config_dir="/cfg", tmux_exec=fake, sleep=_nosleep,
        read_text=fs.read_text, list_dir=fs.list_dir, session_started=False,
        poll=0.01, timeout=1.0)
    assert isinstance(turn, AssistantTurn)
    assert turn.text == "437"                       # reply read from the JSONL
    assert turn.session_id == "sess-1"


def test_run_tmux_turn_sends_user_text_and_enter():
    conv = {"claude_session_id": "sess-1"}
    fake = FakeTmux()
    fs = _fs_with_reply()
    run_tmux_turn(conv, "hello there", session="ovr_c1", start_argv=["claude"],
                  cwd="/work", config_dir="/cfg", tmux_exec=fake, sleep=_nosleep,
                  read_text=fs.read_text, list_dir=fs.list_dir, session_started=False,
                  poll=0.01, timeout=1.0)
    assert fake.sent_text() == "hello there"
    assert fake.has("send-keys", "Enter")


def test_run_tmux_turn_starts_session_when_not_started():
    conv = {"claude_session_id": "sess-1"}
    fake = FakeTmux()
    fs = _fs_with_reply()
    run_tmux_turn(conv, "hi", session="ovr_c1", start_argv=["claude", "--interactive-ish"],
                  cwd="/work", config_dir="/cfg", tmux_exec=fake, sleep=_nosleep,
                  read_text=fs.read_text, list_dir=fs.list_dir, session_started=False,
                  poll=0.01, timeout=1.0)
    assert fake.has("new-session")                  # a session was created


def test_run_tmux_turn_skips_start_when_already_started():
    conv = {"claude_session_id": "sess-1"}
    fake = FakeTmux()
    fs = _fs_with_reply()
    run_tmux_turn(conv, "hi", session="ovr_c1", start_argv=["claude"],
                  cwd="/work", config_dir="/cfg", tmux_exec=fake, sleep=_nosleep,
                  read_text=fs.read_text, list_dir=fs.list_dir, session_started=True,
                  poll=0.01, timeout=1.0)
    assert not fake.has("new-session")              # existing session reused


def test_run_tmux_turn_advances_marker_for_incremental_reads():
    conv = {"claude_session_id": "sess-1"}
    fake = FakeTmux()
    fs = _fs_with_reply(text="437")  # 2 transcript lines (user + assistant)
    turn = run_tmux_turn(
        conv, "q", session="ovr_c1", start_argv=["claude"], cwd="/work",
        config_dir="/cfg", tmux_exec=fake, sleep=_nosleep,
        read_text=fs.read_text, list_dir=fs.list_dir, session_started=True,
        poll=0.01, timeout=1.0)
    assert turn.text == "437"
    # the conversation's tmux marker now reflects the consumed line count, so a
    # later turn only reads NEW records.
    assert conv.get("tmux_marker") == 2
