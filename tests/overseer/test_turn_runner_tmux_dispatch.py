"""Oracle: run_chat_turn dispatches the claude-tmux backend (additive edit).

The only change to ``overseer.turn_runner.run_chat_turn`` is an ADDITIVE early
branch + a new optional ``tmux_seams`` injection param: when the conversation's
``agent_backend == 'claude-tmux'`` it delegates to
``overseer.tmux_chat.run_tmux_chat_turn`` (driving an interactive tmux turn);
for every other backend (``claude``/``agy``) the existing NDJSON path is
byte-for-byte unchanged. ``tmux_seams`` is forwarded so the tmux path is
hermetically testable; on the non-tmux path it is ignored.

``tests/overseer/test_turn_runner.py`` (the pre-committed run_chat_turn oracle)
still passes unchanged -- this file only adds the dispatch guarantee.
"""
from __future__ import annotations

import json

from overseer.session_store import SessionStore
from overseer import turn_runner


# --- claude-tmux side: a hermetic tmux bundle -------------------------------

READY = " Welcome back\n > \n   bypass permissions on (shift+tab to cycle) . 0 tokens\n"


class _FakeTmux:
    def __init__(self):
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        return READY if "capture-pane" in argv else ""


class _ExplodingTmux:
    def __call__(self, argv):
        raise AssertionError("tmux path must NOT run for a non-claude-tmux backend")


class _FakeFS:
    def __init__(self, tree):
        self.tree = tree

    def list_dir(self, path):
        return list(self.tree.get(str(path), {}).keys())

    def read_text(self, path):
        import os
        d, n = os.path.split(str(path))
        return self.tree[d][n]


def _nosleep(_):
    return None


def _fs_with_reply(text, cwd="/work", cfg="/cfg", session="sess-1"):
    from overseer import tmux_transcript as tt
    pdir = str(tt.project_dir(cfg, cwd))
    body = "\n".join([
        json.dumps({"type": "user", "message": {"role": "user", "content": "q"}}),
        json.dumps({"type": "assistant",
                    "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}}),
    ]) + "\n"
    return _FakeFS({pdir: {session + ".jsonl": body}})


def _tmux_bundle(fake, fs, *, cwd="/work", cfg="/cfg"):
    return {"tmux_exec": fake, "sleep": _nosleep, "read_text": fs.read_text,
            "list_dir": fs.list_dir, "config_dir": cfg, "session": "ovr_c1", "cwd": cwd,
            "start_argv": ["env", "CLAUDE_CONFIG_DIR=" + cfg, "claude"], "session_started": True}


# --- NDJSON (claude backend) seams ------------------------------------------

class _FakeParser:
    def handle_event(self, event):
        pass


def _canned(text=("Hello", " world")):
    lines = [json.dumps({"type": "system", "subtype": "init", "session_id": "s1"})]
    for c in text:
        lines.append(json.dumps({"type": "content_block_delta",
                                 "delta": {"type": "text_delta", "text": c}}))
    return lines


def _ndjson_seams():
    return (lambda cmd, **k: _canned(), lambda c, **k: {}, lambda a, **k: list(a), _FakeParser())


def _store(tmp_path, backend):
    store = SessionStore(tmp_path / "sessions.json")
    store.create("c1", current_mode="observe", model="opus", agent_backend=backend)
    store.append_turn("c1", {"role": "user", "content": "q"})
    return store


# --- the dispatch contract --------------------------------------------------

def test_claude_tmux_backend_routes_to_tmux_chat(tmp_path):
    store = _store(tmp_path, "claude-tmux")
    fake = _FakeTmux()
    res = turn_runner.run_chat_turn(
        store, "c1", "q", config={}, repo_root=tmp_path,
        state_dir=tmp_path / "state", logs_dir=tmp_path / "logs",
        tmux_seams=_tmux_bundle(fake, _fs_with_reply("144")))
    assert res["ok"] is True
    assert res["text"] == "144"                       # reply came from the tmux transcript
    assert store.get("c1")["transcript"][-1]["content"] == "144"
    # the NDJSON runner was never used; the tmux pane was driven
    assert any("send-keys" in c for c in fake.calls)


def test_claude_backend_still_uses_ndjson_path(tmp_path):
    store = _store(tmp_path, "claude")
    # a tmux bundle is supplied but MUST be ignored for the claude backend
    res = turn_runner.run_chat_turn(
        store, "c1", "q", config={}, repo_root=tmp_path,
        state_dir=tmp_path / "state", logs_dir=tmp_path / "logs",
        seams=_ndjson_seams(),
        tmux_seams={"tmux_exec": _ExplodingTmux(), "sleep": _nosleep,
                    "read_text": lambda p: "", "list_dir": lambda p: [],
                    "config_dir": "/cfg", "session": "x", "cwd": "/w",
                    "start_argv": ["claude"], "session_started": True})
    assert res["text"] == "Hello world"               # NDJSON path, unchanged
