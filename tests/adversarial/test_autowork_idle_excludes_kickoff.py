"""Adversarial regression bar for R-PROMOTE-6.

Bug: after `_auto_promote` fires `plan_kickoff` in iteration N, the daemon's
`run_daemon` `is_idle` computation returns True (because `free_slots==cap`
and `would_launch==[]`), so `sleep_target = heartbeat = 1800s`. This leaves
the freshly-written plan's tasks unstaged for up to 30 minutes — blocking
self-build criterion 6's autonomous Path B closure.

Fix (session #20):
- `_iteration` captures `_auto_promote`'s summary dict and bubbles
  `extracts` + `plan_kickoffs` into its return dict.
- `run_daemon`'s `is_idle` excludes iterations where `plan_kickoffs > 0`,
  so the next iteration runs within `poll` (5s) and the extract loop picks
  up the freshly-written plan's tasks.

The three xfail markers in this file get dropped in a follow-up META
commit once the fix lands.
"""
from __future__ import annotations

import inspect
import pathlib
import re

import pytest

from harness.autowork_daemon import _iteration, run_daemon


@pytest.fixture
def empty_state(tmp_path: pathlib.Path) -> pathlib.Path:
    """A minimal state dir with no tasks queued — _iteration runs a no-op
    pass and returns its result dict."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    (state_dir / "tasks").mkdir()
    (state_dir / "tasks" / "processed").mkdir()
    (state_dir / "control").mkdir()
    (state_dir / "control" / "autowork").mkdir()
    return state_dir


def test_iteration_returns_plan_kickoffs_key(tmp_path: pathlib.Path, empty_state: pathlib.Path) -> None:
    """_iteration must bubble _auto_promote's plan_kickoffs count into its
    return dict so run_daemon can use it for the is_idle computation."""
    result = _iteration(tmp_path, empty_state, cap=4, dry_run=True)
    assert isinstance(result, dict), f"expected dict, got {type(result).__name__}"
    assert "plan_kickoffs" in result, f"missing key 'plan_kickoffs'; got keys: {sorted(result.keys())}"
    assert isinstance(result["plan_kickoffs"], int), (
        f"plan_kickoffs must be int, got {type(result['plan_kickoffs']).__name__}"
    )
    assert result["plan_kickoffs"] == 0, f"empty-state plan_kickoffs must be 0, got {result['plan_kickoffs']}"


def test_iteration_returns_extracts_key(tmp_path: pathlib.Path, empty_state: pathlib.Path) -> None:
    """_iteration must also bubble _auto_promote's extracts count into its
    return dict for future ops/UI use."""
    result = _iteration(tmp_path, empty_state, cap=4, dry_run=True)
    assert isinstance(result, dict)
    assert "extracts" in result, f"missing key 'extracts'; got keys: {sorted(result.keys())}"
    assert isinstance(result["extracts"], int)
    assert result["extracts"] == 0, f"empty-state extracts must be 0, got {result['extracts']}"


def test_run_daemon_is_idle_references_plan_kickoffs() -> None:
    """The is_idle assignment in run_daemon must reference plan_kickoffs so
    iterations with plan_kickoff > 0 are not classified as idle and the
    next sleep_target is poll (5s) instead of heartbeat (1800s)."""
    src = inspect.getsource(run_daemon)
    # Find the is_idle = ... assignment line(s) via regex (\bis_idle\s*=\s*[^=])
    # — matches a bare-name LHS assignment without confusing == comparison
    # tokens INSIDE the RHS expression.
    is_idle_assign_re = re.compile(r"\bis_idle\s*=\s*[^=]")
    is_idle_lines = [
        line for line in src.splitlines()
        if is_idle_assign_re.search(line)
    ]
    assert is_idle_lines, f"no is_idle assignment found in run_daemon source: {src[:500]!r}"
    assert any("plan_kickoffs" in line for line in is_idle_lines), (
        f"run_daemon is_idle assignment must reference 'plan_kickoffs'; "
        f"got lines: {is_idle_lines}"
    )
