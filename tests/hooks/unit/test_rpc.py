"""Unit tests for harness.hooks.rpc.* (HOOK-11-extract-rpc).

Pins the contract of the extracted MCP verb bodies so both MCP and the future
hook entrypoints can share a single source of truth:

    harness.hooks.rpc.submit_code
    harness.hooks.rpc.submit_plan_draft
    harness.hooks.rpc.submit_reconciliation
    harness.hooks.rpc.clarification
    harness.hooks.rpc.error_report

The required submission schema mirrors mcp_server.py:648-658.
"""

from __future__ import annotations

import json

import pytest

import harness.hooks.rpc.submit_code
import harness.hooks.rpc.submit_plan_draft
import harness.hooks.rpc.submit_reconciliation
import harness.hooks.rpc.clarification
import harness.hooks.rpc.error_report
from harness.hooks.rpc import (
    submit_code,
    submit_plan_draft,
    submit_reconciliation,
    clarification,
    error_report,
)


# ---------- submit_code ----------


def _locked_fields(**overrides):
    base = {
        "session_id": "sess-1",
        "agent_identity": "claude",
        "round_number": 3,
        "timestamp": "2026-04-17T12:00:00+00:00",
    }
    base.update(overrides)
    return base


class TestSubmitCodeValidate:
    def test_clean_code_returns_empty(self):
        code = "def add(a, b):\n    return a + b\n"
        violations = submit_code.validate(code)
        assert violations == []

    def test_invalid_syntax_returns_violations(self):
        violations = submit_code.validate("def bad(:\n    return")
        assert any(v.severity == "error" for v in violations)

    def test_allow_nondeterminism_flag_passed_through(self):
        code = "import random\ndef f():\n    return random.random()\n"
        strict = submit_code.validate(code, allow_nondeterminism=False)
        relaxed = submit_code.validate(code, allow_nondeterminism=True)
        # Deterministic mode should flag more than the relaxed mode.
        strict_err = [v for v in strict if v.severity == "error"]
        relaxed_err = [v for v in relaxed if v.severity == "error"]
        assert len(strict_err) >= len(relaxed_err)


class TestSubmitCodePersist:
    def test_build_record_matches_schema(self):
        args = _locked_fields(code="x=1", explanation="trivial")
        rec = submit_code.build_record(args, submission_number=1)
        for k in (
            "session_id", "agent_identity", "round_number", "timestamp",
            "submission_number", "code", "explanation",
        ):
            assert k in rec, f"record missing required schema key: {k}"
        assert rec["submission_number"] == 1
        assert rec["code"] == "x=1"

    def test_build_record_missing_code_raises(self):
        args = _locked_fields(explanation="nope")
        with pytest.raises(submit_code.SchemaError) as exc:
            submit_code.build_record(args, submission_number=1)
        # Error must point agents to the canonical mcp_server schema lines.
        assert "mcp_server.py:648-658" in str(exc.value)

    def test_build_record_missing_explanation_raises(self):
        args = _locked_fields(code="x=1")
        with pytest.raises(submit_code.SchemaError) as exc:
            submit_code.build_record(args, submission_number=1)
        assert "mcp_server.py:648-658" in str(exc.value)
        assert "explanation" in str(exc.value)

    def test_persist_writes_canonical_filename(self, tmp_path):
        args = _locked_fields(code="x=1", explanation="e")
        rec = submit_code.build_record(args, submission_number=1)
        path = submit_code.persist(rec, state_dir=tmp_path, agent="claude", task_id="TSK-1")
        assert path.exists()
        # Filename shape matches session_namer.generate_submission_filename().
        assert "claude_round3" in path.name and "TSK-1" in path.name
        assert path.name.endswith("_submission.json")
        on_disk = json.loads(path.read_text())
        assert on_disk == rec


class TestSubmitCodePayloads:
    def test_accepted_payload_no_warnings(self):
        p = submit_code.accepted_payload([])
        assert p["status"] == "accepted"
        assert p["ast_valid"] is True
        assert "warnings" not in p

    def test_accepted_payload_with_warnings(self):
        p = submit_code.accepted_payload([{"rule": "x", "line": 1, "message": "m"}])
        assert p["warnings"] == [{"rule": "x", "line": 1, "message": "m"}]

    def test_rejected_payload_truncates_to_50(self):
        fakes = [
            type("V", (), {"rule": "r", "line": i, "message": "m", "severity": "error"})()
            for i in range(75)
        ]
        p = submit_code.rejected_payload(fakes)
        assert p["status"] == "rejected"
        assert p["ast_valid"] is False
        assert len(p["violations"]) == 50
        assert "50" in p["message"]


# ---------- submit_plan_draft ----------


class TestSubmitPlanDraft:
    def test_persist_writes_single_shot_file(self, tmp_path):
        args = {"tasks": [], "session_id": "s1", "agent_identity": "claude"}
        path = submit_plan_draft.persist(args, state_dir=tmp_path, agent="claude")
        assert path.exists()
        assert path.name == "claude_draft.json"
        assert path.parent.name == "sessions"

    def test_validate_returns_list(self):
        violations = submit_plan_draft.validate({"tasks": []})
        assert isinstance(violations, list)


# ---------- submit_reconciliation ----------


class TestSubmitReconciliation:
    def test_validate_unknown_stance(self):
        err = submit_reconciliation.validate_responses(
            [{"stance": "bogus", "diff_item_id": "D1"}], valid_ids={"D1"}
        )
        assert err is not None and "bogus" in err.lower()

    def test_validate_unknown_diff_id(self):
        err = submit_reconciliation.validate_responses(
            [{"stance": "defend", "diff_item_id": "XYZ"}], valid_ids={"D1"}
        )
        assert err is not None and "XYZ" in err

    def test_validate_rejects_non_list(self):
        err = submit_reconciliation.validate_responses("not-a-list", valid_ids=set())
        assert err is not None

    def test_validate_rejects_non_dict_entry(self):
        err = submit_reconciliation.validate_responses(["string"], valid_ids=set())
        assert err is not None

    def test_validate_accepts_valid(self):
        err = submit_reconciliation.validate_responses(
            [{"stance": "concede", "diff_item_id": "D1"}], valid_ids={"D1"}
        )
        assert err is None

    def test_load_valid_diff_ids_from_disk(self, tmp_path):
        planning = tmp_path / "planning"
        planning.mkdir()
        (planning / "current_diff.json").write_text(json.dumps(
            {"items": [{"diff_item_id": "A"}, {"diff_item_id": "B"}]}
        ))
        assert submit_reconciliation.load_valid_diff_ids(tmp_path) == {"A", "B"}

    def test_load_valid_diff_ids_missing_returns_empty(self, tmp_path):
        assert submit_reconciliation.load_valid_diff_ids(tmp_path) == set()

    def test_persist_writes_canonical_file(self, tmp_path):
        args = {"responses": [{"stance": "defend", "diff_item_id": "D1"}]}
        p = submit_reconciliation.persist(args, state_dir=tmp_path, agent="gemini")
        assert p.exists()
        assert p.name == "gemini_reconciliation.json"


# ---------- clarification ----------


class TestClarification:
    def test_build_record_requires_question(self):
        with pytest.raises(clarification.SchemaError):
            clarification.build_record(_locked_fields(), clarification_number=1)

    def test_build_record_shape(self):
        args = _locked_fields(question="why?")
        rec = clarification.build_record(args, clarification_number=2)
        assert rec["clarification_number"] == 2
        assert rec["question"] == "why?"
        for k in ("session_id", "agent_identity", "round_number", "timestamp"):
            assert k in rec

    def test_persist_writes_numbered_file(self, tmp_path):
        args = _locked_fields(question="q")
        rec = clarification.build_record(args, clarification_number=1)
        p = clarification.persist(rec, state_dir=tmp_path, agent="claude",
                                   clarification_number=1)
        assert p.exists()
        assert p.name == "claude_clarification_1.json"


# ---------- error_report ----------


class TestErrorReport:
    def test_build_record_requires_error(self):
        with pytest.raises(error_report.SchemaError):
            error_report.build_record(_locked_fields())

    def test_build_record_shape(self):
        args = _locked_fields(error="boom")
        rec = error_report.build_record(args)
        assert rec["error"] == "boom"
        for k in ("session_id", "agent_identity", "round_number", "timestamp"):
            assert k in rec

    def test_persist_writes_canonical_file(self, tmp_path):
        args = _locked_fields(error="e")
        rec = error_report.build_record(args)
        p = error_report.persist(rec, state_dir=tmp_path, agent="gemini")
        assert p.exists()
        assert p.name == "gemini_error.json"
