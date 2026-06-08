"""RED oracle for overseer/transcript.py — append-only conversation model.

Pins ``Turn``/``Message`` shapes, JSONL round-trip, secret redaction, and the
cache-friendly ``reconstruct_prefix`` (constraint 8: the resent prefix must be
VERBATIM/byte-identical so it actually hits claude's prefix cache).
"""
import dataclasses

import pytest

from overseer.transcript import (
    Turn,
    Message,
    to_jsonl,
    from_jsonl,
    redact,
    reconstruct_prefix,
)


def _turn(index, role, mode, content):
    return Turn(index=index, role=role, mode=mode, content=content)


def test_turn_carries_index_role_mode_and_content():
    fields = {f.name for f in dataclasses.fields(Turn)}
    assert {"index", "role", "mode", "content"} <= fields
    t = _turn(0, "user", "observe", "hello")
    assert t.index == 0
    assert t.role == "user"
    assert t.mode == "observe"  # per-turn mode label drives the UI color code
    assert t.content == "hello"


def test_message_is_the_prefix_form_role_plus_content():
    fields = {f.name for f in dataclasses.fields(Message)}
    assert {"role", "content"} <= fields
    m = Message(role="assistant", content="hi")
    assert m.role == "assistant"
    assert m.content == "hi"


def test_jsonl_round_trip_is_lossless():
    t = _turn(3, "assistant", "analyze", "line one\nline two\twith tab")
    line = to_jsonl(t)
    assert isinstance(line, str)
    assert "\n" not in line.rstrip("\n")  # exactly one physical JSONL line
    back = from_jsonl(line)
    assert back == t  # dataclass equality: every field preserved verbatim


def test_redact_strips_operator_secret_shaped_tokens():
    secret = "a1b2c3d4e5f60718293a4b5c6d7e8f9012345678"  # 40 hex chars
    text = f"the provenance key is {secret} keep it safe"
    out = redact(text)
    assert secret not in out
    assert "[REDACTED]" in out


def test_redact_leaves_ordinary_text_untouched():
    text = "just a normal sentence with no secrets in it."
    assert redact(text) == text


def test_reconstruct_prefix_is_verbatim_and_bounded():
    turns = [
        _turn(0, "user", "observe", "first user"),
        _turn(1, "assistant", "observe", "first assistant"),
        _turn(2, "user", "analyze", "second user"),
        _turn(3, "assistant", "analyze", "second assistant"),
    ]
    prefix = reconstruct_prefix(turns, up_to_index=1)
    # Only turns 0 and 1, in order, as Message (role+content) — VERBATIM.
    assert [type(m) for m in prefix] == [Message, Message]
    assert [(m.role, m.content) for m in prefix] == [
        ("user", "first user"),
        ("assistant", "first assistant"),
    ]


def test_reconstruct_prefix_does_not_paraphrase_or_rewrap():
    # The exact original bytes must survive (cache-prefix correctness).
    weird = "  leading spaces, trailing  \n embedded newline, \t tab "
    turns = [_turn(0, "user", "observe", weird)]
    prefix = reconstruct_prefix(turns, up_to_index=0)
    assert prefix[0].content == weird


def test_reconstruct_full_prefix_when_up_to_index_is_last():
    turns = [_turn(i, "user" if i % 2 == 0 else "assistant", "observe", f"t{i}") for i in range(5)]
    prefix = reconstruct_prefix(turns, up_to_index=4)
    assert len(prefix) == 5
    assert [m.content for m in prefix] == [f"t{i}" for i in range(5)]
