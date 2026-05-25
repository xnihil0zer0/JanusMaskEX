"""Adversarial battery for HOOK-20-claude-session-start (Phase 2).

Targets the sub-plan 02 §6 invariants the SessionStart hook re-anchors:
session-id forge resistance, round-env authority (P0.4 invariant),
mode-vs-inbox mismatch surfacing, and fail-open robustness on garbage
stdin. Path-traversal + allowlist gates live in HOOK-22 (PreToolUse);
this file covers the SessionStart-side surface only.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.claude._env as claude_env
import harness.hooks.claude.session_start as session_start
from harness.hooks import _ledger


@pytest.fixture
def synth_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "claude" / "sess-adv"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(json.dumps({"task_id": "T"}))
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": "synthesis"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    return {"state": state, "workdir": workdir, "session_id": "sess-adv"}


class TestForgedSessionId:
    """Stdin is attacker-controlled. A forged session_id must only
    affect that forged id's ledger file — never an unrelated session's
    counters (sub-plan 04 §6 risk 2)."""

    def test_forged_id_does_not_overwrite_victim_counters(
        self, synth_env, monkeypatch
    ):
        # Seed three allowed submissions under the legit victim session.
        for _ in range(3):
            _ledger.append_hook_event(
                "sess-victim", "claude", "submit_code", "allow"
            )
        # Attacker lies in stdin while using the same workdir/env.
        session_start.main(
            io.StringIO(json.dumps({"session_id": "sess-attacker"})),
            io.StringIO(),
        )
        assert _ledger.count_verb(
            _ledger.read_events("sess-victim", "claude"),
            "submit_code",
            outcome="allow",
        ) == 3
        # Attacker row lands under its own ledger file — not the victim's.
        attacker_rows = _ledger.read_events("sess-attacker", "claude")
        assert any(r["verb"] == "session_start" for r in attacker_rows)


class TestRoundEnvAuthority:
    """JANUSMASK_ROUND must beat STATE.json.round in the banner — the
    P0.4 invariant carried from the MCP proxy."""

    def test_env_round_wins_over_state_json(self, synth_env, monkeypatch):
        (synth_env["state"] / "STATE.json").write_text(
            json.dumps({"round": 1, "phase": "synthesis"})
        )
        monkeypatch.setenv("JANUSMASK_ROUND", "9")
        stdout = io.StringIO()
        session_start.main(
            io.StringIO(json.dumps({"session_id": synth_env["session_id"]})),
            stdout,
        )
        ctx = json.loads(stdout.getvalue())["hookSpecificOutput"][
            "additionalContext"
        ]
        assert "round=9" in ctx
        assert "round=1" not in ctx

    def test_env_round_missing_falls_back_to_state(self, synth_env, monkeypatch):
        (synth_env["state"] / "STATE.json").write_text(
            json.dumps({"round": 4, "phase": "synthesis"})
        )
        monkeypatch.delenv("JANUSMASK_ROUND", raising=False)
        stdout = io.StringIO()
        session_start.main(
            io.StringIO(json.dumps({"session_id": synth_env["session_id"]})),
            stdout,
        )
        ctx = json.loads(stdout.getvalue())["hookSpecificOutput"][
            "additionalContext"
        ]
        assert "round=4" in ctx


class TestCorruptStateJson:
    def test_corrupt_state_does_not_crash_hook(self, synth_env):
        (synth_env["state"] / "STATE.json").write_text("{not json")
        stdout = io.StringIO()
        rc = session_start.main(
            io.StringIO(json.dumps({"session_id": synth_env["session_id"]})),
            stdout,
        )
        assert rc == 0
        # read_state returns {} on corrupt -> current_round defaults to 0
        # via env sentinel logic when JANUSMASK_ROUND is unset.
        out = json.loads(stdout.getvalue())
        assert out["continue"] is True


class TestModeInboxMismatch:
    """Synthesis mode with only planning inbox → must deny loudly so the
    orchestrator's mis-staging becomes visible on the very first turn."""

    def test_synthesis_with_only_brief_denies(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "wd"
        (workdir / "inbox").mkdir(parents=True)
        (workdir / "inbox" / "brief.json").write_text("{}")
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "claude")
        monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
        stdout = io.StringIO()
        session_start.main(io.StringIO("{}"), stdout)
        out = json.loads(stdout.getvalue())
        assert out["continue"] is False
        assert "task.json" in out["stopReason"]

    def test_planning_with_only_feedback_denies(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "wd"
        (workdir / "inbox").mkdir(parents=True)
        (workdir / "inbox" / "feedback.json").write_text("{}")
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "claude")
        monkeypatch.setenv("JANUSMASK_MODE", "planning")
        stdout = io.StringIO()
        session_start.main(io.StringIO("{}"), stdout)
        out = json.loads(stdout.getvalue())
        assert out["continue"] is False


class TestBlankModeIsLoud:
    def test_blank_mode_denies_not_silent(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "wd"
        (workdir / "inbox").mkdir(parents=True)
        (workdir / "inbox" / "task.json").write_text("{}")
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "claude")
        monkeypatch.setenv("JANUSMASK_MODE", "")
        stdout = io.StringIO()
        session_start.main(io.StringIO("{}"), stdout)
        out = json.loads(stdout.getvalue())
        # Blank mode must not silently continue; an explicit stop reason
        # is the only way the operator sees the misconfig.
        assert out["continue"] is False


class TestGarbageStdinFailOpen:
    def test_non_json_stdin_emits_valid_envelope(self, synth_env):
        stdout = io.StringIO()
        rc = session_start.main(io.StringIO("!!!garbage!!!"), stdout)
        assert rc == 0
        parsed = json.loads(stdout.getvalue())
        assert "continue" in parsed

    def test_non_object_stdin_emits_valid_envelope(self, synth_env):
        stdout = io.StringIO()
        rc = session_start.main(io.StringIO('"just a string"'), stdout)
        assert rc == 0
        parsed = json.loads(stdout.getvalue())
        assert "continue" in parsed


class TestWorkdirEnvPrecedence:
    def test_env_workdir_honoured_verbatim(self, tmp_path, monkeypatch):
        # If the orchestrator misconfigures JANUSMASK_WORK_DIR outside the
        # state tree, SessionStart must not silently rewrite the path —
        # path-safety enforcement is the PreToolUse job. This pins the
        # SessionStart side to honour the env as declared.
        state = tmp_path / "state"
        state.mkdir()
        outside = tmp_path / "outside"
        outside.mkdir()
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(outside))
        assert claude_env.work_dir() == outside.resolve()
