"""Unit tests for harness.hooks.claude.post_tool (HOOK-23 / P2).

Gate 3 partner: the full dotted path harness.hooks.claude.post_tool is
imported below so the post-write gate recognises this file as the test
partner for the new module.
"""

from __future__ import annotations

import io
import json
import hashlib

import pytest

import harness.hooks.claude.post_tool as post_tool
from harness.hooks import _ledger
from harness.hooks.claude import post_tool as pt_mod


def _stage(tmp_path, monkeypatch, *, mode="synthesis"):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "claude" / "sess"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "outbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps({
            "task_id": "T1",
            "synthesis_target_type": "pure_function",
            "constraints": {"deterministic": True},
        })
    )
    (state / "STATE.json").write_text(
        json.dumps({"round": 3, "phase": mode, "task_id": "T1"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    monkeypatch.setenv("JANUSMASK_ROUND", "3")
    return {"state": state, "workdir": workdir, "session_id": "sess"}


def _run(tool_name, tool_input, *, success=True, session_id="sess"):
    stdin = io.StringIO(json.dumps({
        "hook_event_name": "PostToolUse",
        "session_id": session_id,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": {
            "success": success,
            "filePath": tool_input.get("file_path", ""),
        },
    }))
    stdout = io.StringIO()
    post_tool.main(stdin, stdout)
    return json.loads(stdout.getvalue())


CLEAN_CODE = "def f(a, b):\n    return a + b\n"


class TestSubmissionPersistence:
    def test_canonical_file_written(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        out = _run(
            "Write",
            {"file_path": str(outbox_file), "content": CLEAN_CODE, "explanation": "add"},
        )
        assert out["decision"] == "allow"
        # Canonical filename lands under state/sessions/.
        sessions = list((env["state"] / "sessions").glob("claude_*_submission.json"))
        assert len(sessions) == 1
        record = json.loads(sessions[0].read_text())
        assert record["code"] == CLEAN_CODE
        assert record["agent_identity"] == "claude"
        assert record["round_number"] == 3
        assert record["submission_number"] == 1
        assert record["session_id"]
        assert record["timestamp"]

    def test_submission_number_increments_with_ledger(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        # Seed two prior allowed submissions.
        for _ in range(2):
            _ledger.append_hook_event(env["session_id"], "claude", "submit_code", "allow")
        _run(
            "Write",
            {"file_path": str(outbox_file), "content": CLEAN_CODE, "explanation": "x"},
        )
        record = json.loads(
            next((env["state"] / "sessions").glob("*_submission.json")).read_text()
        )
        assert record["submission_number"] == 3  # 2 prior + this one

    def test_allow_ledger_row_with_digest_appended(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        _run(
            "Write",
            {"file_path": str(outbox_file), "content": CLEAN_CODE, "explanation": "y"},
        )
        rows = _ledger.read_events(env["session_id"], "claude")
        hits = [
            r for r in rows
            if r["verb"] == "submit_code" and r["outcome"] == "allow"
        ]
        assert hits
        expected_digest = hashlib.sha256(CLEAN_CODE.encode("utf-8")).hexdigest()
        assert hits[-1]["digest"] == f"sha256:{expected_digest}"

    def test_failed_write_skips_persistence(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        out = _run(
            "Write",
            {"file_path": str(outbox_file), "content": CLEAN_CODE, "explanation": "x"},
            success=False,
        )
        assert out["decision"] == "allow"
        # No canonical file written.
        assert not (env["state"] / "sessions").exists() or not list(
            (env["state"] / "sessions").glob("*_submission.json")
        )


class TestClarificationPersistence:
    def test_clarification_record_written_and_counter_bumps(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "clarification_1.md"
        outbox_file.write_text("why does foo exist?")
        out = _run(
            "Write",
            {"file_path": str(outbox_file), "content": "why does foo exist?"},
        )
        assert out["decision"] == "allow"
        persisted = env["state"] / "sessions" / "claude_clarification_1.json"
        assert persisted.exists()
        record = json.loads(persisted.read_text())
        assert record["question"] == "why does foo exist?"
        assert record["clarification_number"] == 1
        # Ledger has the allow row.
        rows = _ledger.read_events(env["session_id"], "claude")
        assert any(
            r["verb"] == "clarification" and r["outcome"] == "allow" for r in rows
        )

    def test_clarification_number_derived_from_filename(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch)
        # Simulate 2nd clarification via filename.
        _ledger.append_hook_event(env["session_id"], "claude", "clarification", "allow")
        outbox_file = env["workdir"] / "outbox" / "clarification_2.md"
        outbox_file.write_text("follow-up")
        _run("Write", {"file_path": str(outbox_file), "content": "follow-up"})
        persisted = env["state"] / "sessions" / "claude_clarification_2.json"
        assert persisted.exists()
        record = json.loads(persisted.read_text())
        assert record["clarification_number"] == 2


class TestErrorReportPersistence:
    def test_error_record_written(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "error.md"
        outbox_file.write_text("boom: stuck on foo")
        out = _run(
            "Write",
            {"file_path": str(outbox_file), "content": "boom: stuck on foo"},
        )
        assert out["decision"] == "allow"
        persisted = env["state"] / "sessions" / "claude_error.json"
        assert persisted.exists()
        record = json.loads(persisted.read_text())
        assert "boom" in record["error"]


class TestPlanDraftPersistence:
    def test_plan_draft_written(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="planning")
        body = {"plan_version": "v1", "tasks": []}
        outbox_file = env["workdir"] / "outbox" / "plan_draft.json"
        outbox_file.write_text(json.dumps(body))
        out = _run(
            "Write",
            {"file_path": str(outbox_file), "content": json.dumps(body)},
        )
        assert out["decision"] == "allow"
        persisted = env["state"] / "planning" / "sessions" / "claude_draft.json"
        assert persisted.exists()
        rows = _ledger.read_events(env["session_id"], "claude")
        assert any(
            r["verb"] == "plan_draft" and r["outcome"] == "allow" for r in rows
        )


class TestReconciliationPersistence:
    def test_reconciliation_written(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch, mode="reconciliation")
        body = {"responses": []}
        outbox_file = env["workdir"] / "outbox" / "reconciliation.json"
        outbox_file.write_text(json.dumps(body))
        out = _run(
            "Write",
            {"file_path": str(outbox_file), "content": json.dumps(body)},
        )
        assert out["decision"] == "allow"
        persisted = (
            env["state"] / "planning" / "sessions" / "claude_reconciliation.json"
        )
        assert persisted.exists()


class TestNonWriteToolPassthrough:
    def test_read_tool_noop(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        out = _run("Read", {"file_path": "/tmp/x"})
        assert out["decision"] == "allow"


class TestMalformedInput:
    def test_garbage_stdin_allows(self, tmp_path, monkeypatch):
        _stage(tmp_path, monkeypatch)
        stdout = io.StringIO()
        rc = post_tool.main(io.StringIO("{not json"), stdout)
        assert rc == 0
        out = json.loads(stdout.getvalue())
        # PostToolUse cannot block retroactively — always allow on malformed input.
        assert out["decision"] == "allow"

    def test_nonexistent_outbox_file_does_not_crash(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        # Agent "succeeded" but file was deleted/never existed.
        out = _run(
            "Write",
            {"file_path": str(env["workdir"] / "outbox" / "submission.py"),
             "content": CLEAN_CODE, "explanation": "x"},
        )
        # Allow (cannot block retroactively) but no canonical file persisted.
        assert out["decision"] == "allow"
