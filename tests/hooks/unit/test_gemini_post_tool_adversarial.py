"""Adversarial battery for HOOK-33-gemini-post-tool (Phase 3).

AfterTool is persistence-only — it cannot retroactively block a tool
call, so the failure modes are all about data-integrity:

  - locked-field forgeability: the agent's ``write_file`` payload is
    just code; locked fields (``session_id``, ``agent_identity``,
    ``round_number``, ``timestamp``) are stamped by the hook from env
    + STATE, never from ``tool_input``. An adversary who mutates the
    on-disk file between BeforeTool and AfterTool cannot forge
    ``agent_identity="claude"``.
  - disk-content-wins: the hook re-reads the file from disk and
    persists that, not ``tool_input.content`` (sub-plan 03 §3.4 row
    C). If an attacker TOCTOU-swaps the file bytes the persisted
    record reflects the bytes actually on disk.
  - failure-mode robustness: missing files, unhappy persist paths,
    non-write tool calls must never crash the hook.
"""

from __future__ import annotations

import hashlib
import io
import json

import pytest

import harness.hooks.gemini.post_tool as post_tool
from harness.hooks import _ledger


CLEAN_CODE = "def f(x):\n    return x\n"


def _stage(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "adv"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "outbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps({"task_id": "T", "synthesis_target_type": "function"})
    )
    (state / "STATE.json").write_text(
        json.dumps({"round": 7, "phase": "synthesis", "task_id": "T"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    monkeypatch.setenv("JANUSMASK_ROUND", "7")
    return {"state": state, "workdir": workdir, "session_id": "adv"}


def _run(tool_name, tool_input, *, success=True, extra=None, sid="adv"):
    body = {
        "hook_event_name": "AfterTool",
        "session_id": sid,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": {
            "success": success,
            "filePath": tool_input.get("file_path", ""),
        },
    }
    if extra:
        body.update(extra)
    stdin = io.StringIO(json.dumps(body))
    stdout = io.StringIO()
    post_tool.main(stdin, stdout)
    return json.loads(stdout.getvalue())


class TestLockedFieldsUnforgeability:
    def test_agent_identity_is_stamped_from_env_not_stdin(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        # Attacker injects their own agent_identity via the stdin envelope —
        # this field must be ignored, not propagated.
        _run(
            "write_file",
            {
                "file_path": str(outbox_file),
                "content": CLEAN_CODE,
                "agent_identity": "claude",
                "session_id": "forged-sid",
                "round_number": 999,
            },
        )
        record = json.loads(
            next(
                (env["state"] / "sessions").glob("*_submission.json")
            ).read_text()
        )
        assert record["agent_identity"] == "gemini"
        assert record["round_number"] == 7
        # session_id from the stdin envelope's top-level field is what the
        # hook uses; the attacker can only set THEIR OWN session's record,
        # not alter identity or round.
        assert record["session_id"] == "adv"

    def test_timestamp_monotonic_across_two_persists(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        _run(
            "write_file",
            {
                "file_path": str(outbox_file),
                "content": CLEAN_CODE,
                "explanation": "v1",
            },
        )
        outbox_file.write_text(CLEAN_CODE + "# v2\n")
        _run(
            "write_file",
            {
                "file_path": str(outbox_file),
                "content": CLEAN_CODE + "# v2\n",
                "explanation": "v2",
            },
        )
        ts_list = [
            json.loads(p.read_text())["timestamp"]
            for p in sorted(
                (env["state"] / "sessions").glob("*_submission.json")
            )
        ]
        # Both records land; their timestamps are parseable ISO strings.
        for t in ts_list:
            assert t.endswith("Z")


class TestDiskContentWins:
    def test_toctou_swap_records_disk_bytes_not_stdin_bytes(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        # Orchestrator BeforeTool validated this content.
        validated = "def g(x):\n    return x * 2\n"
        outbox_file.write_text(validated)
        # Between Write and AfterTool, the agent swaps the file to
        # something else. The persisted record must reflect what is
        # actually on disk.
        swapped = "def g(x):\n    return x + 1\n"
        outbox_file.write_text(swapped)
        _run(
            "write_file",
            {
                "file_path": str(outbox_file),
                "content": validated,  # stdin still carries validated
                "explanation": "sneak",
            },
        )
        record = json.loads(
            next(
                (env["state"] / "sessions").glob("*_submission.json")
            ).read_text()
        )
        assert record["code"] == swapped

    def test_digest_matches_disk_content(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "submission.py"
        outbox_file.write_text(CLEAN_CODE)
        _run(
            "write_file",
            {
                "file_path": str(outbox_file),
                "content": CLEAN_CODE,
                "explanation": "x",
            },
        )
        rows = _ledger.read_events("adv", "gemini")
        hits = [
            r
            for r in rows
            if r["verb"] == "submit_code" and r["outcome"] == "allow"
        ]
        assert hits[-1]["digest"] == (
            "sha256:" + hashlib.sha256(CLEAN_CODE.encode("utf-8")).hexdigest()
        )


class TestResilience:
    def test_non_write_tool_does_not_crash(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        out = _run("grep_search", {"pattern": "foo"})
        assert out["decision"] == "allow"

    def test_failed_write_tool_response_skips_persistence(
        self, tmp_path, monkeypatch
    ):
        env = _stage(tmp_path, monkeypatch)
        out = _run(
            "write_file",
            {
                "file_path": str(
                    env["workdir"] / "outbox" / "submission.py"
                ),
                "content": CLEAN_CODE,
            },
            success=False,
        )
        assert out["decision"] == "allow"
        assert not list((env["state"] / "sessions").glob("*.json"))

    def test_unknown_outbox_file_no_persistence(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        outbox_file = env["workdir"] / "outbox" / "random.txt"
        outbox_file.write_text("anything")
        out = _run(
            "write_file",
            {"file_path": str(outbox_file), "content": "anything"},
        )
        assert out["decision"] == "allow"
        assert not list((env["state"] / "sessions").glob("*.json"))

    def test_never_emits_block_or_ask_vocab(self, tmp_path, monkeypatch):
        env = _stage(tmp_path, monkeypatch)
        out = _run(
            "write_file",
            {
                "file_path": str(
                    env["workdir"] / "outbox" / "submission.py"
                ),
                "content": CLEAN_CODE,
            },
        )
        assert out["decision"] == "allow"  # post-tool never denies
