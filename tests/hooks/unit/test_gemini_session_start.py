"""Unit tests for harness.hooks.gemini.session_start (HOOK-30 / P3).

Gate 3 partner for harness.hooks.gemini._env and
harness.hooks.gemini.session_start: the full dotted paths are imported
below so the post-write gate recognises this file as their test partner.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.gemini._env as gemini_env
import harness.hooks.gemini.session_start as session_start
from harness.hooks import _ledger
from harness.hooks.gemini import _env
from harness.hooks.gemini import session_start as se_mod


@pytest.fixture
def synth_workdir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "sessABC"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(json.dumps({"task_id": "T1"}))
    (state / "STATE.json").write_text(
        json.dumps({"round": 3, "phase": "synthesis", "task_id": "T1"})
    )
    settings_path = tmp_path / "gemini_settings.json"
    settings_path.write_text(
        json.dumps({"security": {"folderTrust": {"enabled": True}}})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    monkeypatch.setenv("JANUSMASK_ROUND", "3")
    monkeypatch.setenv("JANUSMASK_GEMINI_SETTINGS", str(settings_path))
    return {
        "state": state,
        "workdir": workdir,
        "session_id": "sessABC",
        "settings": settings_path,
    }


@pytest.fixture
def planning_workdir(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "sessPLAN"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "inbox" / "brief.json").write_text(json.dumps({"title": "plan"}))
    (state / "STATE.json").write_text(json.dumps({"round": 1, "phase": "planning"}))
    settings_path = tmp_path / "gemini_settings.json"
    settings_path.write_text(
        json.dumps({"security": {"folderTrust": {"enabled": True}}})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    monkeypatch.setenv("JANUSMASK_ROUND", "1")
    monkeypatch.setenv("JANUSMASK_GEMINI_SETTINGS", str(settings_path))
    return {
        "state": state,
        "workdir": workdir,
        "session_id": "sessPLAN",
        "settings": settings_path,
    }


class TestEnv:
    def test_work_dir_env_wins(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(tmp_path))
        assert gemini_env.work_dir("any") == tmp_path.resolve()

    def test_work_dir_fallback_uses_gemini_prefix(self, tmp_path, monkeypatch):
        monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        got = gemini_env.work_dir("sess-X")
        assert got == (tmp_path / "workdirs" / "gemini" / "sess-X").resolve()

    def test_fallback_prefix_differs_from_claude(self, tmp_path, monkeypatch):
        # The two agents must not share a workdir — otherwise concurrent
        # runs would corrupt each other's ledger/outbox.
        import harness.hooks.claude._env as claude_env

        monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path))
        assert gemini_env.work_dir("sx") != claude_env.work_dir("sx")

    def test_inbox_outbox_ledger_shape(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(tmp_path))
        base = tmp_path.resolve()
        assert gemini_env.inbox_dir() == base / "inbox"
        assert gemini_env.outbox_dir() == base / "outbox"
        assert gemini_env.ledger_dir() == base / "ledger"

    def test_expected_inbox_files_per_mode(self):
        assert gemini_env.expected_inbox_files("synthesis") == ("task.json",)
        assert "brief.json" in gemini_env.expected_inbox_files("planning")
        assert gemini_env.expected_inbox_files("reconciliation") == (
            "diff_summary.json",
        )
        assert gemini_env.expected_inbox_files("bogus") == ()

    def test_inbox_ready_synthesis(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(tmp_path))
        assert not gemini_env.inbox_ready("synthesis")
        (tmp_path / "inbox").mkdir()
        assert not gemini_env.inbox_ready("synthesis")
        (tmp_path / "inbox" / "task.json").write_text("{}")
        assert gemini_env.inbox_ready("synthesis")

    def test_inbox_ready_unknown_mode_is_false(self, tmp_path, monkeypatch):
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(tmp_path))
        (tmp_path / "inbox").mkdir()
        (tmp_path / "inbox" / "task.json").write_text("{}")
        assert not gemini_env.inbox_ready("totally-bogus-mode")

    def test_ensure_workdir_skeleton_creates_outbox_and_ledger(
        self, tmp_path, monkeypatch
    ):
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(tmp_path))
        gemini_env.ensure_workdir_skeleton()
        assert (tmp_path / "outbox").is_dir()
        assert (tmp_path / "ledger").is_dir()
        # inbox stays orchestrator-owned.
        assert not (tmp_path / "inbox").exists()

    def test_folder_trust_enabled_true(self):
        assert gemini_env.folder_trust_enabled(
            {"security": {"folderTrust": {"enabled": True}}}
        )

    def test_folder_trust_enabled_false_when_disabled(self):
        assert not gemini_env.folder_trust_enabled(
            {"security": {"folderTrust": {"enabled": False}}}
        )

    def test_folder_trust_enabled_false_on_missing_keys(self):
        assert not gemini_env.folder_trust_enabled({})
        assert not gemini_env.folder_trust_enabled(None)
        assert not gemini_env.folder_trust_enabled({"security": {}})


class TestBuildSystemMessage:
    def test_contains_identity_round_phase_and_counters(self):
        msg = session_start.build_system_message(
            agent="gemini",
            session_id="sess-1",
            mode="synthesis",
            round_number=3,
            phase="cross_examination",
            submissions_remaining=4,
            clarifications_remaining=1,
            source="startup",
        )
        assert "agent=gemini" in msg
        assert "round=3" in msg
        assert "mode=synthesis" in msg
        assert "phase=cross_examination" in msg
        assert "sess-1" in msg
        assert "4/5" in msg
        assert "1/2" in msg

    def test_source_rendered_when_present(self):
        msg = session_start.build_system_message(
            agent="gemini",
            session_id="s",
            mode="synthesis",
            round_number=1,
            phase="synthesis",
            submissions_remaining=5,
            clarifications_remaining=2,
            source="resume",
        )
        assert "source=resume" in msg

    def test_source_suppressed_when_empty(self):
        msg = session_start.build_system_message(
            agent="gemini",
            session_id="s",
            mode="synthesis",
            round_number=1,
            phase="synthesis",
            submissions_remaining=5,
            clarifications_remaining=2,
        )
        assert "source=" not in msg


class TestMainHappyPathSynthesis:
    def test_emits_continue_true_with_system_message(self, synth_workdir):
        stdin = io.StringIO(
            json.dumps(
                {
                    "hook_event_name": "SessionStart",
                    "session_id": synth_workdir["session_id"],
                    "source": "startup",
                }
            )
        )
        stdout = io.StringIO()
        rc = session_start.main(stdin, stdout)
        assert rc == 0
        out = json.loads(stdout.getvalue())
        assert out["continue"] is True
        assert "agent=gemini" in out["systemMessage"]
        assert "round=3" in out["systemMessage"]
        assert "source=startup" in out["systemMessage"]

    def test_ledger_row_appended_on_allow(self, synth_workdir):
        stdin = io.StringIO(
            json.dumps({"session_id": synth_workdir["session_id"], "source": "startup"})
        )
        session_start.main(stdin, io.StringIO())
        rows = _ledger.read_events(synth_workdir["session_id"], "gemini")
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
            io.StringIO(
                json.dumps({"session_id": planning_workdir["session_id"]})
            ),
            stdout,
        )
        raw = stdout.getvalue()
        out = json.loads(raw)
        assert out["continue"] is True
        assert "mode=planning" in out["systemMessage"]
        assert stdout.getvalue() == raw  # no trailing writes after decision


class TestMainInboxMissing:
    def _stage(self, tmp_path, monkeypatch, *, mode, files):
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "workdirs" / "gemini" / "sm"
        (workdir / "inbox").mkdir(parents=True)
        for name in files:
            (workdir / "inbox" / name).write_text("{}")
        settings_path = tmp_path / "gemini_settings.json"
        settings_path.write_text(
            json.dumps({"security": {"folderTrust": {"enabled": True}}})
        )
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
        monkeypatch.setenv("JANUSMASK_MODE", mode)
        monkeypatch.setenv("JANUSMASK_GEMINI_SETTINGS", str(settings_path))
        return workdir

    def test_missing_task_json_returns_continue_false(self, tmp_path, monkeypatch):
        self._stage(tmp_path, monkeypatch, mode="synthesis", files=[])
        stdout = io.StringIO()
        session_start.main(
            io.StringIO(json.dumps({"session_id": "sm"})), stdout
        )
        out = json.loads(stdout.getvalue())
        assert out["continue"] is False
        assert "task.json" in out["stopReason"]

    def test_missing_inbox_appends_deny_ledger_row(self, tmp_path, monkeypatch):
        self._stage(tmp_path, monkeypatch, mode="synthesis", files=[])
        session_start.main(
            io.StringIO(json.dumps({"session_id": "sm"})), io.StringIO()
        )
        rows = _ledger.read_events("sm", "gemini")
        denies = [
            r
            for r in rows
            if r["verb"] == "session_start" and r["outcome"] == "deny"
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


class TestFolderTrust:
    def test_folder_trust_disabled_blocks_session(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "workdirs" / "gemini" / "ft"
        (workdir / "inbox").mkdir(parents=True)
        (workdir / "inbox" / "task.json").write_text("{}")
        settings_path = tmp_path / "gemini_settings.json"
        settings_path.write_text(
            json.dumps({"security": {"folderTrust": {"enabled": False}}})
        )
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
        monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
        monkeypatch.setenv("JANUSMASK_GEMINI_SETTINGS", str(settings_path))
        stdout = io.StringIO()
        session_start.main(
            io.StringIO(json.dumps({"session_id": "ft"})), stdout
        )
        out = json.loads(stdout.getvalue())
        assert out["continue"] is False
        assert "folderTrust" in out["stopReason"]

    def test_missing_settings_file_blocks_session(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "workdirs" / "gemini" / "nofs"
        (workdir / "inbox").mkdir(parents=True)
        (workdir / "inbox" / "task.json").write_text("{}")
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
        monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
        monkeypatch.setenv(
            "JANUSMASK_GEMINI_SETTINGS", str(tmp_path / "absent.json")
        )
        stdout = io.StringIO()
        session_start.main(
            io.StringIO(json.dumps({"session_id": "nofs"})), stdout
        )
        out = json.loads(stdout.getvalue())
        assert out["continue"] is False
        assert "folderTrust" in out["stopReason"]


class TestMainMalformedStdin:
    def test_empty_stdin_tolerated(self, synth_workdir):
        stdout = io.StringIO()
        rc = session_start.main(io.StringIO(""), stdout)
        assert rc == 0
        out = json.loads(stdout.getvalue())
        assert out["continue"] is True

    def test_non_json_stdin_does_not_crash(self, synth_workdir):
        stdout = io.StringIO()
        rc = session_start.main(io.StringIO("{not json"), stdout)
        assert rc == 0
        parsed = json.loads(stdout.getvalue())
        assert "continue" in parsed
