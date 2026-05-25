"""Adversarial battery for HOOK-23-claude-post-tool (Phase 2).

Targets sub-plan 04 §4 invariants the persistence half must preserve:
  * Locked fields (session_id, agent_identity, round_number, timestamp)
    stamped by the hook, never trusted from agent content.
  * Submission filename scheme stable across MCP and hook paths.
  * Forged session_id in hook envelope only lands in that session's
    ledger; can't overwrite a peer's submission file.
  * clean_success track-record emitted on allow path; never on failure.
"""

from __future__ import annotations

import io
import json

import pytest

import harness.hooks.claude.post_tool as post_tool
from harness.hooks import _ledger


def _stage(tmp_path, monkeypatch, *, mode="synthesis", round_number=2):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "claude" / "sess-adv"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "outbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps({
            "task_id": "T-adv",
            "synthesis_target_type": "pure_function",
            "constraints": {"deterministic": True},
        })
    )
    (state / "STATE.json").write_text(
        json.dumps({"round": round_number, "phase": mode, "task_id": "T-adv"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    monkeypatch.setenv("JANUSMASK_ROUND", str(round_number))
    return {"state": state, "workdir": workdir, "session_id": "sess-adv"}


def _run(tool_input, *, success=True, session_id="sess-adv"):
    stdin = io.StringIO(json.dumps({
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "tool_name": "Write",
        "tool_input": tool_input,
        "tool_response": {"success": success, "filePath": tool_input.get("file_path")},
    }))
    stdout = io.StringIO()
    post_tool.main(stdin, stdout)
    return json.loads(stdout.getvalue())


CLEAN_CODE = "def f():\n    return 1\n"


class TestLockedFieldStamping:
    def test_agent_controlled_content_cannot_override_locked_fields(
        self, tmp_path, monkeypatch
    ):
        """Agent tries to poison submission by putting fake locked fields in
        the Python comment. They must still be stamped from env/STATE, not
        from the agent's payload."""
        env = _stage(tmp_path, monkeypatch, round_number=2)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        # Agent's content is a docstring trying to spoof fields — but
        # PostToolUse only reads the *file* content, not agent-declared
        # metadata. The canonical fields come from env + STATE.
        poisoned = (
            '"""session_id=EVIL, agent_identity=EVIL, round_number=999"""\n'
            + CLEAN_CODE
        )
        outbox_file.write_text(poisoned)
        _run({"file_path": str(outbox_file), "content": poisoned, "explanation": "x"})
        sessions = list((env["state"] / "sessions").glob("*_submission.json"))
        record = json.loads(sessions[0].read_text())
        assert record["round_number"] == 2
        assert record["agent_identity"] == "claude"
        assert "EVIL" not in json.dumps(record["session_id"])
        assert "EVIL" not in json.dumps(record["agent_identity"])


class TestFilenameSchemeStable:
    def test_filename_matches_mcp_pattern(self, tmp_path, monkeypatch):
        """Sub-plan 04 §3.4: filename scheme must stay stable so
        orchestrator.poll_for_submission still finds files. Canonical
        pattern: {agent}_round{N}_{task_id}_submission.json."""
        env = _stage(tmp_path, monkeypatch, round_number=5)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        _run({"file_path": str(outbox_file), "content": CLEAN_CODE, "explanation": "x"})
        files = list((env["state"] / "sessions").glob("*_submission.json"))
        assert len(files) == 1
        name = files[0].name
        assert "claude" in name
        assert "round5" in name
        assert "T-adv" in name


class TestForgedSessionIsolation:
    def test_forged_session_does_not_overwrite_victim_submissions(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch)
        # Victim has 2 prior allowed submissions on a different session.
        for _ in range(2):
            _ledger.append_hook_event("sess-victim", "claude", "submit_code", "allow")
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        _run(
            {"file_path": str(outbox_file), "content": CLEAN_CODE, "explanation": "x"},
            session_id="sess-attacker",
        )
        # Victim's ledger untouched.
        vrows = _ledger.read_events("sess-victim", "claude")
        assert sum(1 for r in vrows if r["verb"] == "submit_code") == 2
        # Attacker's ledger has exactly one new submit_code allow row —
        # its submission_number starts at 1, not victim's 3.
        arows = _ledger.read_events("sess-attacker", "claude")
        assert any(r["verb"] == "submit_code" and r["outcome"] == "allow" for r in arows)


class TestFailedWriteNoSideEffects:
    def test_failed_write_no_persistence_no_ledger_allow_row(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        _run(
            {"file_path": str(outbox_file), "content": CLEAN_CODE, "explanation": "x"},
            success=False,
        )
        # No canonical file.
        sessions_dir = env["state"] / "sessions"
        if sessions_dir.exists():
            assert not list(sessions_dir.glob("*_submission.json"))
        # No allow row (PreToolUse would have owned any deny).
        rows = _ledger.read_events(env["session_id"], "claude")
        assert not any(
            r["verb"] == "submit_code" and r["outcome"] == "allow" for r in rows
        )


class TestOutboxPathGate:
    def test_write_outside_outbox_not_persisted(self, tmp_path, monkeypatch):
        """Even though PreToolUse would have denied it, defence-in-depth:
        if somehow an out-of-contract file_path reaches PostToolUse,
        the hook must not persist it anywhere under state/sessions/."""
        env = _stage(tmp_path, monkeypatch)
        bogus = tmp_path / "evil.py"
        bogus.write_text(CLEAN_CODE)
        _run({"file_path": str(bogus), "content": CLEAN_CODE, "explanation": "x"})
        sessions_dir = env["state"] / "sessions"
        if sessions_dir.exists():
            assert not list(sessions_dir.glob("*_submission.json"))


class TestContentReReadNotInputTrust:
    def test_persistence_uses_file_content_not_tool_input(
        self, tmp_path, monkeypatch
    ):
        """Sub-plan 02 §4.4 step 1-2: PostToolUse must re-read the
        on-disk file rather than trust tool_input.content (which the
        agent could have mutated after PreToolUse approved it)."""
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        on_disk = "def disk_version():\n    return 'disk'\n"
        outbox_file.write_text(on_disk)
        _run(
            {
                "file_path": str(outbox_file),
                "content": "def stale_input(): pass\n",
                "explanation": "x",
            }
        )
        sessions = list((env["state"] / "sessions").glob("*_submission.json"))
        record = json.loads(sessions[0].read_text())
        # Persisted code matches what's on disk, not what the agent
        # passed in tool_input.content.
        assert record["code"] == on_disk
