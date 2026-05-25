"""W77b.5 path-1 integration battery for the narrow-fuzz bypass-branch wire-in.

§16 was resolved as Path 1 (W96, brief §17): narrow-fuzz remains an additional
pre-accept gate inside the bypass branch (`harness/orchestrator.py:1008-1014`),
no taxonomy edit. This test pins the three couplings that make the path-1
contract hold end-to-end:

  (i)   `validation` is in `BYPASS_FUZZER_TYPES` and out of `SKIP_SMOKE_GATE_TYPES`
        (so validation tasks reach the bypass smoke + embedded + narrow gates).
  (ii)  The narrow-fuzz registry has `validation -> validation.fuzz` (the
        per-type entry §G3 says "flips the type to narrow-fuzzed").
  (iii) The §13 binding reproducer (`validate_nonempty(xs: list)`) drives the
        same `run_narrow_fuzz('validation', '_narrow_fuzz_candidate', ...)`
        call signature the orchestrator uses, surfaces a non-None error, and
        the orchestrator source carries the full 7-line rejection cascade in
        the canonical order: call -> if-check -> logger.error -> set_phase
        rejected -> _mark_processed -> round-complete log -> continue.

Pattern follows `test_orchestrator_return_type_wiring_adversarial.py` (W76b):
unit-level wire-in seam tests, no run_pipeline spin-up. End-to-end orchestration
coverage continues to live in `test_P5_orchestrator_stateful.py`.
"""
from __future__ import annotations

import pathlib
import re
import sys


_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0, str(_REPO_ROOT))

from harness.narrow_fuzz import run_narrow_fuzz  # noqa: E402
from harness.narrow_fuzz import validation  # noqa: E402
from harness.narrow_fuzz._registry import REGISTRY  # noqa: E402
from harness.planner.taxonomies import (  # noqa: E402
    BYPASS_FUZZER_TYPES,
    SKIP_SMOKE_GATE_TYPES,
)


_VALIDATE_NONEMPTY_CANARY = """
def validate_nonempty(xs: list) -> bool:
    \"\"\"Return True iff list is non-empty.\"\"\"
    return xs[0] is not None
"""


# ---------------------------------------------------------------------------
# (i) Taxonomy binding: validation reaches the bypass narrow-fuzz gate.
# ---------------------------------------------------------------------------

def test_validation_in_bypass_fuzzer_types() -> None:
    """Path-1 contract: removing `validation` from `BYPASS_FUZZER_TYPES`
    routes validation tasks past the narrow-fuzz wire-in entirely (full-fuzz
    path at line 1024+ never reaches `run_narrow_fuzz`)."""
    assert 'validation' in BYPASS_FUZZER_TYPES


def test_validation_not_in_skip_smoke_gate_types() -> None:
    """Path-1 contract: validation must NOT be in `SKIP_SMOKE_GATE_TYPES`
    or the entire smoke+embedded+narrow cascade is skipped (line 1015 else
    branch in the bypass)."""
    assert 'validation' not in SKIP_SMOKE_GATE_TYPES


# ---------------------------------------------------------------------------
# (ii) Registry binding: validation -> validation.fuzz per §G3.
# ---------------------------------------------------------------------------

def test_registry_has_validation_entry() -> None:
    """§G3: 'Adding a module flips the type to narrow-fuzzed without taxonomy
    edit.' For that contract to hold, the registry must contain a callable
    keyed by the meta_task_type string the orchestrator passes."""
    assert 'validation' in REGISTRY
    assert callable(REGISTRY['validation'])


def test_registry_validation_resolves_to_validation_fuzz() -> None:
    """The registered callable must be `validation.fuzz` itself (not a stub
    or a wrapper that swallows errors)."""
    assert REGISTRY['validation'] is validation.fuzz


# ---------------------------------------------------------------------------
# (iii) §12 #5 integration: orchestrator's exact call signature surfaces the
# §13 reproducer crash through the public `run_narrow_fuzz` entry point.
# ---------------------------------------------------------------------------

def test_run_narrow_fuzz_surfaces_validate_nonempty_crash() -> None:
    """Drives the exact orchestrator call site:
        run_narrow_fuzz(mtt, '_narrow_fuzz_candidate', claude_code)
    with mtt='validation' and a canary embedding `validate_nonempty(xs: list)`.
    The path-1 contract requires a non-None error so the bypass-branch reject
    cascade fires. The error string must name the validator and the failing
    input so the rejection log carries actionable detail."""
    err = run_narrow_fuzz('validation', '_narrow_fuzz_candidate', _VALIDATE_NONEMPTY_CANARY)
    assert err is not None, 'narrow-fuzz failed to surface IndexError on xs=[]'
    assert 'validate_nonempty' in err
    assert 'IndexError' in err
    assert '[]' in err


def test_run_narrow_fuzz_clean_validator_returns_none() -> None:
    """Negative control: a clean validator must NOT trip the narrow-fuzz gate,
    or every validation task would be falsely rejected."""
    clean_src = """
def is_positive(n: int) -> bool:
    return n > 0
"""
    assert run_narrow_fuzz('validation', '_narrow_fuzz_candidate', clean_src) is None


# ---------------------------------------------------------------------------
# (iv) Rejection cascade structure: full 7-line block in canonical order.
# ---------------------------------------------------------------------------

def test_orchestrator_narrow_fuzz_rejection_cascade_intact() -> None:
    """The W77b.3 wire-up test pins the call line and the round-complete log
    string. This test pins the FULL 7-line rejection cascade in canonical
    order, so a partial deletion (e.g. dropping `_mark_processed` or
    `set_phase('rejected')`) trips the gate before it can ship."""
    from harness import orchestrator

    src = pathlib.Path(orchestrator.__file__).read_text(encoding='utf-8')

    cascade_pattern = re.compile(
        r"narrow_err = run_narrow_fuzz\(mtt, '_narrow_fuzz_candidate', claude_code\)\s*\n"
        r"\s+if narrow_err is not None:\s*\n"
        r"\s+logger\.error\('Narrow-fuzz rejected bypass-eligible[^']*',[^)]*\)\s*\n"
        r"\s+set_phase\(state_dir, phase='rejected'\)\s*\n"
        r"(?:\s+_emit_lifecycle\(state_dir, event='phase_transition'[^\n]*\)\s*\n)?"
        r"\s+_mark_processed\(state_dir, task_id\)\s*\n"
        r"(?:\s+_emit_lifecycle\(state_dir, event='task_terminal'[^\n]*\)\s*\n)?"
        r"\s+logger\.info\('=== Round %d complete \(rejected via narrow-fuzz\)[^']*',[^)]*\)\s*\n"
        r"\s+continue\b"
    )
    assert cascade_pattern.search(src) is not None, (
        'narrow-fuzz rejection cascade missing or out of order in '
        'harness/orchestrator.py — path-1 contract broken'
    )


def test_orchestrator_narrow_fuzz_runs_after_smoke_and_embedded() -> None:
    """§3.3 ordering: narrow-fuzz fires AFTER smoke + embedded gates inside
    the bypass branch. If a refactor reorders the gates (e.g. moves narrow
    before smoke), the test fails — narrow-fuzz is intentionally the last,
    most expensive gate so the cheaper checks short-circuit first."""
    from harness import orchestrator

    src = pathlib.Path(orchestrator.__file__).read_text(encoding='utf-8')

    smoke_call = "smoke_err = smoke_import('_smoke_candidate', claude_code)"
    embedded_call = "embedded_err = run_embedded_tests('_embedded_candidate', claude_code)"
    narrow_call = "narrow_err = run_narrow_fuzz(mtt, '_narrow_fuzz_candidate', claude_code)"

    assert smoke_call in src
    assert embedded_call in src
    assert narrow_call in src
    assert src.index(smoke_call) < src.index(embedded_call) < src.index(narrow_call), (
        'bypass-branch gate ordering changed: expected smoke -> embedded -> narrow'
    )
