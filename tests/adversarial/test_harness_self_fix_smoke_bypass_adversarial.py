"""W85 adversarial — harness_self_fix bypasses smoke + embedded test gates.

The orchestrator's bypass branch (orchestrator.py:973+) historically ran
``smoke_import`` and ``run_embedded_tests`` for every BYPASS_FUZZER_TYPES
task. Both subprocess gates use ``python -S`` (skip site-packages) to
catch hidden deps in untrusted synthesis candidates. That gating is
INCORRECT for ``harness_self_fix`` tasks: those legitimately fix
harness internals which import site-packages (hypothesis, pytest, etc.)
— under -S, the gate falsely rejects every harness-self-fix candidate,
blocking the M1 SELFFIX-001 round-trip (W83 dispatch confirmed this:
'ModuleNotFoundError: No module named hypothesis' on the smoke step).

W85 adds a ``skip_smoke_gates`` flag to META_TASK_POLICY (set True for
``harness_self_fix``) and an ``SKIP_SMOKE_GATE_TYPES`` derived frozenset.
The orchestrator wraps the smoke + embedded gates in
``if mtt not in SKIP_SMOKE_GATE_TYPES``.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

from harness.planner.taxonomies import (
    BYPASS_FUZZER_TYPES,
    META_TASK_POLICY,
    SKIP_SMOKE_GATE_TYPES,
)

ORCHESTRATOR_PATH = Path(__file__).resolve().parents[2] / "harness" / "orchestrator.py"


def test_harness_self_fix_in_skip_smoke_gate_types():
    assert "harness_self_fix" in SKIP_SMOKE_GATE_TYPES


def test_harness_self_fix_in_bypass_set():
    """Skip-gate types must also be bypass-eligible — the gate only runs
    inside the bypass branch."""
    assert "harness_self_fix" in BYPASS_FUZZER_TYPES


def test_other_bypass_types_still_smoke_gated():
    """Skip-gate types are explicitly opted in via skip_smoke_gates=True
    in META_TASK_POLICY. The set expanded post-G14 (1eb09d1) to cover
    data-only / test_* / non-py mtts whose smoke gate cannot run under
    -S without sys.path injection (G16 deferred). Regression guard:
    pins the explicit allow-list so a future taxonomy edit must update
    this test to lift the gate for a new mtt."""
    expected_skip = {
        "harness_self_fix",
        "config_schema",
        "docs_writing",
        "harness_plumbing",
        "hooks_integration",
        "mcp_server_change",
        "test_acceptance",
        "test_e2e",
        "test_integration",
        "test_unit",
    }
    assert SKIP_SMOKE_GATE_TYPES == expected_skip


def test_skip_smoke_gate_strict_subset_of_bypass():
    """The gate is meaningful only inside the bypass branch — non-bypass
    types go through diff_fuzz, not smoke."""
    assert SKIP_SMOKE_GATE_TYPES.issubset(BYPASS_FUZZER_TYPES)


def test_orchestrator_imports_skip_smoke_gate_types():
    src = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    assert "SKIP_SMOKE_GATE_TYPES" in src, (
        "orchestrator.py must import SKIP_SMOKE_GATE_TYPES from taxonomies"
    )
    assert "from harness.planner.taxonomies import" in src


def test_orchestrator_gates_smoke_behind_skip_check():
    """Static AST/string check: smoke_import + run_embedded_tests calls
    must be reachable only when mtt is NOT in SKIP_SMOKE_GATE_TYPES.
    """
    src = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    smoke_idx = src.index("smoke_err = smoke_import('_smoke_candidate'")
    embedded_idx = src.index("embedded_err = run_embedded_tests('_embedded_candidate'")
    skip_check_idx = src.index("mtt not in SKIP_SMOKE_GATE_TYPES")
    assert skip_check_idx < smoke_idx, (
        "skip-gate check must precede smoke_import call"
    )
    assert skip_check_idx < embedded_idx, (
        "skip-gate check must precede run_embedded_tests call"
    )


def test_skip_smoke_flag_default_false_for_unflagged_types():
    """Backward compat: the new flag is optional; mtts NOT in
    SKIP_SMOKE_GATE_TYPES must default to skip_smoke_gates=False (smoke
    gate stays on for them). The opt-in set is pinned by
    test_other_bypass_types_still_smoke_gated above.
    """
    for mtt, policy in META_TASK_POLICY.items():
        if mtt in SKIP_SMOKE_GATE_TYPES:
            continue
        assert policy.get("skip_smoke_gates", False) is False


def test_skip_smoke_gate_only_skips_when_inside_bypass_branch():
    """Static check: the SKIP_SMOKE_GATE_TYPES check sits INSIDE the
    `if mtt in BYPASS_FUZZER_TYPES:` branch, not at the top of run_pipeline.
    Non-bypass types must continue to hit diff_fuzz regardless of the
    skip-gate flag — the flag only governs smoke-vs-diff-fuzz selection
    within the bypass branch.
    """
    tree = ast.parse(ORCHESTRATOR_PATH.read_text(encoding="utf-8"))
    found_pattern = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        # Look for: if mtt in BYPASS_FUZZER_TYPES: ... if mtt not in SKIP_SMOKE_GATE_TYPES:
        test_src = ast.unparse(node.test)
        if "BYPASS_FUZZER_TYPES" in test_src and "in" in test_src and "not" not in test_src:
            inner_src = ast.unparse(node)
            if "SKIP_SMOKE_GATE_TYPES" in inner_src and "smoke_import" in inner_src:
                found_pattern = True
                break
    assert found_pattern, (
        "Expected: `if mtt in BYPASS_FUZZER_TYPES:` block containing a "
        "`SKIP_SMOKE_GATE_TYPES` gate around smoke_import"
    )
