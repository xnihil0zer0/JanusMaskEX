"""Behavioral oracle for SITE2 MD-ROUTING mirror (run_pipeline loop).

Asserts route/bypass parity between `_should_bypass_or_route_task` and the
dispatch-path decision logic across a representative matrix of tasks.
"""

from __future__ import annotations

import sys
from pathlib import Path
import pytest

# Ensure repo root is in path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent))

from harness.planner.taxonomies import BYPASS_FUZZER_TYPES, META_TASK_POLICY

def test_should_bypass_or_route_task_exists():
    """Verify that _should_bypass_or_route_task is exported by harness.orchestrator."""
    try:
        from harness.orchestrator import _should_bypass_or_route_task
    except (ImportError, AttributeError) as e:
        pytest.fail(f"Symbol _should_bypass_or_route_task is missing or cannot be imported: {e}")

def test_should_bypass_or_route_task_parity_matrix():
    """Verify routing decisions match the dispatch path for a representative task matrix."""
    try:
        from harness.orchestrator import _should_bypass_or_route_task
    except (ImportError, AttributeError) as e:
        pytest.fail(f"Symbol _should_bypass_or_route_task is missing or cannot be imported: {e}")

    # Matrix of (task_dict, expected_outcome)
    matrix = [
        # (1) harness_self_fix -> bypass
        ({"meta_task_type": "harness_self_fix"}, "bypass"),
        # (2) state_machine -> route
        ({"meta_task_type": "state_machine"}, "route"),
        # (3) cli_tooling -> fuzz (no-bypass/regular)
        ({"meta_task_type": "cli_tooling"}, "fuzz"),
        # (4) test_authoring -> bypass (because skip_interface_fuzz is True)
        ({"meta_task_type": "test_authoring"}, "bypass"),
        # (5) Missing meta_task_type -> fuzz
        ({}, "fuzz"),
        # (6) None meta_task_type -> fuzz
        ({"meta_task_type": None}, "fuzz"),
        # (7) Fallback to constraints
        ({"constraints": {"meta_task_type": "harness_self_fix"}}, "bypass"),
        # (8) Priority of top-level meta_task_type over constraints
        ({"meta_task_type": "harness_self_fix", "constraints": {"meta_task_type": "state_machine"}}, "bypass"),
        ({"meta_task_type": "state_machine", "constraints": {"meta_task_type": "harness_self_fix"}}, "route"),
        # (9) Unknown meta_task_type -> fuzz
        ({"meta_task_type": "some_completely_unknown_type"}, "fuzz"),
    ]

    config = {}

    for task, expected in matrix:
        actual = _should_bypass_or_route_task(task, config)
        assert actual == expected, f"For task {task}, expected {expected}, got {actual}"

def test_dispatch_path_logic_parity():
    """Directly assert helper logic matches the live dispatch-path rule on the same task inputs."""
    try:
        from harness.orchestrator import _should_bypass_or_route_task
    except (ImportError, AttributeError) as e:
        pytest.fail(f"Symbol _should_bypass_or_route_task is missing or cannot be imported: {e}")

    # Build a larger search space from all known keys in META_TASK_POLICY
    config = {}
    for mtt in list(META_TASK_POLICY.keys()) + [None, "invalid_type"]:
        task = {"meta_task_type": mtt}
        
        # Calculate dispatch expected path
        _skip_ifz = (mtt == 'test_authoring') and META_TASK_POLICY.get('test_authoring', {}).get('skip_interface_fuzz')
        if META_TASK_POLICY.get(mtt, {}).get('stateful_fuzz'):
            expected = 'route'
        elif mtt in BYPASS_FUZZER_TYPES or _skip_ifz:
            expected = 'bypass'
        else:
            expected = 'fuzz'

        actual = _should_bypass_or_route_task(task, config)
        assert actual == expected, f"Helper decision {actual!r} diverged from dispatch expected {expected!r} for meta_task_type {mtt!r}"
