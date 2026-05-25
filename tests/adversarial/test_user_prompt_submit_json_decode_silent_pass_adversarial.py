"""W108 adversarial battery for the user_prompt_submit JSON-decode silent-return.

Pre-W108 bug (round-3 H_W107 audit, operator-authorized re-evaluation):
both ``harness.hooks.claude.user_prompt_submit._read_json_file`` and the
Gemini twin caught ``json.JSONDecodeError`` lumped together with
``FileNotFoundError`` / ``OSError`` and bare-returned ``None``. Corrupt
``inbox/task.json`` / ``inbox/feedback.json`` / ``inbox/diff_summary.json``
/ ``inbox/brief.json`` from the worker outbox silently disappeared with
no stderr trace, no ledger row. Operators could not distinguish
"no inbox file" from "malformed inbox file".

Fix (mirrors W105 post_tool pattern): split the bare except into
(a) a ``json.JSONDecodeError`` handler that writes a stderr trace
mirroring the post_tool format and appends a
``_ledger.append_hook_event(verb, outcome="invalid", detail={"reason":
"json_decode_error", "error": str(exc), "path": str(path)})``,
(b) a ``(FileNotFoundError, OSError)`` handler that still bare-returns
``None`` (silent skip remains the design for missing files). Callers
thread audit kwargs (``verb="task_read"`` or ``verb="feedback_read"``).

These tests pin: (i) end-to-end UserPromptSubmit / BeforeModel with
malformed JSON content for each of the four sites (claude×{task_read,
feedback_read} + gemini×{task_read, feedback_read}); (ii) assert the
hook produces NO ``outcome="allow"`` row for the verb, AND DOES produce
exactly one ``outcome="invalid"`` row with ``reason="json_decode_error"``
in detail; (iii) assert ``_ledger.has_verb(.., outcome="allow")``
gating consumers stay false; (iv) negative controls — well-formed inbox
still emits exactly one allow row and zero invalid rows.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import harness.hooks.claude.user_prompt_submit as claude_ups  # noqa: E402
import harness.hooks.gemini.user_prompt_submit as gemini_ups  # noqa: E402
from harness.hooks import _ledger  # noqa: E402


_MALFORMED = "{not valid json at all"


def _stage(tmp_path, monkeypatch, *, agent: str, mode: str, phase: str | None = None):
    state = tmp_path / "state"
    state.mkdir(exist_ok=True)
    sid = f"w108-{agent}"
    workdir = state / "workdirs" / agent / sid
    (workdir / "inbox").mkdir(parents=True, exist_ok=True)
    (state / "STATE.json").write_text(
        json.dumps({"round": 1, "phase": phase or mode})
    )
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(state))
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(workdir))
    monkeypatch.setenv("JANUSMASK_AGENT", agent)
    monkeypatch.setenv("JANUSMASK_MODE", mode)
    return {"state": state, "workdir": workdir, "session_id": sid}


def _run_claude(session_id: str):
    stdin = io.StringIO(
        json.dumps({"hook_event_name": "UserPromptSubmit", "session_id": session_id})
    )
    stdout = io.StringIO()
    claude_ups.main(stdin, stdout)
    return json.loads(stdout.getvalue())


def _run_gemini(session_id: str):
    stdin = io.StringIO(
        json.dumps({"hook_event_name": "BeforeModel", "session_id": session_id})
    )
    stdout = io.StringIO()
    gemini_ups.main(stdin, stdout)
    return json.loads(stdout.getvalue())


# ---------------------------------------------------------------------------
# Claude twin — UserPromptSubmit
# ---------------------------------------------------------------------------


def test_claude_task_read_malformed_json_writes_invalid_ledger_row(
    tmp_path, monkeypatch, capsys
) -> None:
    """Pre-fix: bare return on JSONDecodeError. No allow row, no
    invalid row, no stderr trace. Post-fix: stderr trace + exactly one
    invalid row with reason=json_decode_error in detail."""
    env = _stage(tmp_path, monkeypatch, agent="claude", mode="synthesis")
    (env["workdir"] / "inbox" / "task.json").write_text(_MALFORMED)

    out = _run_claude(env["session_id"])
    captured = capsys.readouterr()

    assert out["decision"] == "allow"
    assert "task_read" in captured.err
    assert "json decode" in captured.err.lower()
    assert "UserPromptSubmit" in captured.err

    rows = _ledger.read_events(env["session_id"], "claude")
    task_rows = [r for r in rows if r.get("verb") == "task_read"]
    assert task_rows, "no task_read ledger row recorded — silent-pass regression"
    assert all(r.get("outcome") != "allow" for r in task_rows), (
        "task_read must NOT be marked allow on malformed JSON"
    )
    invalid_rows = [r for r in task_rows if r.get("outcome") == "invalid"]
    assert len(invalid_rows) == 1, (
        f"expected exactly one invalid task_read row, got {invalid_rows!r}"
    )
    assert invalid_rows[0].get("detail", {}).get("reason") == "json_decode_error"
    assert not _ledger.has_verb(rows, "task_read", outcome="allow")


def test_claude_feedback_read_malformed_json_writes_invalid_ledger_row(
    tmp_path, monkeypatch, capsys
) -> None:
    env = _stage(
        tmp_path, monkeypatch, agent="claude",
        mode="synthesis", phase="cross_examination",
    )
    # task.json well-formed so the feedback branch is exercised cleanly
    (env["workdir"] / "inbox" / "task.json").write_text(
        json.dumps({"task_id": "T-w108", "specification": "x"})
    )
    (env["workdir"] / "inbox" / "feedback.json").write_text(_MALFORMED)

    out = _run_claude(env["session_id"])
    captured = capsys.readouterr()

    assert out["decision"] == "allow"
    assert "feedback_read" in captured.err
    assert "json decode" in captured.err.lower()

    rows = _ledger.read_events(env["session_id"], "claude")
    fb_rows = [r for r in rows if r.get("verb") == "feedback_read"]
    assert fb_rows, "no feedback_read ledger row — silent-pass regression"
    invalid_rows = [r for r in fb_rows if r.get("outcome") == "invalid"]
    assert len(invalid_rows) == 1
    assert invalid_rows[0].get("detail", {}).get("reason") == "json_decode_error"
    assert not _ledger.has_verb(rows, "feedback_read", outcome="allow")


def test_claude_task_well_formed_emits_allow_no_invalid(tmp_path, monkeypatch) -> None:
    """Negative control: a well-formed inbox file still produces a single
    allow row and zero invalid rows."""
    env = _stage(tmp_path, monkeypatch, agent="claude", mode="synthesis")
    (env["workdir"] / "inbox" / "task.json").write_text(
        json.dumps({"task_id": "T-w108", "specification": "x"})
    )

    out = _run_claude(env["session_id"])
    assert out["decision"] == "allow"

    rows = _ledger.read_events(env["session_id"], "claude")
    task_rows = [r for r in rows if r.get("verb") == "task_read"]
    assert any(r.get("outcome") == "allow" for r in task_rows)
    assert not any(r.get("outcome") == "invalid" for r in task_rows)


# ---------------------------------------------------------------------------
# Gemini twin — BeforeModel
# ---------------------------------------------------------------------------


def test_gemini_task_read_malformed_json_writes_invalid_ledger_row(
    tmp_path, monkeypatch, capsys
) -> None:
    env = _stage(tmp_path, monkeypatch, agent="gemini", mode="synthesis")
    (env["workdir"] / "inbox" / "task.json").write_text(_MALFORMED)

    out = _run_gemini(env["session_id"])
    captured = capsys.readouterr()

    assert out["decision"] == "allow"
    assert "task_read" in captured.err
    assert "json decode" in captured.err.lower()
    assert "BeforeModel" in captured.err

    rows = _ledger.read_events(env["session_id"], "gemini")
    task_rows = [r for r in rows if r.get("verb") == "task_read"]
    assert task_rows
    invalid_rows = [r for r in task_rows if r.get("outcome") == "invalid"]
    assert len(invalid_rows) == 1
    assert invalid_rows[0].get("detail", {}).get("reason") == "json_decode_error"
    assert not _ledger.has_verb(rows, "task_read", outcome="allow")


def test_gemini_feedback_read_malformed_json_writes_invalid_ledger_row(
    tmp_path, monkeypatch, capsys
) -> None:
    env = _stage(
        tmp_path, monkeypatch, agent="gemini",
        mode="synthesis", phase="cross_examination",
    )
    (env["workdir"] / "inbox" / "task.json").write_text(
        json.dumps({"task_id": "T-w108", "specification": "x"})
    )
    (env["workdir"] / "inbox" / "feedback.json").write_text(_MALFORMED)

    out = _run_gemini(env["session_id"])
    captured = capsys.readouterr()

    assert out["decision"] == "allow"
    assert "feedback_read" in captured.err
    assert "json decode" in captured.err.lower()

    rows = _ledger.read_events(env["session_id"], "gemini")
    fb_rows = [r for r in rows if r.get("verb") == "feedback_read"]
    assert fb_rows
    invalid_rows = [r for r in fb_rows if r.get("outcome") == "invalid"]
    assert len(invalid_rows) == 1
    assert invalid_rows[0].get("detail", {}).get("reason") == "json_decode_error"
    assert not _ledger.has_verb(rows, "feedback_read", outcome="allow")


def test_gemini_task_well_formed_emits_allow_no_invalid(tmp_path, monkeypatch) -> None:
    env = _stage(tmp_path, monkeypatch, agent="gemini", mode="synthesis")
    (env["workdir"] / "inbox" / "task.json").write_text(
        json.dumps({"task_id": "T-w108", "specification": "x"})
    )

    out = _run_gemini(env["session_id"])
    assert out["decision"] == "allow"

    rows = _ledger.read_events(env["session_id"], "gemini")
    task_rows = [r for r in rows if r.get("verb") == "task_read"]
    assert any(r.get("outcome") == "allow" for r in task_rows)
    assert not any(r.get("outcome") == "invalid" for r in task_rows)


if __name__ == "__main__":
    import pytest  # noqa: E402
    raise SystemExit(pytest.main([__file__, "-v"]))
