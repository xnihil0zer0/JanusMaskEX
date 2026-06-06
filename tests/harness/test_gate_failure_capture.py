"""RED oracle for the gate-failure error-capture fix (NGv2 Epic-4 TASK 1).

Today ``harness/orchestrator_worker.py::main()`` computes ``smoke_err`` /
``embedded_err`` / ``narrow_err`` (the full subprocess import traceback returned
by ``smoke_import`` / ``run_embedded_tests`` / ``run_narrow_fuzz``) and then DROPS
it -- only the bare ``smoke_failed`` / ``embedded_tests_failed`` /
``narrow_fuzz_failed`` outcome reaches the ledger, so a flaky external import can
never be root-caused and burns re-dispatch tokens.

This oracle pins:
  1. a NEW top-level helper ``_emit_gate_failure(state_dir, task_id, gate, err)``
     that appends a ``gate_failed`` row (with the truncated error string) to
     ``state/impl_progress.jsonl`` -- directly unit-testable; and
  2. that ``main()`` is wired to call it at all three gate-failure sites with the
     captured error variable, while remaining structurally intact (no truncation).
"""
import ast
import json
from pathlib import Path

import harness.orchestrator_worker as ow


def _read_rows(state_dir):
    p = Path(state_dir) / 'impl_progress.jsonl'
    if not p.exists():
        return []
    return [json.loads(line) for line in p.read_text(encoding='utf-8').splitlines() if line.strip()]


# ---- 1. the helper writes a structured gate_failed ledger row ----

def test_emit_gate_failure_writes_ledger_row(tmp_path):
    err = 'sandbox import failed: ModuleNotFoundError: No module named ngv2.contracts'
    ow._emit_gate_failure(tmp_path, 'mytask', 'smoke', err)
    rows = [r for r in _read_rows(tmp_path) if r.get('event') == 'gate_failed']
    assert len(rows) == 1
    row = rows[0]
    assert row['task_id'] == 'mytask'
    assert row['gate'] == 'smoke'
    assert 'ModuleNotFoundError' in row['detail']
    assert 'ngv2.contracts' in row['detail']
    assert 'ts' in row


def test_emit_gate_failure_truncates_long_detail(tmp_path):
    ow._emit_gate_failure(tmp_path, 't2', 'embedded', 'x' * 5000)
    rows = [r for r in _read_rows(tmp_path) if r.get('event') == 'gate_failed']
    assert len(rows) == 1
    assert len(rows[0]['detail']) <= 2000


def test_emit_gate_failure_coerces_non_string_and_never_raises(tmp_path):
    # err may be an exception object or None; the helper must coerce, not raise.
    ow._emit_gate_failure(tmp_path, 't3', 'narrow', RuntimeError('boom-detail'))
    ow._emit_gate_failure(tmp_path, 't3', 'narrow', None)
    rows = [r for r in _read_rows(tmp_path) if r.get('event') == 'gate_failed']
    assert len(rows) == 2
    assert any('boom-detail' in r['detail'] for r in rows)


# ---- 2. main() is wired at all three gate-failure sites ----

def test_main_wires_emit_gate_failure_for_all_three_gates():
    src = Path(ow.__file__).read_text(encoding='utf-8')
    # Each gate-failure site records its captured error via the helper. The exact
    # call form is dictated by the spec so this match is deterministic.
    assert "_emit_gate_failure(state_dir, task_id, 'smoke', smoke_err)" in src
    assert "_emit_gate_failure(state_dir, task_id, 'embedded', embedded_err)" in src
    assert "_emit_gate_failure(state_dir, task_id, 'narrow', narrow_err)" in src


# ---- 3. the edit must not truncate main() or drop existing terminal logic ----

def test_main_structurally_intact():
    src = Path(ow.__file__).read_text(encoding='utf-8')
    tree = ast.parse(src)
    mains = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == 'main']
    assert len(mains) == 1
    span = mains[0].end_lineno - mains[0].lineno + 1
    assert span >= 560, f'main() shrank to {span} lines -- suspected truncation'
    for marker in (
        'smoke_failed', 'embedded_tests_failed', 'narrow_fuzz_failed',
        'auto_commit_failed', 'stateful_fuzz_divergence', 'fuzz_error_r1',
        'BYPASS_FUZZER_TYPES', 'SKIP_SMOKE_GATE_TYPES',
    ):
        assert marker in src, f'terminal marker {marker!r} disappeared from orchestrator_worker'
