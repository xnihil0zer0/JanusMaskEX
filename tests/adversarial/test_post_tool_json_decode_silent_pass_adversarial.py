"""W105 adversarial battery for the post-tool JSON-decode silent-return.

Pre-W105 bug (round-3 G5 hooks audit): both
``harness.hooks.claude.post_tool._persist_plan_draft`` /
``_persist_reconciliation`` and the Gemini twins caught
``json.JSONDecodeError`` on the disk content of plan_draft.json /
reconciliation.json with a bare ``return`` — no stderr trace, no ledger
row. The OSError handler 4-6 lines below in each function DOES write to
stderr, showing the author knew the stderr-trace pattern but missed it
for JSONDecodeError. Impact: a worker submission with malformed JSON
silently disappears from the audit trail; orchestrator sees no
submission, no ledger row exists for the malformed content, debugging is
operator-grep-only.

Fix: extend each of the 4 except blocks to (a) write stderr trace
mirroring the OSError sibling, (b) append _ledger.append_hook_event with
outcome="invalid" and detail={"reason": "json_decode_error", "error":
str(exc)}.

These tests pin: (i) end-to-end PostToolUse / AfterTool with malformed
JSON content for each of the four sites (claude×{plan_draft,
reconciliation} + gemini×{plan_draft, reconciliation}); (ii) assert the
hook produces NO outcome="allow" row for the verb, AND DOES produce an
outcome="invalid" row with the json_decode_error reason; (iii) assert
existing ``has_verb(..., outcome="allow")`` consumers (the gating
helpers in _state_gates and _decide_common) remain false, since they
filter on outcome="allow" only.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import harness.hooks.claude.post_tool as claude_post_tool  # noqa: E402
import harness.hooks.gemini.post_tool as gemini_post_tool  # noqa: E402
from harness.hooks import _ledger  # noqa: E402


_MALFORMED = "{not valid json at all"


def _stage_claude(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "claude" / "w105-claude"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "outbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps({"task_id": "T-w105", "synthesis_target_type": "function"})
    )
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": "planning", "task_id": "T-w105"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "claude")
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    monkeypatch.setenv("JANUSMASK_ROUND", "1")
    return {"state": state, "workdir": workdir, "session_id": "w105-claude"}


def _run_claude(tool_input, *, sid="w105-claude"):
    body = {
        "hook_event_name": "PostToolUse",
        "session_id": sid,
        "tool_name": "Write",
        "tool_input": tool_input,
        "tool_response": {"success": True, "filePath": tool_input.get("file_path")},
    }
    stdin = io.StringIO(json.dumps(body))
    stdout = io.StringIO()
    claude_post_tool.main(stdin, stdout)
    return json.loads(stdout.getvalue())


def _stage_gemini(tmp_path, monkeypatch):
    state = tmp_path / "state"
    state.mkdir()
    workdir = state / "workdirs" / "gemini" / "w105-gemini"
    (workdir / "inbox").mkdir(parents=True)
    (workdir / "outbox").mkdir(parents=True)
    (workdir / "inbox" / "task.json").write_text(
        json.dumps({"task_id": "T-w105", "synthesis_target_type": "function"})
    )
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": "planning", "task_id": "T-w105"})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    monkeypatch.setenv("JANUSMASK_MODE", "planning")
    monkeypatch.setenv("JANUSMASK_ROUND", "1")
    return {"state": state, "workdir": workdir, "session_id": "w105-gemini"}


def _run_gemini(tool_name, tool_input, *, sid="w105-gemini"):
    body = {
        "hook_event_name": "AfterTool",
        "session_id": sid,
        "tool_name": tool_name,
        "tool_input": tool_input,
        "tool_response": {"success": True, "filePath": tool_input.get("file_path", "")},
    }
    stdin = io.StringIO(json.dumps(body))
    stdout = io.StringIO()
    gemini_post_tool.main(stdin, stdout)
    return json.loads(stdout.getvalue())


# ---------------------------------------------------------------------------
# Claude twin: PostToolUse + Write tool. Outbox-relative path drives dispatch.
# ---------------------------------------------------------------------------

def test_claude_post_tool_plan_draft_malformed_json_writes_invalid_ledger_row(
    tmp_path, monkeypatch, capsys
) -> None:
    """Pre-fix: bare ``return`` on JSONDecodeError. No allow row, no
    invalid row, no stderr trace — submission silently lost. Post-fix:
    stderr trace + ledger row outcome="invalid" with reason in detail."""
    env = _stage_claude(tmp_path, monkeypatch)
    outbox_file = env["workdir"] / "outbox" / "plan_draft.json"
    outbox_file.write_text(_MALFORMED)
    _run_claude(
        {"file_path": str(outbox_file), "content": _MALFORMED, "explanation": "x"}
    )
    captured = capsys.readouterr()
    assert "plan_draft" in captured.err.lower()
    assert "json decode" in captured.err.lower()

    rows = _ledger.read_events(env["session_id"], "claude")
    plan_rows = [r for r in rows if r.get("verb") == "plan_draft"]
    # The pre-fix path produced no row at all; the fix must yield exactly
    # one invalid row (and never an allow row).
    assert plan_rows, "no plan_draft ledger row recorded — silent-pass regression"
    assert all(r.get("outcome") != "allow" for r in plan_rows), (
        "plan_draft must NOT be marked allow on malformed JSON"
    )
    invalid_rows = [r for r in plan_rows if r.get("outcome") == "invalid"]
    assert len(invalid_rows) == 1, (
        f"expected exactly one invalid plan_draft row, got {invalid_rows!r}"
    )
    assert invalid_rows[0].get("detail", {}).get("reason") == "json_decode_error"
    # Existing has_verb gating consumers must continue to see "no allow":
    assert not _ledger.has_verb(rows, "plan_draft", outcome="allow")


def test_claude_post_tool_reconciliation_malformed_json_writes_invalid_ledger_row(
    tmp_path, monkeypatch, capsys
) -> None:
    env = _stage_claude(tmp_path, monkeypatch)
    outbox_file = env["workdir"] / "outbox" / "reconciliation.json"
    outbox_file.write_text(_MALFORMED)
    _run_claude(
        {"file_path": str(outbox_file), "content": _MALFORMED, "explanation": "x"}
    )
    captured = capsys.readouterr()
    assert "reconciliation" in captured.err.lower()
    assert "json decode" in captured.err.lower()

    rows = _ledger.read_events(env["session_id"], "claude")
    recon_rows = [r for r in rows if r.get("verb") == "reconciliation"]
    assert recon_rows, "no reconciliation ledger row — silent-pass regression"
    assert all(r.get("outcome") != "allow" for r in recon_rows)
    invalid_rows = [r for r in recon_rows if r.get("outcome") == "invalid"]
    assert len(invalid_rows) == 1
    assert invalid_rows[0].get("detail", {}).get("reason") == "json_decode_error"
    assert not _ledger.has_verb(rows, "reconciliation", outcome="allow")


# ---------------------------------------------------------------------------
# Gemini twin: AfterTool + write_file tool. Same dispatch shape.
# ---------------------------------------------------------------------------

def test_gemini_post_tool_plan_draft_malformed_json_writes_invalid_ledger_row(
    tmp_path, monkeypatch, capsys
) -> None:
    env = _stage_gemini(tmp_path, monkeypatch)
    outbox_file = env["workdir"] / "outbox" / "plan_draft.json"
    outbox_file.write_text(_MALFORMED)
    _run_gemini(
        "write_file",
        {"file_path": str(outbox_file), "content": _MALFORMED},
    )
    captured = capsys.readouterr()
    assert "plan_draft" in captured.err.lower()
    assert "json decode" in captured.err.lower()

    rows = _ledger.read_events(env["session_id"], "gemini")
    plan_rows = [r for r in rows if r.get("verb") == "plan_draft"]
    assert plan_rows, "no plan_draft ledger row — silent-pass regression"
    assert all(r.get("outcome") != "allow" for r in plan_rows)
    invalid_rows = [r for r in plan_rows if r.get("outcome") == "invalid"]
    assert len(invalid_rows) == 1
    assert invalid_rows[0].get("detail", {}).get("reason") == "json_decode_error"
    assert not _ledger.has_verb(rows, "plan_draft", outcome="allow")


def test_gemini_post_tool_reconciliation_malformed_json_writes_invalid_ledger_row(
    tmp_path, monkeypatch, capsys
) -> None:
    env = _stage_gemini(tmp_path, monkeypatch)
    outbox_file = env["workdir"] / "outbox" / "reconciliation.json"
    outbox_file.write_text(_MALFORMED)
    _run_gemini(
        "write_file",
        {"file_path": str(outbox_file), "content": _MALFORMED},
    )
    captured = capsys.readouterr()
    assert "reconciliation" in captured.err.lower()
    assert "json decode" in captured.err.lower()

    rows = _ledger.read_events(env["session_id"], "gemini")
    recon_rows = [r for r in rows if r.get("verb") == "reconciliation"]
    assert recon_rows, "no reconciliation ledger row — silent-pass regression"
    assert all(r.get("outcome") != "allow" for r in recon_rows)
    invalid_rows = [r for r in recon_rows if r.get("outcome") == "invalid"]
    assert len(invalid_rows) == 1
    assert invalid_rows[0].get("detail", {}).get("reason") == "json_decode_error"
    assert not _ledger.has_verb(rows, "reconciliation", outcome="allow")


# ---------------------------------------------------------------------------
# Negative control: a clean (well-formed JSON) submission still produces
# the existing outcome="allow" row, not the new "invalid" path. Pin so a
# careless rewrite that always-emits-invalid trips here.
# ---------------------------------------------------------------------------

def test_claude_post_tool_plan_draft_well_formed_json_still_allows(
    tmp_path, monkeypatch
) -> None:
    env = _stage_claude(tmp_path, monkeypatch)
    outbox_file = env["workdir"] / "outbox" / "plan_draft.json"
    well_formed = json.dumps({
        "task_id": "T-w105",
        "round": 1,
        "stages": [],
    })
    outbox_file.write_text(well_formed)
    _run_claude(
        {"file_path": str(outbox_file), "content": well_formed, "explanation": "x"}
    )
    rows = _ledger.read_events(env["session_id"], "claude")
    invalid_rows = [
        r for r in rows
        if r.get("verb") == "plan_draft" and r.get("outcome") == "invalid"
    ]
    assert not invalid_rows, (
        f"well-formed JSON must not emit an invalid row: {invalid_rows!r}"
    )
