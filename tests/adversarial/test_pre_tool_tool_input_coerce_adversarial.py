"""W110 adversarial — pre_tool non-dict tool_input coercion.

Pre-fix: harness/hooks/{claude,gemini}/pre_tool.py:main used
`tool_input = payload.get('tool_input') or {}` which only fallback-
coerces falsy values. A truthy non-dict (list/string/int) bypassed
`or {}` and propagated to _decide_read_like / _decide_write /
_decide_write_or_replace, which call .get() on it -> AttributeError
crash. The existing shadow-coerce at L429/L479 was unreachable.

Post-fix: at main(), after gathering session_id/agent/round_number/
phase, isinstance-check tool_input_raw; if non-None and non-dict,
write stderr trace + ledger row verb='tool_input_coerce'
outcome='invalid' tool=<tool_name> detail={reason,type}, then coerce to
{} for downstream. Twin parity: identical fix on both files.
"""
from __future__ import annotations

import io
import json
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

import harness.hooks.claude.pre_tool as claude_pt  # noqa: E402
import harness.hooks.gemini.pre_tool as gemini_pt  # noqa: E402
from harness.hooks import _ledger  # noqa: E402


def _stage(tmp_path, monkeypatch, *, agent: str, mode: str = "synthesis"):
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    (state / "sessions").mkdir(parents=True, exist_ok=True)
    workdir = state / "workdirs" / agent / "sess-w110"
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
    return {"state": state, "workdir": workdir, "session_id": "sess-w110"}


def _run_claude(tool_name, tool_input):
    payload = {
        "hook_event_name": "PreToolUse",
        "session_id": "sess-w110",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    claude_pt.main(stdin, stdout)
    return json.loads(stdout.getvalue())


def _run_gemini(tool_name, tool_input):
    payload = {
        "hook_event_name": "BeforeTool",
        "session_id": "sess-w110",
        "tool_name": tool_name,
        "tool_input": tool_input,
    }
    stdin = io.StringIO(json.dumps(payload))
    stdout = io.StringIO()
    gemini_pt.main(stdin, stdout)
    return json.loads(stdout.getvalue())


def _invalid_rows(session_id: str, agent: str):
    rows = _ledger.read_events(session_id, agent)
    return [
        r
        for r in rows
        if r.get("verb") == "tool_input_coerce" and r.get("outcome") == "invalid"
    ]


# -- Claude twin -----------------------------------------------------------


class TestClaudeNonDictCoercion:
    def test_list_tool_input_does_not_crash_and_logs_invalid(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="claude")
        out = _run_claude("Write", [1, 2, 3])

        assert out["decision"] == "deny"

        invalids = _invalid_rows(env["session_id"], "claude")
        assert len(invalids) == 1
        row = invalids[0]
        assert row["hook"] == "PreToolUse"
        assert row["tool"] == "Write"
        assert row["detail"]["reason"] == "non_dict_tool_input"
        assert row["detail"]["type"] == "list"

        err = capsys.readouterr().err
        assert "PreToolUse tool_input_coerce" in err
        assert "list" in err

    def test_string_tool_input_does_not_crash_and_logs_invalid(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="claude")
        out = _run_claude("Read", "/etc/passwd")

        # Pre-fix: AttributeError crash. Post-fix: hook completes with a
        # well-formed decision (the coerced {} runs through the normal
        # decide_read_like path, so the precise allow/deny depends on the
        # tool's no-path branch — we don't pin it).
        assert out["decision"] in ("allow", "deny")

        invalids = _invalid_rows(env["session_id"], "claude")
        assert len(invalids) == 1
        assert invalids[0]["detail"]["type"] == "str"
        assert invalids[0]["tool"] == "Read"

    def test_dict_tool_input_emits_no_invalid_row_negative_control(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="claude")
        target = str(env["workdir"] / "inbox" / "task.json")
        out = _run_claude("Read", {"file_path": target})

        assert out["decision"] == "allow"
        assert _invalid_rows(env["session_id"], "claude") == []

        err = capsys.readouterr().err
        assert "tool_input_coerce" not in err

    def test_none_tool_input_emits_no_invalid_row(
        self, tmp_path, monkeypatch
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="claude")
        out = _run_claude("Write", None)

        assert out["decision"] == "deny"
        assert _invalid_rows(env["session_id"], "claude") == []


# -- Gemini twin -----------------------------------------------------------


class TestGeminiNonDictCoercion:
    def test_list_tool_input_does_not_crash_and_logs_invalid(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="gemini")
        out = _run_gemini("write_file", [1, 2, 3])

        assert out["decision"] == "deny"

        invalids = _invalid_rows(env["session_id"], "gemini")
        assert len(invalids) == 1
        row = invalids[0]
        assert row["hook"] == "BeforeTool"
        assert row["tool"] == "write_file"
        assert row["detail"]["reason"] == "non_dict_tool_input"
        assert row["detail"]["type"] == "list"

        err = capsys.readouterr().err
        assert "BeforeTool tool_input_coerce" in err
        assert "list" in err

    def test_string_tool_input_does_not_crash_and_logs_invalid(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="gemini")
        out = _run_gemini("read_file", "/etc/passwd")

        assert out["decision"] in ("allow", "deny")
        invalids = _invalid_rows(env["session_id"], "gemini")
        assert len(invalids) == 1
        assert invalids[0]["detail"]["type"] == "str"
        assert invalids[0]["tool"] == "read_file"

    def test_dict_tool_input_emits_no_invalid_row_negative_control(
        self, tmp_path, monkeypatch, capsys
    ) -> None:
        env = _stage(tmp_path, monkeypatch, agent="gemini")
        target = str(env["workdir"] / "inbox" / "task.json")
        out = _run_gemini("read_file", {"file_path": target})

        assert out["decision"] == "allow"
        assert _invalid_rows(env["session_id"], "gemini") == []

        err = capsys.readouterr().err
        assert "tool_input_coerce" not in err


# -- Twin asymmetry pin ----------------------------------------------------


class TestTwinParity:
    def test_both_twins_use_same_verb_and_detail_keys(
        self, tmp_path, monkeypatch
    ) -> None:
        env_c = _stage(tmp_path / "c", monkeypatch, agent="claude")
        _run_claude("Write", [1, 2, 3])
        claude_rows = _invalid_rows(env_c["session_id"], "claude")

        env_g = _stage(tmp_path / "g", monkeypatch, agent="gemini")
        _run_gemini("write_file", [1, 2, 3])
        gemini_rows = _invalid_rows(env_g["session_id"], "gemini")

        assert len(claude_rows) == 1
        assert len(gemini_rows) == 1
        c, g = claude_rows[0], gemini_rows[0]

        assert c["verb"] == g["verb"] == "tool_input_coerce"
        assert c["outcome"] == g["outcome"] == "invalid"
        assert set(c["detail"].keys()) == set(g["detail"].keys()) == {
            "reason",
            "type",
        }
        assert c["detail"]["reason"] == g["detail"]["reason"] == "non_dict_tool_input"
        assert c["detail"]["type"] == g["detail"]["type"] == "list"
