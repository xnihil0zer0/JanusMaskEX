"""RED oracle — authoritative contract for the ac-wire-decode leaf
(harness/orchestrator_worker.py accept chokepoint).

Contract: a NEW module-level bridge ``_decode_check_safe(payload: dict,
state_dir=None) -> None`` in ``harness/orchestrator_worker.py``, invoked from
``_print_json_line`` AFTER the JSON line is written + flushed (alongside
``_reap_spent_briefs_safe`` / ``_purge_stale_sidecars_safe``). Behavior:

- Resolves the flag AT CALL TIME via ``from autocompiler.flags import
  ac_enabled`` inside the body; OFF (the live default) => returns immediately,
  no ledger row, the emitted JSON line byte-identical to today.
- ON (``ac_enabled('decode')``) and the payload carries a str ``task_id``:
  reads the raw emission ``<state_dir>/output/<task_id>.py`` when it exists,
  runs ``autocompiler.decode.decode_submission`` over it, and appends ONE
  observability row to ``<state_dir>/impl_progress.jsonl``:
  ``{"event": "decode_check", "task_id", "ok", "repaired", "dropped_edits"}``.
  Missing emission file => no row. Gating is NOT affected — this is
  observability only.
- ``state_dir=None`` resolves the repo-standard ``<repo_root>/state`` exactly
  like ``_purge_stale_sidecars_safe``.
- TOTAL: a raising flag reader, a raising decode_submission, unreadable files,
  or a garbage payload can NEVER raise back into ``_print_json_line``.
"""
import inspect
import json

import pytest

import harness.orchestrator_worker as worker_mod
from harness.orchestrator_worker import _decode_check_safe, _print_json_line


def _rows(state_dir):
    ledger = state_dir / 'impl_progress.jsonl'
    if not ledger.exists():
        return []
    return [json.loads(line) for line in ledger.read_text().splitlines() if line.strip()]


def test_bridge_is_wired_into_print_json_line():
    src = inspect.getsource(_print_json_line)
    assert '_decode_check_safe(' in src, \
        '_print_json_line must invoke the decode bridge after emitting the line'


def test_flag_off_no_row_and_line_identical(tmp_path, capsys):
    payload = {'task_id': 'tdec-off', 'outcome': 'accepted'}
    _print_json_line(payload)  # live default config: decode flag OFF
    out = capsys.readouterr().out
    assert out == json.dumps(payload) + '\n'
    _decode_check_safe(payload, state_dir=tmp_path)
    assert _rows(tmp_path) == []


def test_flag_on_appends_decode_check_row(tmp_path, monkeypatch):
    import autocompiler.flags as flags_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: key == 'decode')
    (tmp_path / 'output').mkdir(parents=True)
    doc = json.dumps({'reasoning': 'r', 'edits': [{'file': 'a.py', 'code': 'x = 1\n'}]})
    (tmp_path / 'output' / 'tdec-on.py').write_text(doc, encoding='utf-8')
    _decode_check_safe({'task_id': 'tdec-on', 'outcome': 'accepted'}, state_dir=tmp_path)
    rows = [r for r in _rows(tmp_path) if r.get('event') == 'decode_check']
    assert len(rows) == 1
    row = rows[0]
    assert row['task_id'] == 'tdec-on'
    assert row['ok'] is True and row['repaired'] is False and row['dropped_edits'] == 0


def test_flag_on_garbage_emission_reports_not_ok(tmp_path, monkeypatch):
    import autocompiler.flags as flags_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: key == 'decode')
    (tmp_path / 'output').mkdir(parents=True)
    (tmp_path / 'output' / 'tdec-bad.py').write_text('def f():\n    pass\n', encoding='utf-8')
    _decode_check_safe({'task_id': 'tdec-bad'}, state_dir=tmp_path)
    rows = [r for r in _rows(tmp_path) if r.get('event') == 'decode_check']
    assert len(rows) == 1 and rows[0]['ok'] is False


def test_missing_emission_no_row(tmp_path, monkeypatch):
    import autocompiler.flags as flags_mod
    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: True)
    _decode_check_safe({'task_id': 'tdec-none'}, state_dir=tmp_path)
    assert [r for r in _rows(tmp_path) if r.get('event') == 'decode_check'] == []


def test_bridge_is_total(tmp_path, monkeypatch):
    # Edge cases: raising flag reader / decoder / garbage payloads never escape.
    import autocompiler.flags as flags_mod

    def _boom(*a, **k):
        raise RuntimeError('boom')
    monkeypatch.setattr(flags_mod, 'ac_enabled', _boom)
    _decode_check_safe({'task_id': 'x'}, state_dir=tmp_path)

    monkeypatch.setattr(flags_mod, 'ac_enabled', lambda key, *a, **k: True)
    import autocompiler.decode as decode_mod
    monkeypatch.setattr(decode_mod, 'decode_submission', _boom)
    (tmp_path / 'output').mkdir(parents=True, exist_ok=True)
    (tmp_path / 'output' / 'x.py').write_text('{}', encoding='utf-8')
    _decode_check_safe({'task_id': 'x'}, state_dir=tmp_path)

    for garbage in ({}, {'task_id': 42}, {'task_id': ''}, None):
        _decode_check_safe(garbage, state_dir=tmp_path)
