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
        # hierarchical-planner Brief 4: epic_planning emits child BRIEFS, not
        # code, so there is nothing to smoke-test -> skip_smoke_gates=True.
        "epic_planning",
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


def _is_bypass_branch_test(test_node: ast.expr) -> bool:
    """True iff the source of an ``if`` test expresses the fuzzer-BYPASS
    condition, in EITHER the legacy inline form or the SITE2 helper form.

    Legacy inline form (pre-REV29-SITE2)::

        if mtt in BYPASS_FUZZER_TYPES or _skip_ifz:

    SITE2 helper-indirected form (commit e8d8825)::

        if _should_bypass_or_route_task(task, config) == 'bypass':

    The decision was centralized into ``_should_bypass_or_route_task`` whose
    'bypass' return encodes the SAME condition; the separate test
    ``test_helper_encodes_bypass_condition`` below pins that the helper still
    keys on ``BYPASS_FUZZER_TYPES`` so this indirection cannot silently drop
    the check. We must NOT accept a bare top-of-loop ``if mtt not in
    SKIP_SMOKE_GATE_TYPES`` (the dangerous hoist), so the legacy branch is
    only recognized when it is the *positive* bypass membership test, and the
    helper branch only when it compares the helper call against ``'bypass'``.
    """
    test_src = ast.unparse(test_node)
    # Legacy positive bypass-membership test: `mtt in BYPASS_FUZZER_TYPES ...`.
    # Reject the *negated* SKIP_SMOKE check (`mtt not in SKIP_SMOKE_GATE_TYPES`)
    # so a hoisted smoke-skip `if` can never be mistaken for the bypass branch.
    if (
        "BYPASS_FUZZER_TYPES" in test_src
        and "in" in test_src
        and "SKIP_SMOKE_GATE_TYPES" not in test_src
        and "not in BYPASS_FUZZER_TYPES" not in test_src
    ):
        return True
    # SITE2 helper-indirected form: `_should_bypass_or_route_task(...) == 'bypass'`.
    if "_should_bypass_or_route_task" in test_src and "bypass" in test_src:
        return True
    return False


def test_skip_smoke_gate_only_skips_when_inside_bypass_branch():
    """Static check: the SKIP_SMOKE_GATE_TYPES gate sits INSIDE the
    fuzzer-BYPASS branch (the `if mtt in BYPASS_FUZZER_TYPES:` legacy form OR
    the `if _should_bypass_or_route_task(...) == 'bypass':` SITE2 form), not
    at the top of run_pipeline. Non-bypass types must continue to hit
    diff_fuzz regardless of the skip-gate flag — the flag only governs
    smoke-vs-diff-fuzz selection WITHIN the bypass branch.

    Negative case still caught: if a refactor HOISTS the smoke-skip out of
    the bypass branch (top-level `if mtt not in SKIP_SMOKE_GATE_TYPES:` whose
    body holds smoke_import, with no enclosing bypass test), no `If` node's
    test satisfies ``_is_bypass_branch_test`` (it explicitly rejects the
    negated SKIP_SMOKE_GATE_TYPES form), so ``found_pattern`` stays False and
    the test FAILS.
    """
    tree = ast.parse(ORCHESTRATOR_PATH.read_text(encoding="utf-8"))
    found_pattern = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.If):
            continue
        if not _is_bypass_branch_test(node.test):
            continue
        # The SKIP_SMOKE_GATE_TYPES gate around smoke_import must be NESTED
        # inside this bypass branch's body (not merely co-located in the file).
        for child in ast.walk(ast.Module(body=node.body, type_ignores=[])):
            if not isinstance(child, ast.If):
                continue
            child_src = ast.unparse(child)
            if "SKIP_SMOKE_GATE_TYPES" in child_src and "smoke_import" in child_src:
                found_pattern = True
                break
        if found_pattern:
            break
    assert found_pattern, (
        "Expected a fuzzer-BYPASS `if` (mtt in BYPASS_FUZZER_TYPES, or "
        "_should_bypass_or_route_task(...) == 'bypass') whose body NESTS a "
        "`SKIP_SMOKE_GATE_TYPES` gate around smoke_import. If this fails, the "
        "smoke-skip may have been HOISTED out of the bypass branch — letting "
        "non-bypass task types skip the smoke gate."
    )


def test_helper_encodes_bypass_condition():
    """STRENGTHEN: the SITE2 indirection (`_should_bypass_or_route_task`) must
    faithfully encode the bypass condition, so it cannot silently drop the
    ``BYPASS_FUZZER_TYPES`` membership check. We assert the helper's source
    keys on ``BYPASS_FUZZER_TYPES`` and returns ``'bypass'`` for that case,
    AND verify behavior: a harness_self_fix-style task -> 'bypass', a plain
    synthesis task -> not 'bypass'.

    If the helper is absent (a future revert to the pure-inline form), this
    test is a no-op for the source check but the behavioral half is skipped —
    the inline form is then covered directly by
    ``test_skip_smoke_gate_only_skips_when_inside_bypass_branch``.
    """
    src = ORCHESTRATOR_PATH.read_text(encoding="utf-8")
    if "_should_bypass_or_route_task" not in src:
        pytest.skip("helper not present; inline-form covered by branch test")

    tree = ast.parse(src)
    helper = next(
        (
            n
            for n in ast.walk(tree)
            if isinstance(n, ast.FunctionDef)
            and n.name == "_should_bypass_or_route_task"
        ),
        None,
    )
    assert helper is not None, "_should_bypass_or_route_task must be a top-level def"
    helper_src = ast.unparse(helper)
    assert "BYPASS_FUZZER_TYPES" in helper_src, (
        "_should_bypass_or_route_task must key its 'bypass' decision on "
        "BYPASS_FUZZER_TYPES — the indirection must not drop the check"
    )
    assert "'bypass'" in helper_src or '"bypass"' in helper_src, (
        "helper must return the 'bypass' sentinel"
    )

    # Behavioral check: import the live helper and confirm classification.
    from harness.orchestrator import _should_bypass_or_route_task

    bypass_mtt = next(iter(BYPASS_FUZZER_TYPES))
    assert (
        _should_bypass_or_route_task({"meta_task_type": bypass_mtt}, {}) == "bypass"
    ), f"helper must classify bypass-eligible mtt {bypass_mtt!r} as 'bypass'"

    non_bypass_mtt = "synthesis"
    assert non_bypass_mtt not in BYPASS_FUZZER_TYPES, (
        "test premise: 'synthesis' must not be a bypass type"
    )
    assert (
        _should_bypass_or_route_task({"meta_task_type": non_bypass_mtt}, {}) != "bypass"
    ), "helper must NOT classify a non-bypass synthesis task as 'bypass'"
