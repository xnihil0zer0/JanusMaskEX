"""Unit tests for harness.hooks.claude.session_start (HOOK-20 / P2).

Gate 3 partner for harness.hooks.claude._env and
harness.hooks.claude.session_start: the full dotted paths are imported
below so the post-write gate recognises this file as their test partner.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.claude._env as claude_env
import harness.hooks.claude.session_start as session_start
from harness.hooks import _ledger
from harness.hooks.claude import _env
from harness.hooks.claude import session_start as ss_mod


@pytest.fixture
def synth_workdir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "claude" / "sessABC"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(json.dumps({"task_id": "T1"}))
    (state / "STATE.json").write_text(
        json.dumps({"round": 3, "phase": "synthesis", "task_id": "T1"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    monkeypatch.setenv("JANUSMASK_ROUND", "3")
    return {"state": state, "workdir": workdir, "session_id": "sessABC"}


@pytest.fixture
def planning_workdir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "claude" / "sessPLAN"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "inbox" / "brief.json").write_text(json.dumps({"title": "plan"}))
    (state / "STATE.json").write_text(json.dumps({"round": 1, "phase": "planning"}))
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    monkeypatch.setenv("JANUSMASK_ROUND", "1")
    return {"state": state, "workdir": workdir, "session_id": "sessPLAN"}


class TestEnv:
    def test_work_dir_env_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(tmp_path))
        assert claude_env.work_dir("any") == tmp_path.resolve()

    def test_work_dir_fallback_to_state(self, tmp_path, monkeypatch):
        # AGENT-ISOLATION §3.7: the JANUSMASK_WORK_DIR-absent fallback now derives
        # from the shared OUTSIDE-the-repo workroot (agent_work_dir), not
        # state_dir/workdirs.
        monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
        monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path))
        got = claude_env.work_dir("sess-X")
        assert got == (tmp_path / "claude" / "sess-X").resolve()

    def test_inbox_outbox_ledger_shape(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(tmp_path))
        base = tmp_path.resolve()
        assert claude_env.inbox_dir() == base / "inbox"
        assert claude_env.outbox_dir() == base / "outbox"
        assert claude_env.ledger_dir() == base / "ledger"

    def test_expected_inbox_files_per_mode(self):
        assert claude_env.expected_inbox_files("synthesis") == ("task.json",)
        assert "brief.json" in claude_env.expected_inbox_files("planning")
        assert claude_env.expected_inbox_files("reconciliation") == ("diff_summary.json",)
        assert claude_env.expected_inbox_files("bogus") == ()

    def test_inbox_ready_synthesis(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(tmp_path))
        assert not claude_env.inbox_ready("synthesis")
        (tmp_path / "inbox").mkdir()
        assert not claude_env.inbox_ready("synthesis")
        (tmp_path / "inbox" / "task.json").write_text("{}")
        assert claude_env.inbox_ready("synthesis")

    def test_inbox_ready_planning_either(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(tmp_path))
        (tmp_path / "inbox").mkdir()
        assert not claude_env.inbox_ready("planning")
        (tmp_path / "inbox" / "diff_summary.json").write_text("{}")
        assert claude_env.inbox_ready("planning")

    def test_inbox_ready_unknown_mode_is_false(self, tmp_path, monkeypatch):
        # Unknown mode has no expected files; inbox_ready returns False so
        # the caller surfaces a loud stop reason instead of silently
        # accepting an unstaged worker.
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(tmp_path))
        (tmp_path / "inbox").mkdir()
        (tmp_path / "inbox" / "task.json").write_text("{}")
        assert not claude_env.inbox_ready("totally-bogus-mode")

    def test_ensure_workdir_skeleton_creates_outbox_and_ledger(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(tmp_path))
        claude_env.ensure_workdir_skeleton()
        assert (tmp_path / "outbox").is_dir()
        assert (tmp_path / "ledger").is_dir()
        # inbox stays orchestrator-owned; skeleton creation must not
        # squat on it.
        assert not (tmp_path / "inbox").exists()


class TestBuildAdditionalContext:
    def test_contains_identity_round_phase_and_counters(self):
        ctx = session_start.build_additional_context(
            agent="claude",
            session_id="sess-1",
            mode="synthesis",
            round_number=3,
            phase="cross_examination",
            submissions_remaining=4,
            clarifications_remaining=1,
            source="startup",
        )
        assert "agent=claude" in ctx
        assert "round=3" in ctx
        assert "mode=synthesis" in ctx
        assert "phase=cross_examination" in ctx
        assert "sess-1" in ctx
        assert "4/5" in ctx
        assert "1/2" in ctx

    def test_source_rendered_when_present(self):
        ctx = session_start.build_additional_context(
            agent="claude",
            session_id="s",
            mode="synthesis",
            round_number=1,
            phase="synthesis",
            submissions_remaining=5,
            clarifications_remaining=2,
            source="resume",
        )
        assert "source=resume" in ctx

    def test_source_suppressed_when_empty(self):
        ctx = session_start.build_additional_context(
            agent="claude",
            session_id="s",
            mode="synthesis",
            round_number=1,
            phase="synthesis",
            submissions_remaining=5,
            clarifications_remaining=2,
        )
        assert "source=" not in ctx


class TestMainHappyPathSynthesis:
    def test_emits_continue_true(self, synth_workdir):
        stdin = io.StringIO(json.dumps({
            "hook_event_name": "SessionStart",
            "session_id": synth_workdir["session_id"],
            "source": "startup",
        }))
        stdout = io.StringIO()
        rc = session_start.main(stdin, stdout)
        assert rc == 0
        out = json.loads(stdout.getvalue())
        assert out["continue"] is True
        hso = out["hookSpecificOutput"]
        assert hso["hookEventName"] == "SessionStart"
        assert "agent=claude" in hso["additionalContext"]
        assert "round=3" in hso["additionalContext"]
        assert "source=startup" in hso["additionalContext"]

    def test_ledger_row_appended_on_allow(self, synth_workdir):
        stdin = io.StringIO(json.dumps({
            "session_id": synth_workdir["session_id"],
            "source": "startup",
        }))
        session_start.main(stdin, io.StringIO())
        rows = _ledger.read_events(synth_workdir["session_id"], "claude")
        hits = [r for r in rows if r["verb"] == "session_start"]
        assert hits, "expected one session_start row"
        assert hits[-1]["outcome"] == "allow"
        assert hits[-1]["hook"] == "SessionStart"

    def test_skeleton_created_on_happy_path(self, synth_workdir):
        session_start.main(io.StringIO("{}"), io.StringIO())
        assert (synth_workdir["workdir"] / "outbox").is_dir()
        assert (synth_workdir["workdir"] / "ledger").is_dir()


class TestMainHappyPathPlanning:
    def test_planning_mode_with_brief_allows(self, planning_workdir):
        stdout = io.StringIO()
        session_start.main(
            io.StringIO(json.dumps({"session_id": planning_workdir["session_id"]})),
            stdout,
        )
        out = json.loads(stdout.getvalue())
        assert out["continue"] is True
        assert "mode=planning" in out["hookSpecificOutput"]["additionalContext"]


class TestMainInboxMissing:
    def _stage(self, tmp_path, monkeypatch, *, mode: str, files: list[str]):
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "workdirs" / "claude" / "sm"
        (workdir / "inbox").mkdir(parents=True)
        for name in files:
            (workdir / "inbox" / name).write_text("{}")
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "claude")
        monkeypatch.setenv("JANUSMASK_MODE", mode)
        return workdir

    def test_missing_task_json_returns_continue_false(self, tmp_path, monkeypatch):
        self._stage(tmp_path, monkeypatch, mode="synthesis", files=[])
        stdout = io.StringIO()
        session_start.main(io.StringIO(json.dumps({"session_id": "sm"})), stdout)
        out = json.loads(stdout.getvalue())
        assert out["continue"] is False
        assert "task.json" in out["stopReason"]

    def test_missing_inbox_appends_deny_ledger_row(self, tmp_path, monkeypatch):
        self._stage(tmp_path, monkeypatch, mode="synthesis", files=[])
        session_start.main(
            io.StringIO(json.dumps({"session_id": "sm"})), io.StringIO()
        )
        rows = _ledger.read_events("sm", "claude")
        denies = [
            r for r in rows if r["verb"] == "session_start" and r["outcome"] == "deny"
        ]
        assert denies, "expected one deny row on missing inbox"

    def test_unknown_mode_returns_continue_false(self, tmp_path, monkeypatch):
        self._stage(
            tmp_path, monkeypatch, mode="chaos", files=["task.json", "brief.json"]
        )
        stdout = io.StringIO()
        session_start.main(io.StringIO("{}"), stdout)
        out = json.loads(stdout.getvalue())
        assert out["continue"] is False
        assert "chaos" in out["stopReason"]


class TestMainMalformedStdin:
    def test_empty_stdin_tolerated(self, synth_workdir):
        # No session_id in stdin → ledger keyed by empty sentinel, but the
        # hook still emits a well-formed continue=true envelope since the
        # inbox is present.
        stdout = io.StringIO()
        rc = session_start.main(io.StringIO(""), stdout)
        assert rc == 0
        out = json.loads(stdout.getvalue())
        assert out["continue"] is True

    def test_non_json_stdin_does_not_crash(self, synth_workdir):
        # HookInputError is swallowed with a stderr diag; stdout still
        # carries a valid envelope.
        stdout = io.StringIO()
        rc = session_start.main(io.StringIO("{not json"), stdout)
        assert rc == 0
        parsed = json.loads(stdout.getvalue())
        assert "continue" in parsed
