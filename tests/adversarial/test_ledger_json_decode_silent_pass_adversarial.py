"""W109 adversarial — _ledger.read_events JSON decode silent-pass fix.

Pre-fix: harness/hooks/_ledger.py:read_events bare 'except
json.JSONDecodeError: continue' silently dropped corrupted rows with no
stderr trace. Operators couldn't distinguish 'no rows' from
'rows-but-some-corrupted'. We CANNOT append an invalid ledger row inside
read_events (chicken/egg: we're failing to read the ledger we'd write
into), so the fix is stderr-only.

Post-fix: stderr trace `_ledger read_events JSON decode error at <path>
line N: <exc>` for each corrupted row; valid rows still preserved in
order; silent skip remains the design.
"""
from __future__ import annotations

import json
import pathlib
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from harness.hooks import _ledger  # noqa: E402


def _valid_row(verb: str, outcome: str = "allow") -> str:
    return json.dumps(
        {
            "ts": "2026-04-26T00:00:00Z",
            "session_id": "w109",
            "agent": "claude",
            "round": 1,
            "phase": "synthesis",
            "hook": "TestHook",
            "tool": "",
            "verb": verb,
            "outcome": outcome,
            "counters": {},
            "digest": "",
            "detail": {},
        }
    )


def test_corrupt_row_skipped_valid_rows_returned(tmp_path: pathlib.Path, capsys) -> None:
    ledger = tmp_path / "test.ledger.jsonl"
    ledger.write_text(
        _valid_row("submission")
        + "\n{not valid json\n"
        + _valid_row("clarification")
        + "\n",
        encoding="utf-8",
    )

    rows = _ledger.read_events("w109", "claude", path=ledger)

    assert len(rows) == 2
    assert rows[0]["verb"] == "submission"
    assert rows[1]["verb"] == "clarification"

    err = capsys.readouterr().err
    assert "_ledger read_events JSON decode error" in err
    assert str(ledger) in err
    assert "line 2" in err


def test_all_corrupt_rows_returns_empty_list(tmp_path: pathlib.Path, capsys) -> None:
    ledger = tmp_path / "all_bad.ledger.jsonl"
    ledger.write_text(
        "{not json\n"
        "garbage\n"
        "[[[\n"
        "}}}\n"
        "{\"unterminated\":\n",
        encoding="utf-8",
    )

    rows = _ledger.read_events("w109", "claude", path=ledger)

    assert rows == []

    err = capsys.readouterr().err
    decode_count = err.count("_ledger read_events JSON decode error")
    assert decode_count == 5, f"expected 5 stderr traces, got {decode_count}: {err!r}"


def test_negative_control_all_valid_no_stderr(tmp_path: pathlib.Path, capsys) -> None:
    ledger = tmp_path / "all_good.ledger.jsonl"
    rows_text = "\n".join(_valid_row(f"verb_{i}") for i in range(5)) + "\n"
    ledger.write_text(rows_text, encoding="utf-8")

    rows = _ledger.read_events("w109", "claude", path=ledger)

    assert len(rows) == 5
    for i, row in enumerate(rows):
        assert row["verb"] == f"verb_{i}"

    err = capsys.readouterr().err
    assert "_ledger read_events" not in err
    assert err == ""


def test_mixed_valid_corrupt_valid_preserves_order_and_line_numbers(
    tmp_path: pathlib.Path, capsys
) -> None:
    ledger = tmp_path / "mixed.ledger.jsonl"
    ledger.write_text(
        _valid_row("v1")
        + "\nGARBAGE_LINE_2\n"
        + _valid_row("v3")
        + "\n\n"
        + "{also bad\n"
        + _valid_row("v6")
        + "\n",
        encoding="utf-8",
    )

    rows = _ledger.read_events("w109", "claude", path=ledger)

    assert [r["verb"] for r in rows] == ["v1", "v3", "v6"]

    err = capsys.readouterr().err
    assert "line 2" in err, err
    assert "line 5" in err, err
    decode_count = err.count("_ledger read_events JSON decode error")
    assert decode_count == 2, f"expected 2 stderr traces, got {decode_count}"


def test_blank_lines_skipped_silently(tmp_path: pathlib.Path, capsys) -> None:
    ledger = tmp_path / "blanks.ledger.jsonl"
    ledger.write_text(
        "\n"
        + _valid_row("v1")
        + "\n\n   \n"
        + _valid_row("v2")
        + "\n",
        encoding="utf-8",
    )

    rows = _ledger.read_events("w109", "claude", path=ledger)

    assert [r["verb"] for r in rows] == ["v1", "v2"]
    assert capsys.readouterr().err == ""


def test_count_verb_unaffected_by_skipped_corruption(tmp_path: pathlib.Path, capsys) -> None:
    ledger = tmp_path / "count.ledger.jsonl"
    ledger.write_text(
        _valid_row("submission", outcome="allow")
        + "\n{corrupt\n"
        + _valid_row("submission", outcome="allow")
        + "\n",
        encoding="utf-8",
    )

    rows = _ledger.read_events("w109", "claude", path=ledger)
    assert _ledger.count_verb(rows, "submission", outcome="allow") == 2
    assert _ledger.has_verb(rows, "submission", outcome="allow") is True

    err = capsys.readouterr().err
    assert "_ledger read_events JSON decode error" in err
