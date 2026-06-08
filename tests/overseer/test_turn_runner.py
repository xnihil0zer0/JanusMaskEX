"""Oracle for overseer.turn_runner: the web<->driver bridge.

Exercises the deterministic store/transcript bookkeeping with INJECTED fake
seams (no real agent spawn), plus the real seam-construction helpers
(claude-path resolution, env allowlist, jail toggling). The live claude spawn
itself is out of scope here -- only the wiring around it.
"""
from __future__ import annotations

import json
from pathlib import Path

from overseer.session_store import SessionStore
from overseer import turn_runner


class _FakeParser:
    def __init__(self):
        self.events = []

    def handle_event(self, event):
        self.events.append(event)


def _canned_stream(session_id="sess-1", text=("Hello", " world")):
    lines = [json.dumps({"type": "system", "subtype": "init", "session_id": session_id})]
    for chunk in text:
        lines.append(json.dumps({"type": "content_block_delta",
                                 "delta": {"type": "text_delta", "text": chunk}}))
    return lines


def _seams(captured, lines):
    def jail_builder(argv, **kw):
        captured["argv"] = list(argv)
        return list(argv)

    def env_builder(conversation, **kw):
        return {"X": "1"}

    def runner(cmd, *, env, stdin, **kw):
        captured["stdin"] = stdin
        captured["env"] = env
        return lines

    return (runner, env_builder, jail_builder, _FakeParser())


def _store(tmp_path):
    store = SessionStore(tmp_path / "sessions.json")
    store.create("conv-1", current_mode="observe", model="opus", agent_backend="claude")
    store.append_turn("conv-1", {"role": "user", "content": "hi there"})
    return store


def test_run_chat_turn_persists_assistant_and_session(tmp_path):
    store = _store(tmp_path)
    captured = {}
    res = turn_runner.run_chat_turn(
        store, "conv-1", "hi there",
        config={}, repo_root=tmp_path, state_dir=tmp_path / "state",
        logs_dir=tmp_path / "logs",
        seams=_seams(captured, _canned_stream()),
    )
    assert res["ok"] is True
    assert res["text"] == "Hello world"
    assert res["session_id"] == "sess-1"
    rec = store.get("conv-1")
    assert rec["claude_session_id"] == "sess-1"          # persisted
    assert rec["transcript"][-1] == {"role": "assistant", "content": "Hello world"}
    assert captured["stdin"] == "hi there"               # user_text fed on stdin


def test_run_chat_turn_writes_transcript_jsonl_both_turns(tmp_path):
    store = _store(tmp_path)
    captured = {}
    turn_runner.run_chat_turn(
        store, "conv-1", "hi there",
        config={}, repo_root=tmp_path, state_dir=tmp_path / "state",
        logs_dir=tmp_path / "logs",
        seams=_seams(captured, _canned_stream()),
    )
    log = tmp_path / "logs" / "overseer_chat.jsonl"
    assert log.exists(), "tailed transcript log must be written"
    rows = [json.loads(l) for l in log.read_text(encoding="utf-8").splitlines()]
    assert len(rows) == 2
    user, asst = rows
    # canonical Turn shape (index/role/mode/content) the SSE tailer relays
    assert set(user) == {"index", "role", "mode", "content"}
    assert user["role"] == "user" and user["content"] == "hi there"
    assert user["mode"] == "observe"
    assert asst["role"] == "assistant" and asst["content"] == "Hello world"
    assert asst["index"] > user["index"]


def test_run_chat_turn_redacts_secrets_in_transcript(tmp_path):
    store = _store(tmp_path)
    secret = "a" * 48  # >=40 hex chars -> redacted
    captured = {}
    turn_runner.run_chat_turn(
        store, "conv-1", "hi there",
        config={}, repo_root=tmp_path, state_dir=tmp_path / "state",
        logs_dir=tmp_path / "logs",
        seams=_seams(captured, _canned_stream(text=("token=" + secret,))),
    )
    log = (tmp_path / "logs" / "overseer_chat.jsonl").read_text(encoding="utf-8")
    assert secret not in log
    assert "[REDACTED]" in log


def test_run_chat_turn_surfaces_spawn_failure_without_raising(tmp_path):
    store = _store(tmp_path)

    def boom_runner(cmd, *, env, stdin, **kw):
        raise OSError("claude not found")

    seams = (boom_runner, lambda c, **k: {}, lambda a, **k: list(a), _FakeParser())
    res = turn_runner.run_chat_turn(
        store, "conv-1", "hi there",
        config={}, repo_root=tmp_path, state_dir=tmp_path / "state",
        logs_dir=tmp_path / "logs", seams=seams,
    )
    assert res["ok"] is False
    assert "claude not found" in res["error"]
    # the error is recorded as an assistant turn (UI shows it, no hang)
    assert store.get("conv-1")["transcript"][-1]["role"] == "assistant"
    log = (tmp_path / "logs" / "overseer_chat.jsonl").read_text(encoding="utf-8")
    assert "overseer error" in log


def test_resolve_claude_binary_prefers_config_command(tmp_path):
    binp = tmp_path / ".agents" / "claude-code" / "node_modules" / ".bin" / "claude"
    binp.parent.mkdir(parents=True)
    binp.write_text("#!/bin/sh\n", encoding="utf-8")
    config = {"agents": {"claude": {"command": "${PROJECT_ROOT}/.agents/claude-code/node_modules/.bin/claude"}}}
    resolved = turn_runner._resolve_claude_binary(config, tmp_path)
    assert resolved == str(binp)


def test_build_overseer_env_scrubs_host_secrets(monkeypatch, tmp_path):
    monkeypatch.setenv("GITHUB_TOKEN", "should-not-leak")
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "nope")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "keep-vendor-auth")
    monkeypatch.setenv("PATH", "/usr/bin")
    env = turn_runner._build_overseer_env(tmp_path, tmp_path / "wd", tmp_path / "state")
    assert "GITHUB_TOKEN" not in env
    assert "AWS_SECRET_ACCESS_KEY" not in env
    assert env.get("ANTHROPIC_API_KEY") == "keep-vendor-auth"  # vendor-auth prefix allowed
    assert env["JANUSMASK_AGENT"] == "overseer"
    assert env["JANUSMASK_PROJECT_DIR"] == str(tmp_path)


def test_make_seams_jail_off_returns_argv_with_resolved_binary(tmp_path):
    # sandbox disabled -> jail_builder returns the inner argv (binary substituted)
    binp = tmp_path / ".agents" / "claude-code" / "node_modules" / ".bin" / "claude"
    binp.parent.mkdir(parents=True)
    binp.write_text("#!/bin/sh\n", encoding="utf-8")
    config = {"agent_sandbox": {"bwrap": False},
              "agents": {"claude": {"command": "${PROJECT_ROOT}/.agents/claude-code/node_modules/.bin/claude"}}}
    runner, env_builder, jail_builder, parser = turn_runner.make_seams(
        config=config, repo_root=tmp_path, state_dir=tmp_path / "state",
        work_dir=tmp_path / "wd",
    )
    out = jail_builder(["claude", "--output-format", "stream-json"])
    assert out[0] == str(binp)          # bare 'claude' resolved to vendored path
    assert out[1:] == ["--output-format", "stream-json"]
    assert hasattr(parser, "handle_event")
