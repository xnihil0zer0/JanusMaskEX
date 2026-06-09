"""Oracle: the claude-tmux chat-turn entrypoint that persists like run_chat_turn.

``overseer.tmux_chat.run_tmux_chat_turn`` is what ``run_chat_turn`` delegates to
when a conversation's ``agent_backend == 'claude-tmux'``. It drives one
interactive turn via ``overseer.tmux_driver.run_tmux_turn`` over the real (or, in
tests, injected) tmux seams, then persists exactly as the NDJSON path does:
stores the (possibly new) session id, appends the assistant turn to the store,
and returns ``{ok, text, session_id, tool_uses}``. A spawn/seam failure is
surfaced as an ``ok=False`` assistant turn, never raised.

Hermetic: an injected ``tmux_seams`` bundle (fake always-idle pane + fake fs
transcript) means no real tmux/claude/network.
"""
from __future__ import annotations

import json
from pathlib import Path

from overseer.session_store import SessionStore
from overseer import tmux_chat


READY = " Welcome back\n > \n   bypass permissions on (shift+tab to cycle) . 0 tokens\n"


class FakeTmux:
    def __init__(self, fail=False):
        self.fail = fail
        self.calls = []

    def __call__(self, argv):
        self.calls.append(list(argv))
        if self.fail:
            raise OSError("tmux not found")
        if "capture-pane" in argv:
            return READY
        return ""


class FakeFS:
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


def _assistant(text):
    return json.dumps({"type": "assistant",
                       "message": {"role": "assistant",
                                   "content": [{"type": "text", "text": text}]}})


def _bundle(fake, fs, *, cwd="/work", cfg="/cfg", session="ovr_c1", started=True):
    return {
        "tmux_exec": fake, "sleep": _nosleep,
        "read_text": fs.read_text, "list_dir": fs.list_dir,
        "config_dir": cfg, "session": session, "cwd": cwd,
        "start_argv": ["env", "CLAUDE_CONFIG_DIR=" + cfg, "claude"],
        "session_started": started,
    }


def _fs_with_reply(text="144", session="sess-1", cwd="/work", cfg="/cfg"):
    from overseer import tmux_transcript as tt
    pdir = str(tt.project_dir(cfg, cwd))
    body = "\n".join([
        json.dumps({"type": "user", "message": {"role": "user", "content": "q"}}),
        _assistant(text),
    ]) + "\n"
    return FakeFS({pdir: {session + ".jsonl": body}})


def _store(tmp_path, backend="claude-tmux"):
    store = SessionStore(tmp_path / "sessions.json")
    store.create("c1", current_mode="brief-author", model="opus", agent_backend=backend)
    store.append_turn("c1", {"role": "user", "content": "q"})
    return store


def _run(store, tmp_path, bundle):
    rec = store.get("c1")
    return tmux_chat.run_tmux_chat_turn(
        store, "c1", "q", rec,
        config={}, repo_root=tmp_path, state_dir=tmp_path / "state",
        transcript_path=tmp_path / "logs" / "overseer_chat.jsonl",
        mode="brief-author", tmux_seams=bundle)


def test_persists_reply_and_session_id(tmp_path):
    store = _store(tmp_path)
    fake = FakeTmux()
    res = _run(store, tmp_path, _bundle(fake, _fs_with_reply(text="144")))
    assert res["ok"] is True
    assert res["text"] == "144"
    assert res["session_id"] == "sess-1"
    rec = store.get("c1")
    assert rec["claude_session_id"] == "sess-1"
    assert rec["transcript"][-1] == {"role": "assistant", "content": "144"}


def test_sends_the_turn_through_tmux(tmp_path):
    store = _store(tmp_path)
    fake = FakeTmux()
    _run(store, tmp_path, _bundle(fake, _fs_with_reply()))
    # the user text reached the pane via send-keys ... -- <text>
    sent = [c[c.index("--") + 1] for c in fake.calls if "send-keys" in c and "--" in c]
    assert "q" in sent


def test_writes_assistant_transcript_line(tmp_path):
    store = _store(tmp_path)
    _run(store, tmp_path, _bundle(FakeTmux(), _fs_with_reply(text="144")))
    log = tmp_path / "logs" / "overseer_chat.jsonl"
    assert log.exists()
    rows = [json.loads(l) for l in log.read_text().splitlines()]
    assert any(r.get("role") == "assistant" and r.get("content") == "144" for r in rows)


def test_seam_failure_surfaces_ok_false_without_raising(tmp_path):
    store = _store(tmp_path)
    res = _run(store, tmp_path, _bundle(FakeTmux(fail=True), _fs_with_reply()))
    assert res["ok"] is False
    # the error is recorded as an assistant turn so the UI shows it (no hang)
    assert store.get("c1")["transcript"][-1]["role"] == "assistant"
