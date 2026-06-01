"""Phase C6/H3 adversarial — ast_retry per-attempt HARD timeout budget check.

Asserts:
  (a) When synthesis_timeout is 600.0, the new HARD timeout budget is 1500.0 (synthesis_timeout * 2 + 300.0).
  (b) The retry guard at attempt > 0 aborts if the remaining budget is less than the synthesis window (synthesis_timeout).
  (c) With a synthesis_timeout of 600.0:
      - If 899.0s have elapsed (remaining budget 1500.0 - 899.0 = 601.0s >= 600.0s), the retry is allowed.
      - If 901.0s have elapsed (remaining budget 1500.0 - 901.0 = 599.0s < 600.0s), the retry is aborted.
      - On HEAD, HARD is only 900.0s, so even at 899.0s elapsed (remaining 1.0s < 600.0s), the retry is aborted (RED).
      - After the fix, HARD is 1500.0s, so the retry is allowed at 899.0s elapsed, but still aborted at 901.0s (GREEN).
"""
import time
from pathlib import Path
from unittest.mock import patch
import pytest

from harness.ast_retry import synthesize_with_retries


def test_ast_retry_hard_budget_within_new_limit():
    """Asserts that elapsed time less than (2 * synthesis_timeout + 300 - synthesis_timeout)

    allows the retry to proceed under the new formula, which fails on HEAD.
    """
    agent_calls = []

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        agent_calls.append(prompt)
        return "some_code"

    def validate_code(code, task):
        return False, ["AST error"]

    # We mock time.monotonic() to return:
    # 1. 0.0 at the start of synthesize_with_retries
    # 2. 899.0 when evaluating the retry guard for attempt = 1
    # 3. 899.0 for any subsequent calls
    time_values = [0.0, 899.0]
    time_iter = iter(time_values)

    def mock_monotonic():
        try:
            return next(time_iter)
        except StopIteration:
            return 899.0

    config = {
        "synthesis": {
            "max_ast_retries": 2,
            "timeout_seconds": 600.0
        }
    }

    with patch("time.monotonic", side_effect=mock_monotonic):
        success, code, violations = synthesize_with_retries(
            agent_name="dummy_agent",
            base_prompt="base",
            config=config,
            state_dir=Path("/tmp"),
            round_number=1,
            task={},
            run_agent_func=run_agent,
            validate_code_func=validate_code
        )

    # After the fix, 1500 - 899 = 601 >= 600, so a second attempt is run.
    # On HEAD, 900 - 899 = 1 < 600, so it aborts early with only 1 attempt.
    assert len(agent_calls) == 2
    assert success is False
    assert violations == ["AST error"]


def test_ast_retry_hard_budget_exceeds_new_limit():
    """Asserts that elapsed time greater than (2 * synthesis_timeout + 300 - synthesis_timeout)

    still aborts the retry, even after the fix.
    """
    agent_calls = []

    def run_agent(agent_name, prompt, config, state_dir, round_number, phase_name):
        agent_calls.append(prompt)
        return "some_code"

    def validate_code(code, task):
        return False, ["AST error"]

    # We mock time.monotonic() to return:
    # 1. 0.0 at the start
    # 2. 901.0 when checking the guard
    time_values = [0.0, 901.0]
    time_iter = iter(time_values)

    def mock_monotonic():
        try:
            return next(time_iter)
        except StopIteration:
            return 901.0

    config = {
        "synthesis": {
            "max_ast_retries": 2,
            "timeout_seconds": 600.0
        }
    }

    with patch("time.monotonic", side_effect=mock_monotonic):
        success, code, violations = synthesize_with_retries(
            agent_name="dummy_agent",
            base_prompt="base",
            config=config,
            state_dir=Path("/tmp"),
            round_number=1,
            task={},
            run_agent_func=run_agent,
            validate_code_func=validate_code
        )

    # In both HEAD and FIX, 901.0s elapsed exceeds the allowed budget headroom,
    # so the retry is aborted, calling the agent only once.
    assert len(agent_calls) == 1
    assert success is False
    assert violations == ["AST error"]
