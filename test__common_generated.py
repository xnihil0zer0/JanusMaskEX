# ----- write_decision -----
"""Verification oracle for ``harness.hooks._common.write_decision``.

Spec under test (from the reference implementation)::

    def write_decision(payload, stream=None) -> None:
        stream = stream if stream is not None else sys.stdout
        stream.write(json.dumps(payload))
        stream.flush()

Observable contract:
  * serializes ``payload`` with ``json.dumps`` (default options: no key sort,
    default separators, ``ensure_ascii=True``, no trailing newline);
  * writes that exact string to ``stream`` in a single ``write`` call;
  * flushes the stream after writing;
  * returns ``None``;
  * when ``stream`` is omitted / ``None`` it targets ``sys.stdout``.

Each test exercises ``write_decision`` directly and asserts on its effects,
so it FAILS against a ``NotImplementedError`` stub (non-vacuity).
"""
from __future__ import annotations

import io
import json
import sys

import pytest

from harness.hooks._common import write_decision


class _RecordingStream:
    """Stream double recording the order of write/flush operations."""

    def __init__(self) -> None:
        self.events: list[tuple[str, object]] = []
        self.buffer = ""

    def write(self, data) -> int:
        self.events.append(("write", data))
        self.buffer += data
        return len(data)

    def flush(self) -> None:
        self.events.append(("flush", None))


def test_write_decision_writes_serialized_json_to_stream():
    payload = {"decision": "allow", "reason": "ok"}
    stream = io.StringIO()

    write_decision(payload, stream)

    out = stream.getvalue()
    assert out == json.dumps(payload)
    # Round-trips back to the original payload.
    assert json.loads(out) == payload


def test_write_decision_returns_none():
    stream = io.StringIO()
    result = write_decision({"decision": "deny"}, stream)
    assert result is None


def test_write_decision_flushes_after_writing():
    stream = _RecordingStream()

    write_decision({"decision": "allow"}, stream)

    # The full payload was written, then the stream flushed (write precedes flush).
    assert ("flush", None) in stream.events
    write_index = next(i for i, (kind, _) in enumerate(stream.events) if kind == "write")
    flush_index = next(i for i, (kind, _) in enumerate(stream.events) if kind == "flush")
    assert write_index < flush_index


def test_write_decision_single_write_call_with_whole_payload():
    payload = {"a": 1, "b": 2, "c": 3}
    stream = _RecordingStream()

    write_decision(payload, stream)

    writes = [data for kind, data in stream.events if kind == "write"]
    flushes = [e for e in stream.events if e[0] == "flush"]
    assert writes == [json.dumps(payload)]
    assert len(flushes) == 1


def test_write_decision_defaults_to_sys_stdout(monkeypatch):
    fake_stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    payload = {"decision": "allow", "additionalContext": "hi"}
    write_decision(payload)  # stream omitted -> sys.stdout

    assert fake_stdout.getvalue() == json.dumps(payload)


def test_write_decision_none_stream_defaults_to_sys_stdout(monkeypatch):
    fake_stdout = io.StringIO()
    monkeypatch.setattr(sys, "stdout", fake_stdout)

    payload = {"decision": "deny"}
    write_decision(payload, None)  # explicit None -> sys.stdout

    assert fake_stdout.getvalue() == json.dumps(payload)


def test_write_decision_no_trailing_newline_or_whitespace():
    stream = io.StringIO()
    write_decision({"decision": "allow"}, stream)

    out = stream.getvalue()
    assert not out.endswith("\n")
    assert out == out.strip()


def test_write_decision_preserves_key_insertion_order():
    # Default json.dumps does NOT sort keys; insertion order must be preserved.
    payload = {"z": 1, "m": 2, "a": 3}
    stream = io.StringIO()

    write_decision(payload, stream)

    assert stream.getvalue() == '{"z": 1, "m": 2, "a": 3}'


def test_write_decision_empty_payload_writes_empty_object():
    stream = io.StringIO()
    write_decision({}, stream)
    assert stream.getvalue() == "{}"


def test_write_decision_nested_payload_roundtrips():
    payload = {
        "decision": "deny",
        "reason": "blocked",
        "tool_input": {"path": "/etc/passwd", "flags": [1, 2, 3]},
        "meta": {"nested": {"ok": True, "n": None}},
    }
    stream = io.StringIO()

    write_decision(payload, stream)

    out = stream.getvalue()
    assert out == json.dumps(payload)
    assert json.loads(out) == payload


def test_write_decision_non_ascii_uses_default_serialization():
    # Default json.dumps escapes non-ASCII (ensure_ascii=True).
    payload = {"reason": "café"}
    stream = io.StringIO()

    write_decision(payload, stream)

    assert stream.getvalue() == json.dumps(payload)
    assert "\\u00e9" in stream.getvalue()
