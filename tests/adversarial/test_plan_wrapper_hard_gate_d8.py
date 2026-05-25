"""Adversarial tests for PLAN_WRAPPER_HARD_GATE_D8.

Pre-staged xfail-strict tests that flip to PASS once the D8 dispatch lands.

D8 is the planner-side mirror of V1: V1 hardened the orchestrator-side
``_auto_commit_accepted`` to refuse commits when ``verification_command`` is
missing/empty; D8 hardens the planner-side ``validate_plan_wrapper`` to
RAISE (rather than merely return a ``PlanViolation`` list) when any task in
``plan['tasks']`` has a missing / empty / whitespace-only / non-string
``verification_command``. This catches the bad-plan condition at plan-build
time so the daemon Path-B pipeline cannot enqueue a task that the orchestrator
will silently refuse to commit downstream.

Current HEAD: ``validate_plan_wrapper`` at
``harness/planner/plan_validator.py:190-218`` only inspects schema v2.1
wrapper fields (``source_brief_path`` / ``source_brief_sha256``) — it does
NOT walk ``plan['tasks']``. These tests all assert post-dispatch behavior
and therefore all currently XFAIL (strict=True so they flip to XPASSED and
fail the suite if the dispatch lands without enabling them).
"""

from __future__ import annotations

import pytest

from harness.planner.plan_validator import validate_plan_wrapper


# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_VALID_WRAPPER = {
    "source_brief_path": "/tmp/brief.md",
    "source_brief_sha256": "0" * 64,
}


def _plan_with_task(task: dict) -> dict:
    """Return a wrapper-valid plan with a single task entry."""
    return {**_VALID_WRAPPER, "tasks": [task]}


# ---------------------------------------------------------------------------
# Post-dispatch behavioral tests
# ---------------------------------------------------------------------------


def test_validate_plan_wrapper_raises_on_missing_verification_command() -> None:
    """When verification_command key is absent entirely, raise with task_id."""
    bad = _plan_with_task({"task_id": "TASK_MISSING_VC", "title": "t", "files_touched": ["x"]})
    with pytest.raises(Exception) as exc_info:
        validate_plan_wrapper(bad)
    msg = str(exc_info.value)
    assert "verification_command" in msg.lower(), (
        f"Error message missing 'verification_command' substring: {msg!r}"
    )
    assert "TASK_MISSING_VC" in msg, (
        f"Error message missing offending task_id 'TASK_MISSING_VC': {msg!r}"
    )


def test_validate_plan_wrapper_raises_on_empty_string_verification_command() -> None:
    """When verification_command == '', raise with the task_id."""
    bad = _plan_with_task(
        {
            "task_id": "TASK_EMPTY_VC",
            "title": "t",
            "files_touched": ["x"],
            "verification_command": "",
        }
    )
    with pytest.raises(Exception) as exc_info:
        validate_plan_wrapper(bad)
    msg = str(exc_info.value)
    assert "verification_command" in msg.lower(), (
        f"Error message missing 'verification_command' substring: {msg!r}"
    )
    assert "TASK_EMPTY_VC" in msg, (
        f"Error message missing offending task_id 'TASK_EMPTY_VC': {msg!r}"
    )


def test_validate_plan_wrapper_raises_on_whitespace_verification_command() -> None:
    """When verification_command is whitespace-only ('   \\t\\n'), raise."""
    bad = _plan_with_task(
        {
            "task_id": "TASK_WS_VC",
            "title": "t",
            "files_touched": ["x"],
            "verification_command": "   \t\n",
        }
    )
    with pytest.raises(Exception) as exc_info:
        validate_plan_wrapper(bad)
    msg = str(exc_info.value)
    assert "verification_command" in msg.lower(), (
        f"Error message missing 'verification_command' substring: {msg!r}"
    )
    assert "TASK_WS_VC" in msg, (
        f"Error message missing offending task_id 'TASK_WS_VC': {msg!r}"
    )


def test_validate_plan_wrapper_does_not_raise_when_verification_command_is_valid() -> None:
    """Happy-path regression guard (NOT xfail): a task with a non-empty string
    verification_command must NOT cause validate_plan_wrapper to raise — both
    today (pre-dispatch, the per-task scan does not exist) and post-dispatch
    (the scan exists but takes the happy-path branch). The function may still
    return a list of PlanViolation (e.g., for source_brief_* checks on a
    different plan shape), but it must not propagate an exception when the
    verification_command itself is well-formed.

    This is intentionally NOT xfail-marked: it pins the existing contract so
    a bad dispatch that over-eagerly raises on a valid plan would fail this
    test.
    """
    good = _plan_with_task(
        {
            "task_id": "TASK_GOOD_VC",
            "title": "t",
            "files_touched": ["x"],
            "verification_command": "python -c 'print(\"ok\")'",
        }
    )
    # Should NOT raise — assert by simply calling and confirming the return
    # type is a list (the existing contract).
    result = validate_plan_wrapper(good)
    assert isinstance(result, list), (
        f"validate_plan_wrapper happy path must return list, got {type(result).__name__}"
    )
