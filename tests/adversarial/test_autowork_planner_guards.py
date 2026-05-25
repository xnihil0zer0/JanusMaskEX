"""Adversarial regression bar for R-PROMOTE-4 and R-PROMOTE-5.

R-PROMOTE-4: `_check_hallucination()` returns `(False, '')` for empty plans,
masking the timed-out-planner case and causing false-positive `plan_kickoff`
ledger events that drive the daemon idle with no work to extract.

R-PROMOTE-5: `_run_planner_subprocess()` default `timeout_sec=120.0` is too
tight; legitimate planners need 300s+ for medium briefs. Combines with
R-PROMOTE-4 to emit `plan_kickoff` for timed-out (empty) planner output.

Fix shape (session #20 dispatch):
- R-PROMOTE-4: change the empty-tasks early-return in `_check_hallucination`
  from `(False, '')` to `(True, 'empty_plan')`.
- R-PROMOTE-5: bump `_run_planner_subprocess` default `timeout_sec` from
  `120.0` to `300.0`.

Each fix lands in its own dogfood commit. The three xfail markers in this
file get dropped in a follow-up META commit once both fixes land.
"""
from __future__ import annotations

import pytest

from harness.autowork_daemon import _check_hallucination, _run_planner_subprocess


def test_empty_plan_dict_is_hallucination() -> None:
    """An empty plan_dict (planner timeout, output_plan never written) must
    be flagged as hallucinated, not pass through as `(False, '')`."""
    is_halluc, reason = _check_hallucination({}, wall_seconds=120.0)
    assert is_halluc is True, f"expected hallucinated, got ({is_halluc}, {reason!r})"
    assert reason == "empty_plan", f"expected reason='empty_plan', got {reason!r}"


def test_plan_with_empty_tasks_list_is_hallucination() -> None:
    """A plan_dict shaped `{'tasks': []}` (parsed but tasks-empty) must
    also be flagged as hallucinated."""
    is_halluc, reason = _check_hallucination({"tasks": []}, wall_seconds=120.0)
    assert is_halluc is True, f"expected hallucinated, got ({is_halluc}, {reason!r})"
    assert reason == "empty_plan", f"expected reason='empty_plan', got {reason!r}"


def test_run_planner_subprocess_default_timeout_is_300s() -> None:
    """`_run_planner_subprocess` must default `timeout_sec` to 300.0 (was
    120.0). Inspect `__defaults__` so the assertion is robust against
    parameter-name renames as long as the value is present."""
    defaults = _run_planner_subprocess.__defaults__
    assert defaults is not None, "_run_planner_subprocess has no defaults"
    assert 120.0 not in defaults, f"120.0 still present in defaults: {defaults!r}"
    assert 300.0 in defaults, f"300.0 not in defaults: {defaults!r}"
