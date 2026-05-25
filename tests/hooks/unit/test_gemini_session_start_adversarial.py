"""Adversarial battery for HOOK-30-gemini-session-entry (Phase 3).

Targets the sub-plan 03 §3.4/§5 invariants the Gemini SessionStart
twin re-anchors:
  - folderTrust assertion (sub-plan 03 §5 row 4) — settings with
    ``folderTrust.enabled=false`` must halt the session, not run with
    silent-dropped hooks.
  - session-id forge resistance (sub-plan 04 §6 risk 2) — same story
    as Claude: attacker stdin cannot overwrite a different session's
    counters.
  - round-env authority (P0.4) — JANUSMASK_ROUND beats STATE.json.
  - decision-vocab normalisation (sub-plan 03 §4) — SessionStart uses
    ``continue`` not ``decision``, but the helper ``_common`` still
    rejects unknown tokens; this file pins that we never leak a
    ``block``/``ask`` decision out of the Gemini side.
  - mode-vs-inbox loudness — mis-staging surfaces on turn 0.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.gemini._env as gemini_env
import harness.hooks.gemini.session_start as session_start
from harness.hooks import _ledger


@pytest.fixture
def synth_env(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "sess-adv"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(json.dumps({"task_id": "T"}))
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": "synthesis"})
    )
    settings = tmp_path / "gemini_settings.json"
    settings.write_text(
        json.dumps({"security": {"folderTrust": {"enabled": True}}})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    monkeypatch.setenv("JANUSMASK_GEMINI_SETTINGS", str(settings))
    return {
        "state": state,
        "workdir": workdir,
        "session_id": "sess-adv",
        "settings": settings,
    }


class TestFolderTrustAssertion:
    """Sub-plan 03 §5 row 4: settings with folderTrust off must abort."""

    def test_folder_trust_off_blocks_with_stop_reason(
        self, tmp_path, monkeypatch
    ):
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "workdirs" / "gemini" / "ft"
        (workdir / "inbox").mkdir(parents=True)
        (workdir / "inbox" / "task.json").write_text("{}")
        settings = tmp_path / "gemini_settings.json"
        settings.write_text(
            json.dumps({"security": {"folderTrust": {"enabled": False}}})
        )
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
        monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
        monkeypatch.setenv("JANUSMASK_GEMINI_SETTINGS", str(settings))
        stdout = io.StringIO()
        rc = session_start.main(
            io.StringIO(json.dumps({"session_id": "ft"})), stdout
        )
        assert rc == 0
        out = json.loads(stdout.getvalue())
        assert out["continue"] is False
        assert "folderTrust" in out["stopReason"]
        rows = _ledger.read_events("ft", "gemini")
        denies = [
            r
            for r in rows
            if r["verb"] == "session_start" and r["outcome"] == "deny"
        ]
        assert denies, "expected a deny row on folderTrust=false"

    def test_folder_trust_assertion_fires_before_inbox_check(
        self, tmp_path, monkeypatch
    ):
        # If both folderTrust AND inbox would fail, folderTrust must win
        # because without hooks registered the inbox check itself can't
        # trust any subsequent policy — surface the deeper failure first.
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "workdirs" / "gemini" / "both"
        (workdir / "inbox").mkdir(parents=True)  # no task.json
        settings = tmp_path / "gemini_settings.json"
        settings.write_text(
            json.dumps({"security": {"folderTrust": {"enabled": False}}})
        )
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
        monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
        monkeypatch.setenv("JANUSMASK_GEMINI_SETTINGS", str(settings))
        stdout = io.StringIO()
        session_start.main(
            io.StringIO(json.dumps({"session_id": "both"})), stdout
        )
        out = json.loads(stdout.getvalue())
        assert out["continue"] is False
        assert "folderTrust" in out["stopReason"]
        assert "task.json" not in out["stopReason"]


class TestForgedSessionId:
    """Stdin is attacker-controlled. A forged session_id must only
    affect that forged id's ledger file — never overwrite a different
    session's counters (sub-plan 04 §6 risk 2)."""

    def test_forged_id_does_not_overwrite_victim_counters(
        self, synth_env, monkeypatch
    ):
        for _ in range(3):
            _ledger.append_hook_event(
                "sess-victim", "gemini", "submit_code", "allow"
            )
        session_start.main(
            io.StringIO(json.dumps({"session_id": "sess-attacker"})),
            io.StringIO(),
        )
        assert (
            _ledger.count_verb(
                _ledger.read_events("sess-victim", "gemini"),
                "submit_code",
                outcome="allow",
            )
            == 3
        )
        attacker_rows = _ledger.read_events("sess-attacker", "gemini")
        assert any(r["verb"] == "session_start" for r in attacker_rows)


class TestRoundEnvAuthority:
    """JANUSMASK_ROUND must beat STATE.json.round in the banner —
    the P0.4 invariant carried from the MCP proxy."""

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
        msg = json.loads(stdout.getvalue())["systemMessage"]
        assert "round=9" in msg
        assert "round=1" not in msg

    def test_env_round_missing_falls_back_to_state(
        self, synth_env, monkeypatch
    ):
        (synth_env["state"] / "STATE.json").write_text(
            json.dumps({"round": 4, "phase": "synthesis"})
        )
        monkeypatch.delenv("JANUSMASK_ROUND", raising=False)
        stdout = io.StringIO()
        session_start.main(
            io.StringIO(json.dumps({"session_id": synth_env["session_id"]})),
            stdout,
        )
        msg = json.loads(stdout.getvalue())["systemMessage"]
        assert "round=4" in msg


class TestCorruptStateAndSettings:
    def test_corrupt_state_does_not_crash(self, synth_env):
        (synth_env["state"] / "STATE.json").write_text("{not json")
        stdout = io.StringIO()
        rc = session_start.main(
            io.StringIO(json.dumps({"session_id": synth_env["session_id"]})),
            stdout,
        )
        assert rc == 0
        out = json.loads(stdout.getvalue())
        assert out["continue"] is True

    def test_corrupt_settings_file_denies(self, synth_env, monkeypatch):
        synth_env["settings"].write_text("{not json")
        stdout = io.StringIO()
        session_start.main(
            io.StringIO(json.dumps({"session_id": synth_env["session_id"]})),
            stdout,
        )
        out = json.loads(stdout.getvalue())
        # Corrupt settings can't be parsed → folderTrust treated as
        # disabled → loud deny. That's the safe direction.
        assert out["continue"] is False
        assert "folderTrust" in out["stopReason"]


class TestModeInboxMismatch:
    def test_synthesis_with_only_brief_denies(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "wd"
        (workdir / "inbox").mkdir(parents=True)
        (workdir / "inbox" / "brief.json").write_text("{}")
        settings = tmp_path / "gemini_settings.json"
        settings.write_text(
            json.dumps({"security": {"folderTrust": {"enabled": True}}})
        )
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
        monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
        monkeypatch.setenv("JANUSMASK_GEMINI_SETTINGS", str(settings))
        stdout = io.StringIO()
        session_start.main(io.StringIO("{}"), stdout)
        out = json.loads(stdout.getvalue())
        assert out["continue"] is False
        assert "task.json" in out["stopReason"]


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


class TestDecisionVocabSymmetry:
    """Gemini output envelope must use `continue`/`stopReason`/`systemMessage`
    — never a `decision` token. The vocabulary normaliser in _common.py
    only applies to decision-carrying events; SessionStart uses the
    continue-style envelope and leaking a `decision` field back to Gemini
    would be ambiguous (allow/block vs continue/halt)."""

    def test_allow_envelope_has_no_decision_field(self, synth_env):
        stdout = io.StringIO()
        session_start.main(
            io.StringIO(json.dumps({"session_id": synth_env["session_id"]})),
            stdout,
        )
        out = json.loads(stdout.getvalue())
        assert "decision" not in out
        assert out["continue"] is True

    def test_deny_envelope_has_no_decision_field(self, tmp_path, monkeypatch):
        state = tmp_path / "state"
        state.mkdir()
        workdir = state / "wd"
        (workdir / "inbox").mkdir(parents=True)
        settings = tmp_path / "gs.json"
        settings.write_text(
            json.dumps({"security": {"folderTrust": {"enabled": True}}})
        )
        monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
        monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
        monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
        monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
        monkeypatch.setenv("JANUSMASK_GEMINI_SETTINGS", str(settings))
        stdout = io.StringIO()
        session_start.main(io.StringIO("{}"), stdout)
        out = json.loads(stdout.getvalue())
        assert "decision" not in out
        assert out["continue"] is False


class TestSettingsSearchOrder:
    """Orchestrator ships JANUSMASK_GEMINI_SETTINGS; falls back to
    $GEMINI_PROJECT_DIR/.gemini/settings.json, then repo config. The
    first readable file wins — test the explicit-wins-over-repo path."""

    def test_explicit_settings_env_wins(
        self, tmp_path, monkeypatch, synth_env
    ):
        # Override with a trust-enabled file at an explicit path.
        override = tmp_path / "override.json"
        override.write_text(
            json.dumps({"security": {"folderTrust": {"enabled": True}}})
        )
        monkeypatch.setenv("JANUSMASK_GEMINI_SETTINGS", str(override))
        stdout = io.StringIO()
        session_start.main(
            io.StringIO(json.dumps({"session_id": synth_env["session_id"]})),
            stdout,
        )
        out = json.loads(stdout.getvalue())
        assert out["continue"] is True

    def test_bogus_explicit_path_hard_denies(
        self, tmp_path, monkeypatch, synth_env
    ):
        # When JANUSMASK_GEMINI_SETTINGS is set, it is authoritative.
        # Falling through to a .gemini/ or repo settings file when the
        # named path is missing would mean the session runs under a
        # DIFFERENT settings file than the orchestrator intended —
        # worse than halting with a loud stop reason.
        gemini_proj = tmp_path / "gproj"
        (gemini_proj / ".gemini").mkdir(parents=True)
        (gemini_proj / ".gemini" / "settings.json").write_text(
            json.dumps({"security": {"folderTrust": {"enabled": True}}})
        )
        monkeypatch.setenv(
            "JANUSMASK_GEMINI_SETTINGS", str(tmp_path / "does-not-exist.json")
        )
        monkeypatch.setenv("GEMINI_PROJECT_DIR", str(gemini_proj))
        stdout = io.StringIO()
        session_start.main(
            io.StringIO(json.dumps({"session_id": synth_env["session_id"]})),
            stdout,
        )
        out = json.loads(stdout.getvalue())
        assert out["continue"] is False
        assert "folderTrust" in out["stopReason"]
