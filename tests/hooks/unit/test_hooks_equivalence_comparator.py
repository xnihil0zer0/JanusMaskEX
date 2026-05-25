"""Unit coverage for the harness.hooks_equivalence comparator half (HOOK-51).

Exercises the pieces that ingest MCP audit + shadow log rows, project them
into the common (tool_name, args_hash, decision) diff key, and emit
``state/hooks/equiv_report_<session>.json``. The writer half is covered by
test_hooks_equivalence.py.
"""

from __future__ import annotations

import io
import json
import pathlib
import subprocess
import sys

import pytest

from harness import hooks_equivalence as he


# -- JSONL readers ----------------------------------------------------------


def _write_jsonl(path: pathlib.Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")


def test_load_jsonl_returns_rows(tmp_path):
    p = tmp_path / "log.jsonl"
    _write_jsonl(p, [{"a": 1}, {"a": 2}, {"a": 3}])
    rows = he.load_jsonl(p)
    assert rows == [{"a": 1}, {"a": 2}, {"a": 3}]


def test_load_jsonl_missing_file_returns_empty(tmp_path):
    assert he.load_jsonl(tmp_path / "nope.jsonl") == []


def test_load_jsonl_skips_malformed_lines(tmp_path):
    p = tmp_path / "log.jsonl"
    p.write_text('{"ok": 1}\ngarbage{\n{"ok": 2}\n', encoding="utf-8")
    rows = he.load_jsonl(p)
    assert rows == [{"ok": 1}, {"ok": 2}]


def test_load_shadow_log_reads_session_file(tmp_path):
    shadow = tmp_path / "shadow"
    shadow.mkdir()
    _write_jsonl(
        shadow / "sess-A.jsonl",
        [{"tool_name": "Write", "args_hash": "abc", "policy_decision": "allow"}],
    )
    rows = he.load_shadow_log("sess-A", shadow_dir=shadow)
    assert rows[0]["tool_name"] == "Write"


def test_load_mcp_audit_reads_state_sessions_ledger(tmp_path):
    root = tmp_path / "state"
    sessions = root / "sessions"
    sessions.mkdir(parents=True)
    _write_jsonl(
        sessions / "claude_sess-A.ledger.jsonl",
        [{"tool": "Write", "outcome": "allow", "digest": "d1"}],
    )
    rows = he.load_mcp_audit("sess-A", audit_root=root)
    assert len(rows) == 1
    assert rows[0]["tool"] == "Write"


def test_load_mcp_audit_concats_multi_agent_files(tmp_path):
    root = tmp_path / "state"
    (root / "sessions").mkdir(parents=True)
    _write_jsonl(
        root / "sessions" / "claude_sess-A.ledger.jsonl",
        [{"tool": "Write", "outcome": "allow"}],
    )
    _write_jsonl(
        root / "sessions" / "gemini_sess-A.ledger.jsonl",
        [{"tool": "write_file", "outcome": "deny"}],
    )
    rows = he.load_mcp_audit("sess-A", audit_root=root)
    assert len(rows) == 2
    tools = {r["tool"] for r in rows}
    assert tools == {"Write", "write_file"}


def test_load_mcp_audit_missing_root_returns_empty(tmp_path):
    assert he.load_mcp_audit("sess-X", audit_root=tmp_path / "nope") == []


# -- diff-key normalisers ---------------------------------------------------


def test_shadow_diff_key_projects_three_tuple():
    row = {
        "tool_name": "Write",
        "args_hash": "abc1234567890def",
        "policy_decision": "deny",
        "extra": "ignored",
    }
    assert he.shadow_diff_key(row) == ("Write", "abc1234567890def", "deny")


def test_shadow_diff_key_missing_fields_default_empty():
    assert he.shadow_diff_key({}) == ("", "", "")


def test_mcp_diff_key_projects_tool_digest_outcome():
    row = {"tool": "Write", "digest": "d1", "outcome": "allow"}
    assert he.mcp_diff_key(row) == ("Write", "d1", "allow")


def test_mcp_diff_key_prefers_args_hash_over_digest():
    row = {"tool": "Write", "args_hash": "preferred", "digest": "fallback", "outcome": "allow"}
    assert he.mcp_diff_key(row) == ("Write", "preferred", "allow")


def test_mcp_diff_key_collapses_rate_limited_to_deny():
    row = {"tool": "Write", "digest": "d", "outcome": "rate_limited"}
    assert he.mcp_diff_key(row) == ("Write", "d", "deny")


def test_mcp_diff_key_collapses_invalid_to_deny():
    row = {"tool": "Write", "digest": "d", "outcome": "invalid"}
    assert he.mcp_diff_key(row) == ("Write", "d", "deny")


def test_mcp_diff_key_accepts_tool_name_alias():
    row = {"tool_name": "Read", "args_hash": "h", "decision": "allow"}
    assert he.mcp_diff_key(row) == ("Read", "h", "allow")


# -- compare (multiset diff) -----------------------------------------------


def _shadow(tool: str, ah: str, dec: str, reason: str = "") -> dict:
    return {"tool_name": tool, "args_hash": ah, "policy_decision": dec, "policy_reason": reason}


def _mcp(tool: str, ah: str, outcome: str) -> dict:
    return {"tool": tool, "digest": ah, "outcome": outcome}


def test_compare_identical_logs_match_rate_one():
    shadow = [_shadow("Write", "a", "allow"), _shadow("Read", "b", "allow")]
    mcp = [_mcp("Write", "a", "allow"), _mcp("Read", "b", "allow")]
    rep = he.compare(shadow, mcp, session_id="s")
    assert rep.match_rate == 1.0
    assert rep.divergences == []
    assert rep.shadow_count == 2 and rep.mcp_count == 2


def test_compare_both_empty_is_clean():
    rep = he.compare([], [], session_id="s")
    assert rep.match_rate == 1.0
    assert rep.divergences == []


def test_compare_shadow_only_row_is_divergence():
    rep = he.compare([_shadow("Write", "a", "allow")], [], session_id="s")
    assert rep.match_rate == 0.0
    assert len(rep.divergences) == 1
    assert rep.divergences[0]["source"] == "shadow"
    assert rep.divergences[0]["key"] == ("Write", "a", "allow")


def test_compare_mcp_only_row_is_divergence():
    rep = he.compare([], [_mcp("Write", "a", "allow")], session_id="s")
    assert rep.match_rate == 0.0
    assert len(rep.divergences) == 1
    assert rep.divergences[0]["source"] == "mcp"


def test_compare_decision_mismatch_yields_two_divergences():
    # Hook denies, MCP allowed: the same (tool, hash) but different decision.
    shadow = [_shadow("Write", "a", "deny")]
    mcp = [_mcp("Write", "a", "allow")]
    rep = he.compare(shadow, mcp, session_id="s")
    # Each side has one row the other doesn't match → two divergences.
    assert len(rep.divergences) == 2
    sources = {d["source"] for d in rep.divergences}
    assert sources == {"shadow", "mcp"}


def test_compare_order_insensitive_multiset():
    shadow = [_shadow("A", "1", "allow"), _shadow("B", "2", "deny")]
    mcp = [_mcp("B", "2", "deny"), _mcp("A", "1", "allow")]
    rep = he.compare(shadow, mcp, session_id="s")
    assert rep.match_rate == 1.0


def test_compare_duplicate_rows_counted():
    shadow = [_shadow("Write", "a", "allow")] * 3
    mcp = [_mcp("Write", "a", "allow")] * 2
    rep = he.compare(shadow, mcp, session_id="s")
    # Shadow has one extra copy → exactly one divergence.
    assert len(rep.divergences) == 1
    assert rep.divergences[0]["source"] == "shadow"
    # match_rate = (total - divergences) / total, total = max(3, 2) = 3
    assert rep.match_rate == pytest.approx(2 / 3)


def test_compare_rate_limited_vs_deny_is_equivalent():
    """MCP 'rate_limited' outcome must normalise to 'deny' and match a
    shadow-side 'deny' decision for the same (tool, hash)."""
    shadow = [_shadow("Write", "h", "deny")]
    mcp = [_mcp("Write", "h", "rate_limited")]
    rep = he.compare(shadow, mcp, session_id="s")
    assert rep.match_rate == 1.0


# -- EquivReport / emit_report ---------------------------------------------


def test_equiv_report_to_dict_serialises_tuple_keys_as_lists():
    shadow = [_shadow("Write", "a", "deny")]
    rep = he.compare(shadow, [], session_id="s")
    dct = rep.to_dict()
    assert dct["match_rate"] == 0.0
    assert dct["divergences"][0]["key"] == ["Write", "a", "deny"]
    assert dct["session_id"] == "s"
    assert dct["shadow_count"] == 1
    assert dct["mcp_count"] == 0


def test_equiv_report_round_trips_json():
    rep = he.compare([], [], session_id="s")
    text = json.dumps(rep.to_dict())
    restored = json.loads(text)
    assert restored["match_rate"] == 1.0
    assert restored["divergences"] == []


def test_emit_report_writes_to_default_output_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_PROJECT_DIR", str(tmp_path))
    rep = he.compare(
        [_shadow("Write", "a", "allow")],
        [_mcp("Write", "a", "allow")],
        session_id="outfile-1",
    )
    target = he.emit_report(rep)
    assert target.exists()
    assert target.name == "equiv_report_outfile-1.json"
    assert target.parent == tmp_path / "state" / "hooks"
    body = json.loads(target.read_text())
    assert body["session_id"] == "outfile-1"
    assert body["match_rate"] == 1.0


def test_emit_report_custom_output_dir(tmp_path):
    rep = he.compare([], [], session_id="custom")
    target = he.emit_report(rep, output_dir=tmp_path)
    assert target == tmp_path / "equiv_report_custom.json"
    assert target.exists()


def test_emit_report_generated_at_is_iso(tmp_path):
    rep = he.compare([], [], session_id="ts")
    target = he.emit_report(rep, output_dir=tmp_path)
    body = json.loads(target.read_text())
    import re
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", body["generated_at"])


# -- run_comparison end-to-end ---------------------------------------------


def test_run_comparison_end_to_end_clean(tmp_path):
    shadow_dir = tmp_path / "shadow"
    audit_root = tmp_path / "state"
    output_dir = tmp_path / "reports"

    _write_jsonl(
        shadow_dir / "sess-e2e.jsonl",
        [_shadow("Write", "abc", "allow")],
    )
    _write_jsonl(
        audit_root / "sessions" / "claude_sess-e2e.ledger.jsonl",
        [{"tool": "Write", "digest": "abc", "outcome": "allow"}],
    )

    rep = he.run_comparison(
        "sess-e2e",
        shadow_dir=shadow_dir,
        audit_root=audit_root,
        output_dir=output_dir,
    )
    assert rep.match_rate == 1.0
    assert (output_dir / "equiv_report_sess-e2e.json").exists()


def test_run_comparison_end_to_end_divergent(tmp_path):
    shadow_dir = tmp_path / "shadow"
    audit_root = tmp_path / "state"
    output_dir = tmp_path / "reports"

    _write_jsonl(
        shadow_dir / "sess-x.jsonl",
        [_shadow("Write", "abc", "deny")],
    )
    _write_jsonl(
        audit_root / "sessions" / "claude_sess-x.ledger.jsonl",
        [{"tool": "Write", "digest": "abc", "outcome": "allow"}],
    )

    rep = he.run_comparison(
        "sess-x",
        shadow_dir=shadow_dir,
        audit_root=audit_root,
        output_dir=output_dir,
    )
    assert rep.match_rate < 1.0
    body = json.loads((output_dir / "equiv_report_sess-x.json").read_text())
    assert body["match_rate"] == rep.match_rate
    assert len(body["divergences"]) == 2


# -- CLI entrypoint ---------------------------------------------------------


def test_cli_exits_zero_on_clean_match(tmp_path):
    shadow_dir = tmp_path / "shadow"
    audit_root = tmp_path / "state"
    output_dir = tmp_path / "reports"

    _write_jsonl(
        shadow_dir / "cli-clean.jsonl",
        [_shadow("Write", "h", "allow")],
    )
    _write_jsonl(
        audit_root / "sessions" / "claude_cli-clean.ledger.jsonl",
        [{"tool": "Write", "digest": "h", "outcome": "allow"}],
    )

    rc = he.main([
        "cli-clean",
        "--shadow-dir", str(shadow_dir),
        "--audit-root", str(audit_root),
        "--output-dir", str(output_dir),
    ])
    assert rc == 0


def test_cli_exits_one_on_divergence(tmp_path):
    shadow_dir = tmp_path / "shadow"
    audit_root = tmp_path / "state"
    output_dir = tmp_path / "reports"

    _write_jsonl(shadow_dir / "cli-bad.jsonl", [_shadow("Write", "h", "deny")])
    _write_jsonl(
        audit_root / "sessions" / "claude_cli-bad.ledger.jsonl",
        [{"tool": "Write", "digest": "h", "outcome": "allow"}],
    )

    rc = he.main([
        "cli-bad",
        "--shadow-dir", str(shadow_dir),
        "--audit-root", str(audit_root),
        "--output-dir", str(output_dir),
    ])
    assert rc == 1
