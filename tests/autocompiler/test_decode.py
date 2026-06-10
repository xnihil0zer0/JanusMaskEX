"""RED oracle — authoritative contract for autocompiler/decode.py (leaf ac-decode-validator).

Contract (Phase B, ``addendum_constrained_decoding.md``): JM has NO in-process
model SDK, so constrained decoding is realized as POST-DECODE schema validation
+ truncation repair over the emitted submission text. The module exposes:

``decode_submission(raw: str) -> dict`` returning EXACTLY the keys
``ok`` (bool), ``payload`` (dict | None), ``repaired`` (bool),
``dropped_edits`` (int), ``reason`` (str). Semantics:

- The valid payload schema is REASONING-FIELD-FIRST: a JSON object with a
  ``reasoning`` str and an ``edits`` list. A COMPLETE edit is a dict with str
  ``file`` and str ``code`` fields; incomplete/malformed edits are DROPPED
  (counted in ``dropped_edits``), never fatal.
- A markdown ```` ```json ```` fence around the document is stripped.
- A TRUNCATED document (cut mid-stream, e.g. token-limit MAX_TOKENS) is
  repaired: recover the intact ``reasoning`` and every complete leading edit,
  drop the torn tail, set ``repaired=True``.
- Anything unrecoverable => ``ok=False, payload=None`` with a non-empty
  ``reason``. The function NEVER raises, for ANY str input.
"""
import json

import pytest

from autocompiler.decode import decode_submission

_CLEAN = json.dumps({
    'reasoning': 'fix the off-by-one in pager',
    'edits': [
        {'file': 'pkg/a.py', 'code': 'def a():\n    return 1\n'},
        {'file': 'pkg/b.py', 'code': 'def b():\n    return 2\n'},
    ],
})


def test_clean_document_passes_unrepaired():
    out = decode_submission(_CLEAN)
    assert out['ok'] is True
    assert out['repaired'] is False
    assert out['dropped_edits'] == 0
    assert out['payload']['reasoning'] == 'fix the off-by-one in pager'
    assert [e['file'] for e in out['payload']['edits']] == ['pkg/a.py', 'pkg/b.py']


def test_fenced_document_is_unwrapped():
    out = decode_submission('```json\n' + _CLEAN + '\n```')
    assert out['ok'] is True
    assert out['payload']['reasoning'] == 'fix the off-by-one in pager'


def test_truncated_tail_is_repaired_reasoning_preserved():
    # Regression: cut mid-way through the SECOND edit (the MAX_TOKENS shape).
    cut = _CLEAN[:_CLEAN.rindex('pkg/b.py') + 3]
    out = decode_submission(cut)
    assert out['ok'] is True
    assert out['repaired'] is True
    assert out['dropped_edits'] >= 1
    assert out['payload']['reasoning'] == 'fix the off-by-one in pager'
    edits = out['payload']['edits']
    assert len(edits) == 1 and edits[0]['file'] == 'pkg/a.py'


def test_incomplete_edit_entries_dropped_not_fatal():
    doc = json.dumps({'reasoning': 'r', 'edits': [
        {'file': 'pkg/a.py', 'code': 'x = 1\n'},
        {'file': 'pkg/missing_code.py'},
        {'code': 'orphan'},
        'not-even-a-dict',
    ]})
    out = decode_submission(doc)
    assert out['ok'] is True
    assert out['dropped_edits'] == 3
    assert len(out['payload']['edits']) == 1


def test_missing_reasoning_fails_schema():
    out = decode_submission(json.dumps({'edits': []}))
    assert out['ok'] is False
    assert out['payload'] is None
    assert 'reasoning' in out['reason']


def test_garbage_returns_not_ok_never_raises():
    for raw in ('', 'not json at all', '[1, 2, 3]', '42', '{', '\x00\xff', 'null'):
        out = decode_submission(raw)
        assert isinstance(out, dict)
        assert out['ok'] is False
        assert out['payload'] is None
        assert isinstance(out['reason'], str) and out['reason']


def test_every_prefix_truncation_is_total():
    # Property: decode_submission is TOTAL over every prefix of a valid doc —
    # it never raises and always returns the full result shape.
    for i in range(len(_CLEAN) + 1):
        out = decode_submission(_CLEAN[:i])
        assert set(out) == {'ok', 'payload', 'repaired', 'dropped_edits', 'reason'}
        assert isinstance(out['ok'], bool)
        if out['ok']:
            assert isinstance(out['payload'], dict)
