"""Authored pytest oracle: enabled-but-undersized agy-pool invariant warning.

Verification target: ``harness.autowork_daemon._agy_pool_assign``.

``_agy_pool_assign`` reserves a private agy-pool slot for a worker.  When the
pool is *enabled* but its ``size`` is smaller than ``autowork.parallel_cap``,
concurrent workers beyond ``size`` would silently fall back to the shared HOME
(the pool-sizing footgun described by ``harness.agy_pool.PoolInvariantError``).
The runtime must surface this as a NON-FATAL warning -- an
``agy_pool_invariant_violated`` row appended to ``<state_dir>/impl_progress.jsonl``
(via ``_emit_telemetry``) -- rather than raising.

These tests exercise the REAL observable behaviour:

* ``size < parallel_cap``  -> exactly one ``agy_pool_invariant_violated`` row
  is written for the assigned task (positive control).
* ``size >= parallel_cap`` -> no such row is written, while the assignment
  itself still succeeds (negative control proving the enabled-pool code path
  actually ran).

They are non-vacuous: a mutant that drops the warning fails the undersized
tests, and a mutant that always warns fails the sufficient tests.
"""
from __future__ import annotations
import json
import pytest
import harness.autowork_daemon as awd
VIOLATION_EVENT = 'agy_pool_invariant_violated'
PARALLEL_CAP = 5
TASK_ID = 'task-x'

def _make_config(size: int, parallel_cap: int=PARALLEL_CAP) -> dict:
    """Mock config dict in the exact shape ``_agy_pool_assign`` consumes."""
    return {'workers': {'agy_pool': {'enabled': True, 'size': size}}, 'autowork': {'parallel_cap': parallel_cap}}

def _patch_load_config(monkeypatch: 'pytest.MonkeyPatch', size: int) -> None:
    """Override ``harness.orchestrator.load_config`` (the symbol the function
    re-imports at call time) to return our mock configuration."""
    cfg = _make_config(size)
    monkeypatch.setattr('harness.orchestrator.load_config', lambda *a, **k: cfg, raising=True)

def _ledger_rows(state_dir) -> list[dict]:
    """Wait-free read of the JSONL ledger; validates one JSON dict per line.

    Returns [] when the ledger does not exist (no telemetry written at all).
    """
    ledger = state_dir / 'impl_progress.jsonl'
    if not ledger.exists():
        return []
    rows: list[dict] = []
    for line in ledger.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if not line:
            continue
        row = json.loads(line)
        assert isinstance(row, dict)
        rows.append(row)
    return rows

def _violation_rows(state_dir) -> list[dict]:
    return [r for r in _ledger_rows(state_dir) if r.get('event') == VIOLATION_EVENT]

def test_agy_pool_invariant_runtime_warn_undersized(monkeypatch, tmp_path):
    """size=1 < parallel_cap=5 -> an invariant-violated row is appended."""
    _patch_load_config(monkeypatch, size=1)
    slot = awd._agy_pool_assign(tmp_path, TASK_ID)
    assert slot is not None
    violations = _violation_rows(tmp_path)
    assert violations, 'expected an %r row when an enabled pool size < parallel_cap' % VIOLATION_EVENT
    assert any((r.get('task_id') == TASK_ID for r in violations))

def test_agy_pool_invariant_runtime_warn_sufficient(monkeypatch, tmp_path):
    """size=8 >= parallel_cap=5 -> NO invariant-violated row is appended."""
    _patch_load_config(monkeypatch, size=8)
    slot = awd._agy_pool_assign(tmp_path, TASK_ID)
    assert slot is not None
    assert _violation_rows(tmp_path) == []

def test_agy_pool_invariant_runtime_warn_undersized_regression(monkeypatch, tmp_path):
    """Regression: the warning row keeps the canonical telemetry shape."""
    _patch_load_config(monkeypatch, size=1)
    awd._agy_pool_assign(tmp_path, TASK_ID)
    violations = _violation_rows(tmp_path)
    assert len(violations) >= 1
    row = violations[0]
    assert row.get('phase') == 'autowork'
    assert row.get('task_id') == TASK_ID
    assert row.get('event') == VIOLATION_EVENT
    assert 'ts' in row

def test_agy_pool_invariant_runtime_warn_sufficient_regression(monkeypatch, tmp_path):
    """Regression: boundary size == parallel_cap is sufficient (no warning)."""
    _patch_load_config(monkeypatch, size=PARALLEL_CAP)
    slot = awd._agy_pool_assign(tmp_path, TASK_ID)
    assert slot is not None
    assert _violation_rows(tmp_path) == []