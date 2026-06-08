"""Append-only conversation transcript model and serialization.

This module defines the on-the-wire shapes for the overseer conversation log:

* :class:`Turn` -- one append-only entry in the conversation, carrying its
  ordinal ``index``, the speaker ``role``, a per-turn ``mode`` label (which
  drives the UI color code), and the raw ``content``.
* :class:`Message` -- the simplified ``role``/``content`` form used when a
  prefix of the conversation is resent to the model.

It also provides lossless JSONL (de)serialization, secret redaction, and a
cache-friendly :func:`reconstruct_prefix` that rebuilds a byte-identical
prefix so it actually hits the model's prefix cache (constraint 8).

Stdlib only.
"""
from __future__ import annotations
import json
import re
from dataclasses import asdict, dataclass
__all__ = ['Turn', 'Message', 'to_jsonl', 'from_jsonl', 'redact', 'reconstruct_prefix']

@dataclass
class Turn:
    """One append-only entry in the conversation transcript.

    Attributes:
        index: Monotonic ordinal position of the turn in the conversation.
        role: The speaker, e.g. ``"user"`` or ``"assistant"``.
        mode: Per-turn mode label that drives the UI color code.
        content: The raw, verbatim text content of the turn.
    """
    index: int
    role: str
    mode: str
    content: str

@dataclass
class Message:
    """Simplified prefix form of a turn: just ``role`` and ``content``."""
    role: str
    content: str

def to_jsonl(turn: Turn) -> str:
    """Serialize ``turn`` to a single-line JSONL string.

    ``json.dumps`` escapes newlines, tabs, and other control characters so the
    result occupies exactly one physical line, making the round-trip lossless.
    """
    return json.dumps(asdict(turn), ensure_ascii=False, sort_keys=True)

def from_jsonl(line: str) -> Turn:
    """Parse a single JSONL ``line`` back into a :class:`Turn`."""
    data = json.loads(line)
    return Turn(index=data['index'], role=data['role'], mode=data['mode'], content=data['content'])
_SECRET_RE = re.compile('[0-9a-fA-F]{40,}')

def redact(text: str) -> str:
    """Replace operator-secret-shaped tokens (>=40 hex chars) with ``[REDACTED]``.

    Ordinary text containing no such token is returned unchanged.
    """
    return _SECRET_RE.sub('[REDACTED]', text)

def reconstruct_prefix(turns: list[Turn], up_to_index: int) -> list[Message]:
    """Return the verbatim prefix of ``turns`` as :class:`Message` objects.

    Includes every turn whose ``index`` is ``<= up_to_index``, in chronological
    order, mapping each to a ``Message(role, content)``. Content is copied
    byte-for-byte so the resent prefix is byte-identical for cache correctness.
    """
    return [Message(role=turn.role, content=turn.content) for turn in turns if turn.index <= up_to_index]