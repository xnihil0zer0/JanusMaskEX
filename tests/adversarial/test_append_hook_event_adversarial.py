"""Adversarial battery for harness/hooks/_ledger.py::append_hook_event.

The function is the single write-path for per-session JSONL journals used by 81
call sites across claude/gemini hook code. A silent-append failure here would
blank out hook telemetry without raising, so the goal of this battery is to
ensure it either appends a valid JSON line or fails loudly — never half-write.

Coverage themes (kept lean; the existing tests/hooks/unit/* suite already
exercises the happy paths via integration):
- Type confusion across positional args (session_id, agent, verb, outcome).
- Unicode: NFC/NFD distinct, emoji, unpaired surrogate rejection.
- Boundary: empty strings, very long values, None-coerced mapping kwargs.
- Payload serialisability: non-JSON values (lambda) raise; cycle raises.
- Return shape: row dict has every expected key and preserves caller intent.
- Concurrency: parallel appends from threads preserve JSONL integrity.

Run standalone:
    python -m pytest tests/adversarial/test_append_hook_event_adversarial.py -v
"""

from __future__ import annotations

import json
import pathlib
import sys
import threading

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[2]))

from harness.hooks._ledger import append_hook_event


@pytest.fixture
def ledger_path(tmp_path: pathlib.Path) -> pathlib.Path:
    return tmp_path / "sessions" / "test.ledger.jsonl"


def _read_rows(path: pathlib.Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


class TestHappyPath:
    def test_minimum_args_writes_row(self, ledger_path):
        row = append_hook_event("sess-1", "claude", "write", "allow", path=ledger_path)
        assert row["session_id"] == "sess-1"
        assert row["agent"] == "claude"
        assert row["verb"] == "write"
        assert row["outcome"] == "allow"
        assert row["counters"] == {}
        assert row["detail"] == {}
        assert row["round"] is None
        rows = _read_rows(ledger_path)
        assert rows == [row]

    def test_all_kwargs_preserved_in_row(self, ledger_path):
        row = append_hook_event(
            "sess-2", "gemini", "commit", "deny",
            hook="PreToolUse", tool="Bash", round_number=3, phase="P2",
            counters={"denies": 4}, digest="sha256:abc", detail={"why": "scope"},
            path=ledger_path,
        )
        assert row["hook"] == "PreToolUse"
        assert row["round"] == 3
        assert row["counters"] == {"denies": 4}
        assert row["detail"] == {"why": "scope"}
        on_disk = _read_rows(ledger_path)[0]
        assert on_disk == row


class TestNoneCoercion:
    def test_counters_none_becomes_empty_dict(self, ledger_path):
        row = append_hook_event("s", "claude", "v", "o", counters=None, path=ledger_path)
        assert row["counters"] == {}

    def test_detail_none_becomes_empty_dict(self, ledger_path):
        row = append_hook_event("s", "claude", "v", "o", detail=None, path=ledger_path)
        assert row["detail"] == {}

    def test_round_number_none_preserved_not_omitted(self, ledger_path):
        row = append_hook_event("s", "claude", "v", "o", path=ledger_path)
        assert "round" in row
        assert row["round"] is None


class TestTypeConfusion:
    def test_non_string_verb_still_writes_then_reads(self, ledger_path):
        # int is JSON-serialisable; json.dumps accepts it. The fn doesn't validate types.
        row = append_hook_event("s", "claude", 42, "o", path=ledger_path)
        assert row["verb"] == 42
        assert _read_rows(ledger_path)[0]["verb"] == 42

    def test_bytes_verb_raises_on_json_dump(self, ledger_path):
        with pytest.raises(TypeError):
            append_hook_event("s", "claude", b"bytes-not-json", "o", path=ledger_path)

    def test_none_session_id_serialises_as_null(self, ledger_path):
        row = append_hook_event(None, "claude", "v", "o", path=ledger_path)  # type: ignore[arg-type]
        assert row["session_id"] is None
        assert _read_rows(ledger_path)[0]["session_id"] is None


class TestUnicode:
    def test_nfc_and_nfd_session_ids_round_trip_distinct(self, ledger_path):
        nfc = "café"       # café (NFC, 1 codepoint for é)
        nfd = "café"      # café (NFD, e + combining acute)
        assert nfc != nfd
        append_hook_event(nfc, "claude", "v", "o", path=ledger_path)
        append_hook_event(nfd, "claude", "v", "o", path=ledger_path)
        rows = _read_rows(ledger_path)
        assert [r["session_id"] for r in rows] == [nfc, nfd]

    def test_emoji_in_phase_preserved(self, ledger_path):
        row = append_hook_event("s", "claude", "v", "o", phase="\U0001f4cb review", path=ledger_path)
        assert row["phase"] == "\U0001f4cb review"
        assert _read_rows(ledger_path)[0]["phase"] == "\U0001f4cb review"

    def test_unpaired_surrogate_round_trips_via_json_escape(self, ledger_path):
        # json.dumps defaults to ensure_ascii=True, which escapes surrogates
        # as \udXXX (pure ASCII) — so append succeeds and the surrogate
        # survives round-trip through json.loads without data loss.
        append_hook_event("s", "claude", "v", "o", hook="\ud800", path=ledger_path)
        row = _read_rows(ledger_path)[0]
        assert row["hook"] == "\ud800"


class TestBoundary:
    def test_empty_session_id_allowed(self, ledger_path):
        row = append_hook_event("", "claude", "v", "o", path=ledger_path)
        assert row["session_id"] == ""

    def test_long_digest_preserved(self, ledger_path):
        long_digest = "f" * 10_000
        row = append_hook_event("s", "claude", "v", "o", digest=long_digest, path=ledger_path)
        assert row["digest"] == long_digest
        assert _read_rows(ledger_path)[0]["digest"] == long_digest

    def test_counters_deeply_nested_serialises(self, ledger_path):
        deep = {"k": 1}
        cur = deep
        for _ in range(50):
            cur["nested"] = {"k": 1}
            cur = cur["nested"]
        row = append_hook_event("s", "claude", "v", "o", counters=deep, path=ledger_path)
        round_tripped = _read_rows(ledger_path)[0]
        assert round_tripped["counters"] == deep
        assert row["counters"] is deep  # no defensive copy


class TestPayloadSerialisability:
    def test_lambda_in_counters_raises(self, ledger_path):
        with pytest.raises(TypeError):
            append_hook_event("s", "claude", "v", "o", counters={"fn": lambda x: x}, path=ledger_path)

    def test_cyclic_detail_raises(self, ledger_path):
        cyc: dict = {"k": 1}
        cyc["self"] = cyc
        with pytest.raises((ValueError, RecursionError)):
            append_hook_event("s", "claude", "v", "o", detail=cyc, path=ledger_path)


class TestFilesystem:
    def test_parent_directory_created_automatically(self, tmp_path):
        nested = tmp_path / "a" / "b" / "c" / "ledger.jsonl"
        assert not nested.parent.exists()
        append_hook_event("s", "claude", "v", "o", path=nested)
        assert nested.exists()
        assert _read_rows(nested)[0]["session_id"] == "s"

    def test_appends_not_overwrites(self, ledger_path):
        for i in range(5):
            append_hook_event(f"s-{i}", "claude", "v", "o", path=ledger_path)
        rows = _read_rows(ledger_path)
        assert [r["session_id"] for r in rows] == [f"s-{i}" for i in range(5)]


class TestReturnShape:
    def test_returned_row_has_all_schema_keys(self, ledger_path):
        row = append_hook_event("s", "claude", "v", "o", path=ledger_path)
        expected = {"ts", "session_id", "agent", "round", "phase", "hook",
                    "tool", "verb", "outcome", "counters", "digest", "detail"}
        assert set(row.keys()) >= expected

    def test_timestamp_iso8601_utc_z_suffix(self, ledger_path):
        row = append_hook_event("s", "claude", "v", "o", path=ledger_path)
        ts = row["ts"]
        assert ts.endswith("Z")
        # Format: YYYY-MM-DDTHH:MM:SSZ
        assert len(ts) == 20
        assert ts[4] == "-" and ts[7] == "-" and ts[10] == "T" and ts[13] == ":"


class TestConcurrency:
    def test_parallel_appends_preserve_jsonl_integrity(self, ledger_path):
        n_threads = 8
        rows_per_thread = 25
        barrier = threading.Barrier(n_threads)

        def worker(tid: int) -> None:
            barrier.wait()
            for i in range(rows_per_thread):
                append_hook_event(
                    f"sess-{tid}", "claude", "write", "allow",
                    counters={"tid": tid, "i": i}, path=ledger_path,
                )

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        rows = _read_rows(ledger_path)
        assert len(rows) == n_threads * rows_per_thread
        # Every row must be valid JSON (no interleaved writes corrupted a line)
        # and carry a well-formed counters dict.
        for r in rows:
            assert isinstance(r.get("counters"), dict)
            assert "tid" in r["counters"]
            assert "i" in r["counters"]
