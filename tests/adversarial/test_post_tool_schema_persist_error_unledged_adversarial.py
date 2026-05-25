"""W113 adversarial — post_tool unledged exception sites.

Pre-fix: harness/hooks/{claude,gemini}/post_tool.py caught five exception
classes (rpc_*.SchemaError on submit_code/clarification/error_report;
OSError on plan_draft/reconciliation persist) with stderr trace but no
ledger row, violating ledger-as-source-of-truth for validation-failure
audit.

Post-fix: each handler emits an outcome='invalid' ledger row mirroring
the W105 JSONDecodeError shape with detail={'reason': 'schema_error' |
'persist_error', 'error': str(exc), ...}. Outcome='invalid' is
non-conflicting with all has_verb/count_verb consumers (filter on
outcome='allow').

Tests directly invoke the private _persist_* helpers per twin with
monkey-patched rpc layer raising the target exception, then read the
ledger back and assert (a) the invalid row exists, (b) the verb +
detail.reason match, and (c) twin parity holds.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import harness.hooks.claude.post_tool as claude_pt  # noqa: E402
import harness.hooks.gemini.post_tool as gemini_pt  # noqa: E402
from harness.hooks import _ledger  # noqa: E402
from harness.hooks.rpc import (  # noqa: E402
    clarification as rpc_clarification,
    error_report as rpc_error_report,
    submit_code as rpc_submit_code,
    submit_plan_draft as rpc_submit_plan_draft,
    submit_reconciliation as rpc_submit_reconciliation,
)


_SESSION_ID = "sess-w113"


def _stage(tmp_path, monkeypatch, *, agent: str, mode: str = "synthesis"):
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "sessions").mkdir(parents=True, exist_ok=True)
    workdir = state / "workdirs" / agent / _SESSION_ID
    (workdir / "inbox").mkdir(parents=True, exist_ok=True)
    (workdir / "outbox").mkdir(parents=True, exist_ok=True)
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
        json.dumps({"round": 1, "phase": mode, "task_id": "T1"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", agent)
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    return {"state": state, "workdir": workdir, "session_id": _SESSION_ID}


def _invalid_rows(session_id: str, agent: str, *, verb: str):
    return [
        r
        for r in _ledger.read_events(session_id, agent)
        if r.get("verb") == verb and r.get("outcome") == "invalid"
    ]


def _allow_rows(session_id: str, agent: str, *, verb: str):
    return [
        r
        for r in _ledger.read_events(session_id, agent)
        if r.get("verb") == verb and r.get("outcome") == "allow"
    ]


# -- submit_code SchemaError ----------------------------------------------


def _patch_submit_code_schema_error(monkeypatch):
    def _raise(*a, **kw):
        raise rpc_submit_code.SchemaError("test_schema_failure")

    monkeypatch.setattr(rpc_submit_code, "ensure_valid", lambda *a, **kw: None)
    monkeypatch.setattr(rpc_submit_code, "build_record", _raise)


class TestSubmitCodeSchemaError:
    def test_claude_schema_error_emits_invalid_row(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="claude")
        _patch_submit_code_schema_error(monkeypatch)
        claude_pt._persist_submission(
            session_id=env["session_id"],
            agent="claude",
            round_number=1,
            phase="synthesis",
            content="def f():\n    return 1\n",
            explanation="test",
            events=[],
        )
        rows = _invalid_rows(env["session_id"], "claude", verb="submit_code")
        assert len(rows) == 1
        row = rows[0]
        assert row["hook"] == "PostToolUse"
        assert row["tool"] == "Write"
        assert row["detail"]["reason"] == "schema_error"
        assert row["detail"]["task_id"] == "T1"
        assert "test_schema_failure" in row["detail"]["error"]
        assert (
            "PostToolUse submit_code schema error" in capsys.readouterr().err
        )
        assert _allow_rows(env["session_id"], "claude", verb="submit_code") == []

    def test_gemini_schema_error_emits_invalid_row(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="gemini")
        _patch_submit_code_schema_error(monkeypatch)
        gemini_pt._persist_submission(
            session_id=env["session_id"],
            agent="gemini",
            round_number=1,
            phase="synthesis",
            content="def f():\n    return 1\n",
            explanation="test",
            events=[],
        )
        rows = _invalid_rows(env["session_id"], "gemini", verb="submit_code")
        assert len(rows) == 1
        row = rows[0]
        assert row["hook"] == "AfterTool"
        assert row["tool"] == "write_file"
        assert row["detail"]["reason"] == "schema_error"
        assert "test_schema_failure" in row["detail"]["error"]
        assert (
            "AfterTool(gemini) submit_code schema error"
            in capsys.readouterr().err
        )


# -- clarification SchemaError ---------------------------------------------


def _patch_clarification_schema_error(monkeypatch):
    def _raise(*a, **kw):
        raise rpc_clarification.SchemaError("clar_schema_failure")

    monkeypatch.setattr(rpc_clarification, "build_record", _raise)


class TestClarificationSchemaError:
    def test_claude_schema_error_emits_invalid_row(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="claude")
        _patch_clarification_schema_error(monkeypatch)
        clar_path = str(env["workdir"] / "outbox" / "clarification_2.md")
        claude_pt._persist_clarification(
            file_path=clar_path,
            session_id=env["session_id"],
            agent="claude",
            round_number=1,
            phase="synthesis",
            content="why?",
        )
        rows = _invalid_rows(env["session_id"], "claude", verb="clarification")
        assert len(rows) == 1
        row = rows[0]
        assert row["detail"]["reason"] == "schema_error"
        assert row["detail"]["clarification_number"] == 2
        assert "clar_schema_failure" in row["detail"]["error"]
        assert (
            "PostToolUse clarification schema error" in capsys.readouterr().err
        )

    def test_gemini_schema_error_emits_invalid_row(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="gemini")
        _patch_clarification_schema_error(monkeypatch)
        clar_path = str(env["workdir"] / "outbox" / "clarification_3.md")
        gemini_pt._persist_clarification(
            file_path=clar_path,
            session_id=env["session_id"],
            agent="gemini",
            round_number=1,
            phase="synthesis",
            content="why?",
        )
        rows = _invalid_rows(env["session_id"], "gemini", verb="clarification")
        assert len(rows) == 1
        row = rows[0]
        assert row["detail"]["reason"] == "schema_error"
        assert row["detail"]["clarification_number"] == 3


# -- error_report SchemaError (verb="error" per existing handler) ---------


def _patch_error_report_schema_error(monkeypatch):
    def _raise(*a, **kw):
        raise rpc_error_report.SchemaError("err_schema_failure")

    monkeypatch.setattr(rpc_error_report, "build_record", _raise)


class TestErrorReportSchemaError:
    def test_claude_schema_error_emits_invalid_row_with_error_verb(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="claude")
        _patch_error_report_schema_error(monkeypatch)
        claude_pt._persist_error_report(
            session_id=env["session_id"],
            agent="claude",
            round_number=1,
            phase="synthesis",
            content="oops",
        )
        rows = _invalid_rows(env["session_id"], "claude", verb="error")
        assert len(rows) == 1
        assert rows[0]["detail"]["reason"] == "schema_error"
        assert "err_schema_failure" in rows[0]["detail"]["error"]
        assert (
            "PostToolUse error_report schema error" in capsys.readouterr().err
        )

    def test_gemini_schema_error_emits_invalid_row_with_error_verb(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="gemini")
        _patch_error_report_schema_error(monkeypatch)
        gemini_pt._persist_error_report(
            session_id=env["session_id"],
            agent="gemini",
            round_number=1,
            phase="synthesis",
            content="oops",
        )
        rows = _invalid_rows(env["session_id"], "gemini", verb="error")
        assert len(rows) == 1
        assert rows[0]["detail"]["reason"] == "schema_error"


# -- plan_draft OSError on persist ----------------------------------------


def _patch_plan_draft_persist_oserror(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("disk_full_simulated")

    monkeypatch.setattr(rpc_submit_plan_draft, "persist", _raise)


class TestPlanDraftPersistOSError:
    def test_claude_oserror_emits_invalid_row(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="claude")
        _patch_plan_draft_persist_oserror(monkeypatch)
        claude_pt._persist_plan_draft(
            session_id=env["session_id"],
            agent="claude",
            round_number=1,
            phase="planning",
            content=json.dumps({"steps": []}),
        )
        rows = _invalid_rows(env["session_id"], "claude", verb="plan_draft")
        assert len(rows) == 1
        row = rows[0]
        assert row["detail"]["reason"] == "persist_error"
        assert "disk_full_simulated" in row["detail"]["error"]
        assert (
            "PostToolUse plan_draft persist error" in capsys.readouterr().err
        )

    def test_gemini_oserror_emits_invalid_row(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="gemini")
        _patch_plan_draft_persist_oserror(monkeypatch)
        gemini_pt._persist_plan_draft(
            session_id=env["session_id"],
            agent="gemini",
            round_number=1,
            phase="planning",
            content=json.dumps({"steps": []}),
        )
        rows = _invalid_rows(env["session_id"], "gemini", verb="plan_draft")
        assert len(rows) == 1
        row = rows[0]
        assert row["detail"]["reason"] == "persist_error"
        assert "disk_full_simulated" in row["detail"]["error"]


# -- reconciliation OSError on persist ------------------------------------


def _patch_reconciliation_persist_oserror(monkeypatch):
    def _raise(*a, **kw):
        raise OSError("disk_perm_denied_simulated")

    monkeypatch.setattr(rpc_submit_reconciliation, "persist", _raise)


class TestReconciliationPersistOSError:
    def test_claude_oserror_emits_invalid_row(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="claude")
        _patch_reconciliation_persist_oserror(monkeypatch)
        claude_pt._persist_reconciliation(
            session_id=env["session_id"],
            agent="claude",
            round_number=1,
            phase="reconciliation",
            content=json.dumps({"items": []}),
        )
        rows = _invalid_rows(
            env["session_id"], "claude", verb="reconciliation"
        )
        assert len(rows) == 1
        row = rows[0]
        assert row["detail"]["reason"] == "persist_error"
        assert "disk_perm_denied_simulated" in row["detail"]["error"]

    def test_gemini_oserror_emits_invalid_row(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="gemini")
        _patch_reconciliation_persist_oserror(monkeypatch)
        gemini_pt._persist_reconciliation(
            session_id=env["session_id"],
            agent="gemini",
            round_number=1,
            phase="reconciliation",
            content=json.dumps({"items": []}),
        )
        rows = _invalid_rows(
            env["session_id"], "gemini", verb="reconciliation"
        )
        assert len(rows) == 1
        assert rows[0]["detail"]["reason"] == "persist_error"


# -- Negative controls (well-formed input emits no invalid rows) ----------


class TestNegativeControl:
    def test_claude_well_formed_plan_draft_emits_no_invalid_row(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="claude")
        # Stub persist so we don't need a real validator.
        monkeypatch.setattr(
            rpc_submit_plan_draft, "persist", lambda *a, **kw: None
        )
        claude_pt._persist_plan_draft(
            session_id=env["session_id"],
            agent="claude",
            round_number=1,
            phase="planning",
            content=json.dumps({"steps": []}),
        )
        assert (
            _invalid_rows(env["session_id"], "claude", verb="plan_draft") == []
        )
        # The allow row should still be emitted.
        assert len(
            _allow_rows(env["session_id"], "claude", verb="plan_draft")
        ) == 1


# -- Twin parity -----------------------------------------------------------


class TestTwinParity:
    def test_both_twins_use_identical_invalid_row_shape(
        self, tmp_path, monkeypatch
    ) -> None:
        env_c = _stage(tmp_path / "c", monkeypatch, agent="claude")
        _patch_plan_draft_persist_oserror(monkeypatch)
        claude_pt._persist_plan_draft(
            session_id=env_c["session_id"],
            agent="claude",
            round_number=1,
            phase="planning",
            content=json.dumps({"steps": []}),
        )
        c_rows = _invalid_rows(
            env_c["session_id"], "claude", verb="plan_draft"
        )

        env_g = _stage(tmp_path / "g", monkeypatch, agent="gemini")
        gemini_pt._persist_plan_draft(
            session_id=env_g["session_id"],
            agent="gemini",
            round_number=1,
            phase="planning",
            content=json.dumps({"steps": []}),
        )
        g_rows = _invalid_rows(
            env_g["session_id"], "gemini", verb="plan_draft"
        )

        assert len(c_rows) == 1 and len(g_rows) == 1
        c, g = c_rows[0], g_rows[0]
        assert c["verb"] == g["verb"] == "plan_draft"
        assert c["outcome"] == g["outcome"] == "invalid"
        assert set(c["detail"].keys()) == set(g["detail"].keys()) == {
            "reason",
            "error",
        }
        assert c["detail"]["reason"] == g["detail"]["reason"] == "persist_error"
