"""Adversarial coverage for the persist-time AST gate.

Background: Phase 1+2 empirical diagnostic on B3 baseline-regen blocker #8
(2026-04-19) proved that the PreToolUse hook correctly emits decision=deny
with legitimate error violations, but the CLI can ignore the deny (Claude
--permission-mode bypassPermissions, Gemini yolo) and let the Write reach
the outbox anyway. PostToolUse / AfterTool previously persisted disk_content
unconditionally, creating an asymmetry with the orchestrator's re-validation
in _validate_submission (harness/orchestrator.py:654-663) which correctly
rejected the same bytes and looped until max_ast_retries exhausted.

These tests pin the minimum-scope fix: ensure_valid() raises
AstValidationError on error-severity violations, and both post_tool.py
persist paths call it before build_record/persist, emit a submit_code/deny
ledger row, and skip state/sessions/ write.
"""
from __future__ import annotations

import io
import json
import pathlib
import tempfile
from typing import Any

import pytest

from harness.ast_enforcer import Violation
from harness.hooks.rpc import submit_code as rpc_submit_code


CLEAN_CODE = "def add(a, b):\n    return a + b\n"
UUID_CODE = "import uuid\n\ndef make_id():\n    return uuid.uuid4().hex\n"
TIME_CODE = "import time\n\ndef stamp():\n    return time.time()\n"
SYNTAX_BROKEN = "def broken(:\n    pass\n"


class TestEnsureValid:
    """ensure_valid() is the persist-time gate. It must raise on errors,
    return warnings-only lists on clean code, and respect allow_nondet."""

    def test_clean_code_returns_empty_list(self) -> None:
        violations = rpc_submit_code.ensure_valid(CLEAN_CODE)
        assert violations == []

    def test_raises_on_uuid_import_under_default_allow_nondet(self) -> None:
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid(UUID_CODE)
        errors = [v for v in exc_info.value.violations if v.severity == "error"]
        assert errors, "AstValidationError must carry at least one error Violation"
        assert any(v.rule == "nondeterminism" for v in errors)

    def test_raises_on_time_time_under_default_allow_nondet(self) -> None:
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid(TIME_CODE)
        errors = [v for v in exc_info.value.violations if v.severity == "error"]
        assert any(v.rule == "nondeterminism" for v in errors)

    def test_allow_nondeterminism_true_does_not_raise_on_uuid(self) -> None:
        # Non-deterministic tasks must still persist their submissions.
        result = rpc_submit_code.ensure_valid(UUID_CODE, allow_nondeterminism=True)
        assert all(v.severity != "error" for v in result)

    def test_raises_on_syntax_error(self) -> None:
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid(SYNTAX_BROKEN)
        assert any(v.rule == "syntax" for v in exc_info.value.violations)

    def test_message_preview_contains_rule_and_line(self) -> None:
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid(UUID_CODE)
        msg = str(exc_info.value)
        assert "nondeterminism" in msg
        assert "L" in msg  # line-number prefix "@L<n>"

    def test_violations_list_is_copy_not_reference(self) -> None:
        with pytest.raises(rpc_submit_code.AstValidationError) as exc_info:
            rpc_submit_code.ensure_valid(UUID_CODE)
        original = list(exc_info.value.violations)
        exc_info.value.violations.clear()
        # The re-raised list was cleared, but a fresh ensure_valid call
        # must independently produce the same errors again.
        with pytest.raises(rpc_submit_code.AstValidationError) as exc2:
            rpc_submit_code.ensure_valid(UUID_CODE)
        assert len(exc2.value.violations) == len(original)


class TestAstValidationErrorShape:
    def test_carries_violations_attribute(self) -> None:
        viols = [Violation(rule="syntax", severity="error", line=1, message="boom")]
        err = rpc_submit_code.AstValidationError(viols)
        assert err.violations == viols

    def test_input_list_is_defensively_copied(self) -> None:
        viols = [Violation(rule="syntax", severity="error", line=1, message="orig")]
        err = rpc_submit_code.AstValidationError(viols)
        viols.append(Violation(rule="MUTANT", severity="error", line=99, message="x"))
        assert all(v.rule != "MUTANT" for v in err.violations)
        assert len(err.violations) == 1

    def test_warning_only_list_does_not_trigger_carry(self) -> None:
        # ensure_valid does not raise on warning-only input, so this test
        # documents that the exception is error-severity-only.
        warnings_only = (
            "import subprocess\n\n"
            "def run():\n    subprocess.run(['ls'])\n"
        )
        result = rpc_submit_code.ensure_valid(warnings_only)
        assert result  # warnings are returned, not raised
        assert all(v.severity != "error" for v in result)


class TestPersistStillGatedBySchema:
    """persist() keeps its existing schema gate. The new AST gate lives
    in ensure_valid() and is called by the post_tool _persist_submission
    layer — persist() itself is unchanged."""

    def test_persist_rejects_missing_fields(self, tmp_path: pathlib.Path) -> None:
        # A record with an error-severity submission should still write
        # via persist() as long as the schema is complete — the AST gate
        # is the caller's responsibility.
        record = {
            "session_id": "s1",
            "agent_identity": "claude",
            "round_number": 1,
            "timestamp": "2026-04-19T00:00:00Z",
            "submission_number": 1,
            "code": UUID_CODE,
            "explanation": "ast-gate-is-at-caller-not-persist",
        }
        out = rpc_submit_code.persist(record, state_dir=tmp_path, agent="claude", task_id="t1")
        assert out.exists()
        # Confirm the payload round-trips.
        saved = json.loads(out.read_text("utf-8"))
        assert saved["code"] == UUID_CODE


class TestPostToolClaudePersistGate:
    """harness/hooks/claude/post_tool.py::_persist_submission must gate on
    ensure_valid before build_record/persist."""

    def test_persist_submission_skips_on_ast_error(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks import _paths
        from harness.hooks.claude import post_tool as claude_post
        from harness.hooks.claude import _env as claude_env

        monkeypatch.setattr(_paths, "state_dir", lambda: tmp_path)
        inbox = tmp_path / "workdirs" / "claude" / "s1" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "task.json").write_text(
            json.dumps({"task_id": "gate-test", "synthesis_target_type": ""}),
            encoding="utf-8",
        )
        monkeypatch.setattr(claude_env, "inbox_dir", lambda sid: inbox)

        claude_post._persist_submission(
            session_id="s1",
            agent="claude",
            round_number=1,
            phase="synthesis",
            content=UUID_CODE,
            explanation="",
            events=[],
        )

        sessions = tmp_path / "sessions"
        if sessions.exists():
            # No *_submission.json must have been written.
            submission_files = list(sessions.glob("*_submission.json"))
            assert submission_files == [], (
                f"persist-time gate must skip on AST error; "
                f"found leaked submissions: {submission_files}"
            )

    def test_persist_submission_writes_on_clean_code(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks import _paths
        from harness.hooks.claude import post_tool as claude_post
        from harness.hooks.claude import _env as claude_env

        monkeypatch.setattr(_paths, "state_dir", lambda: tmp_path)
        inbox = tmp_path / "workdirs" / "claude" / "s1" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "task.json").write_text(
            json.dumps({"task_id": "clean-test", "synthesis_target_type": ""}),
            encoding="utf-8",
        )
        monkeypatch.setattr(claude_env, "inbox_dir", lambda sid: inbox)

        claude_post._persist_submission(
            session_id="s1",
            agent="claude",
            round_number=1,
            phase="synthesis",
            content=CLEAN_CODE,
            explanation="",
            events=[],
        )

        sessions = tmp_path / "sessions"
        assert sessions.exists()
        submission_files = list(sessions.glob("*_submission.json"))
        assert len(submission_files) == 1, (
            f"clean code must persist; got {submission_files}"
        )
        record = json.loads(submission_files[0].read_text("utf-8"))
        assert record["code"] == CLEAN_CODE
        assert record["agent_identity"] == "claude"

    def test_persist_submission_respects_allow_nondet_constraint(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Tasks with constraints.deterministic=False must persist
        nondeterministic code — the gate mirrors _decide_submission's
        allow_nondet derivation."""
        from harness.hooks import _paths
        from harness.hooks.claude import post_tool as claude_post
        from harness.hooks.claude import _env as claude_env

        monkeypatch.setattr(_paths, "state_dir", lambda: tmp_path)
        inbox = tmp_path / "workdirs" / "claude" / "s1" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "task.json").write_text(
            json.dumps(
                {
                    "task_id": "nondet-test",
                    "synthesis_target_type": "",
                    "constraints": {"deterministic": False},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(claude_env, "inbox_dir", lambda sid: inbox)

        claude_post._persist_submission(
            session_id="s1",
            agent="claude",
            round_number=1,
            phase="synthesis",
            content=UUID_CODE,
            explanation="",
            events=[],
        )

        submission_files = list((tmp_path / "sessions").glob("*_submission.json"))
        assert len(submission_files) == 1, (
            "nondet task with uuid import must still persist under "
            "constraints.deterministic=False"
        )


class TestPostToolGeminiPersistGate:
    """Twin of the Claude test for harness/hooks/gemini/post_tool.py."""

    def test_persist_submission_skips_on_ast_error(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks import _paths
        from harness.hooks.gemini import post_tool as gemini_post
        from harness.hooks.gemini import _env as gemini_env

        monkeypatch.setattr(_paths, "state_dir", lambda: tmp_path)
        inbox = tmp_path / "workdirs" / "gemini" / "s1" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "task.json").write_text(
            json.dumps({"task_id": "gate-test-g", "synthesis_target_type": ""}),
            encoding="utf-8",
        )
        monkeypatch.setattr(gemini_env, "inbox_dir", lambda sid: inbox)

        gemini_post._persist_submission(
            session_id="s1",
            agent="gemini",
            round_number=1,
            phase="synthesis",
            content=TIME_CODE,
            explanation="",
            events=[],
        )

        sessions = tmp_path / "sessions"
        if sessions.exists():
            submission_files = list(sessions.glob("*_submission.json"))
            assert submission_files == [], (
                f"gemini persist-time gate must skip on AST error; "
                f"found: {submission_files}"
            )

    def test_persist_submission_respects_allow_nondet_constraint(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks import _paths
        from harness.hooks.gemini import post_tool as gemini_post
        from harness.hooks.gemini import _env as gemini_env

        monkeypatch.setattr(_paths, "state_dir", lambda: tmp_path)
        inbox = tmp_path / "workdirs" / "gemini" / "s1" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "task.json").write_text(
            json.dumps(
                {
                    "task_id": "nondet-g",
                    "synthesis_target_type": "",
                    "constraints": {"deterministic": False},
                }
            ),
            encoding="utf-8",
        )
        monkeypatch.setattr(gemini_env, "inbox_dir", lambda sid: inbox)

        gemini_post._persist_submission(
            session_id="s1",
            agent="gemini",
            round_number=1,
            phase="synthesis",
            content=UUID_CODE,
            explanation="",
            events=[],
        )

        submission_files = list((tmp_path / "sessions").glob("*_submission.json"))
        assert len(submission_files) == 1, (
            "gemini nondet task with uuid import must still persist under "
            "constraints.deterministic=False"
        )

    def test_persist_submission_writes_on_clean_code(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks import _paths
        from harness.hooks.gemini import post_tool as gemini_post
        from harness.hooks.gemini import _env as gemini_env

        monkeypatch.setattr(_paths, "state_dir", lambda: tmp_path)
        inbox = tmp_path / "workdirs" / "gemini" / "s1" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "task.json").write_text(
            json.dumps({"task_id": "clean-g", "synthesis_target_type": ""}),
            encoding="utf-8",
        )
        monkeypatch.setattr(gemini_env, "inbox_dir", lambda sid: inbox)

        gemini_post._persist_submission(
            session_id="s1",
            agent="gemini",
            round_number=1,
            phase="synthesis",
            content=CLEAN_CODE,
            explanation="",
            events=[],
        )

        submission_files = list((tmp_path / "sessions").glob("*_submission.json"))
        assert len(submission_files) == 1
        record = json.loads(submission_files[0].read_text("utf-8"))
        assert record["code"] == CLEAN_CODE
        assert record["agent_identity"] == "gemini"


class TestPersistTimeLedgerRow:
    """On AST-gate rejection the post_tool layer must emit a submit_code/
    deny ledger row carrying the violation list so retry feedback works."""

    def test_claude_emits_deny_row_on_ast_gate_trip(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks import _ledger, _paths
        from harness.hooks.claude import post_tool as claude_post
        from harness.hooks.claude import _env as claude_env

        monkeypatch.setattr(_paths, "state_dir", lambda: tmp_path)
        inbox = tmp_path / "workdirs" / "claude" / "s1" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "task.json").write_text(
            json.dumps({"task_id": "row-test", "synthesis_target_type": ""}),
            encoding="utf-8",
        )
        monkeypatch.setattr(claude_env, "inbox_dir", lambda sid: inbox)

        ledger_path = tmp_path / "sessions" / "claude_s1.ledger.jsonl"
        monkeypatch.setattr(
            _ledger, "ledger_path", lambda sid, agent: ledger_path
        )

        claude_post._persist_submission(
            session_id="s1",
            agent="claude",
            round_number=1,
            phase="synthesis",
            content=UUID_CODE,
            explanation="",
            events=[],
        )

        assert ledger_path.exists(), "deny row must be persisted to ledger"
        rows = [
            json.loads(line)
            for line in ledger_path.read_text("utf-8").splitlines()
            if line.strip()
        ]
        deny_rows = [r for r in rows if r.get("outcome") == "deny"]
        assert deny_rows, (
            f"expected a submit_code/deny row; got {rows}"
        )
        row = deny_rows[0]
        assert row["verb"] == "submit_code"
        assert row["detail"]["reason"] == "persist_time_ast_gate"
        assert row["detail"]["error_count"] >= 1
        assert row["detail"]["violations"], "violation payload must be present"

    def test_gemini_emits_deny_row_on_ast_gate_trip(
        self, tmp_path: pathlib.Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from harness.hooks import _ledger, _paths
        from harness.hooks.gemini import post_tool as gemini_post
        from harness.hooks.gemini import _env as gemini_env

        monkeypatch.setattr(_paths, "state_dir", lambda: tmp_path)
        inbox = tmp_path / "workdirs" / "gemini" / "s1" / "inbox"
        inbox.mkdir(parents=True)
        (inbox / "task.json").write_text(
            json.dumps({"task_id": "row-test-g", "synthesis_target_type": ""}),
            encoding="utf-8",
        )
        monkeypatch.setattr(gemini_env, "inbox_dir", lambda sid: inbox)

        ledger_path = tmp_path / "sessions" / "gemini_s1.ledger.jsonl"
        monkeypatch.setattr(
            _ledger, "ledger_path", lambda sid, agent: ledger_path
        )

        gemini_post._persist_submission(
            session_id="s1",
            agent="gemini",
            round_number=1,
            phase="synthesis",
            content=TIME_CODE,
            explanation="",
            events=[],
        )

        assert ledger_path.exists(), "gemini deny row must be persisted to ledger"
        rows = [
            json.loads(line)
            for line in ledger_path.read_text("utf-8").splitlines()
            if line.strip()
        ]
        deny_rows = [r for r in rows if r.get("outcome") == "deny"]
        assert deny_rows, (
            f"expected a gemini submit_code/deny row; got {rows}"
        )
        row = deny_rows[0]
        assert row["verb"] == "submit_code"
        assert row["detail"]["reason"] == "persist_time_ast_gate"
        assert row["detail"]["error_count"] == len(row["detail"]["violations"])
        assert row["detail"]["violations"], "violation payload must be present"
