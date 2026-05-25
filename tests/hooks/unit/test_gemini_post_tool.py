"""Unit tests for harness.hooks.gemini.post_tool (HOOK-33 / P3).

Gate 3 partner: the full dotted path harness.hooks.gemini.post_tool is
imported below so the post-write gate recognises this file as the
test partner.
"""

from __future__ import annotations

import hashlib
import io
import json

import pytest

import harness.hooks.gemini.post_tool as post_tool
from harness.hooks import _ledger
from harness.hooks.gemini import post_tool as pt_mod


CLEAN_CODE = "def f(a, b):\n    return a + b\n"


def _stage(tmp_path, monkeypatch, *, mode="synthesis"):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "sess"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "outbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps(
            {
                "task_id": "T1",
                "synthesis_target_type": "pure_function",
                "constraints": {"deterministic": True},
            }
        )
    )
    (state / "STATE.json").write_text(
        json.dumps({"round": 3, "phase": mode, "task_id": "T1"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    monkeypatch.setenv("JANUSMASK_ROUND", "3")
    return {"state": state, "workdir": workdir, "session_id": "sess"}


def _run(tool_name, tool_input, *, success=True, session_id="sess"):
    stdin = io.StringIO(
        json.dumps(
            {
                "hook_event_name": "AfterTool",
                "session_id": session_id,
                "tool_name": tool_name,
                "tool_input": tool_input,
                "tool_response": {
                    "success": success,
                    "filePath": tool_input.get("file_path", ""),
                },
            }
        )
    )
    stdout = io.StringIO()
    post_tool.main(stdin, stdout)
    return json.loads(stdout.getvalue())


class TestSubmissionPersistence:
    def test_write_file_canonical_submission(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        out = _run(
            "write_file",
            {
                "file_path": str(outbox_file),
                "content": CLEAN_CODE,
                "explanation": "Gemini add",
            },
        )
        assert out["decision"] == "allow"
        sessions = list(
            (env["state"] / "sessions").glob("gemini_*_submission.json")
        )
        assert len(sessions) == 1
        record = json.loads(sessions[0].read_text())
        assert record["code"] == CLEAN_CODE
        assert record["agent_identity"] == "gemini"
        assert record["round_number"] == 3
        assert record["submission_number"] == 1
        assert record["session_id"]
        assert record["timestamp"]

    def test_replace_also_persists_from_disk(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        out = _run(
            "replace",
            {
                "file_path": str(outbox_file),
                "old_string": "foo",
                "new_string": "bar",
                "explanation": "via replace",
            },
        )
        assert out["decision"] == "allow"
        sessions = list(
            (env["state"] / "sessions").glob("gemini_*_submission.json")
        )
        assert len(sessions) == 1
        assert json.loads(sessions[0].read_text())["code"] == CLEAN_CODE

    def test_submission_number_increments_with_ledger(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        for _ in range(2):
            _ledger.append_hook_event(
                env["session_id"], "gemini", "submit_code", "allow"
            )
        _run(
            "write_file",
            {
                "file_path": str(outbox_file),
                "content": CLEAN_CODE,
                "explanation": "x",
            },
        )
        record = json.loads(
            next(
                (env["state"] / "sessions").glob("*_submission.json")
            ).read_text()
        )
        assert record["submission_number"] == 3

    def test_ledger_row_with_digest_appended(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        _run(
            "write_file",
            {
                "file_path": str(outbox_file),
                "content": CLEAN_CODE,
                "explanation": "y",
            },
        )
        rows = _ledger.read_events(env["session_id"], "gemini")
        hits = [
            r
            for r in rows
            if r["verb"] == "submit_code" and r["outcome"] == "allow"
        ]
        assert hits
        expected = hashlib.sha256(CLEAN_CODE.encode("utf-8")).hexdigest()
        assert hits[-1]["digest"] == f"sha256:{expected}"

    def test_failed_response_skips_persistence(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        _run(
            "write_file",
            {"file_path": str(outbox_file), "content": CLEAN_CODE},
            success=False,
        )
        sessions = list((env["state"] / "sessions").glob("*.json"))
        assert not sessions

    def test_missing_disk_file_does_not_crash(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        # Never actually writes the file.
        out = _run(
            "write_file",
            {"file_path": str(outbox_file), "content": CLEAN_CODE},
        )
        assert out["decision"] == "allow"
        sessions = list((env["state"] / "sessions").glob("*.json"))
        assert not sessions


class TestClarificationPersistence:
    def test_clarification_persisted(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "clarification_1.md"
        outbox_file.write_text("Why?")
        _run(
            "write_file",
            {"file_path": str(outbox_file), "content": "Why?"},
        )
        rows = _ledger.read_events(env["session_id"], "gemini")
        hits = [r for r in rows if r["verb"] == "clarification"]
        assert hits and hits[-1]["outcome"] == "allow"


class TestErrorReportPersistence:
    def test_error_md_persisted(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "error.md"
        outbox_file.write_text("bad thing")
        _run(
            "write_file",
            {"file_path": str(outbox_file), "content": "bad thing"},
        )
        rows = _ledger.read_events(env["session_id"], "gemini")
        hits = [r for r in rows if r["verb"] == "error"]
        assert hits and hits[-1]["outcome"] == "allow"


class TestNonWriteTools:
    def test_read_file_allow_no_persistence(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        out = _run(
            "read_file",
            {"file_path": str(env["workdir"] / "inbox" / "task.json")},
        )
        assert out["decision"] == "allow"
        assert not list((env["state"] / "sessions").glob("*.json"))


class TestOutsideOutboxIsNoOp:
    def test_write_outside_outbox_does_not_persist(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        stranger = tmp_path / "stranger.py"
        stranger.write_text(CLEAN_CODE)
        out = _run(
            "write_file",
            {"file_path": str(stranger), "content": CLEAN_CODE},
        )
        assert out["decision"] == "allow"
        assert not list((env["state"] / "sessions").glob("*.json"))


class TestMalformedStdin:
    def test_malformed_stdin_allows(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        stdout = io.StringIO()
        post_tool.main(io.StringIO("{bad"), stdout)
        out = json.loads(stdout.getvalue())
        assert out["decision"] == "allow"
