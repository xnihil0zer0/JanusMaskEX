"""Adversarial regression tests for run_agent_phase retry budget + backoff.

These two tests assert that:

1. The default value of the `max_retries` keyword argument on
   `harness.orchestrator.run_agent_phase` is the integer 3 (widened from 1).
2. The function body contains at least one `time.sleep(...)` call whose
   argument contains a `2 ** N` exponentiation (e.g. `2 ** attempt` or
   `min(60, 2 ** attempt)`), implementing exponential backoff between retry
   attempts.

Both tests are marked xfail(strict=True) until task
RUN_AGENT_PHASE_RETRY_BUDGET is dispatched and lands the harness self-fix.
Once the fix is in, pytest will convert the xfail into a PASS via the strict
xpass contract (failing the run if either assertion still does not hold).

Static analysis only — these tests parse `harness/orchestrator.py` with
`ast.parse` and walk the tree. No subprocess, no network, no harness
sub-imports needed beyond the source path. This keeps the regression cheap
and resilient to future signature additions.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

ORCHESTRATOR_PATH = (
    Path(__file__).resolve().parent.parent.parent / "harness" / "orchestrator.py"
)


def _load_run_agent_phase_node() -> ast.FunctionDef:
    """Parse harness/orchestrator.py and return the run_agent_phase FunctionDef."""
    src = ORCHESTRATOR_PATH.read_text()
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "run_agent_phase":
            return node
    raise AssertionError(
        f"run_agent_phase FunctionDef not found in {ORCHESTRATOR_PATH}"
    )


def test_run_agent_phase_default_max_retries_is_three() -> None:
    """The `max_retries` keyword default should be the integer 3, not 1.

    A single retry attempt (the current default of 1) means the existing
    retry-loop body never executes more than once, leaving the harness
    fragile to transient Gemini/Claude API hiccups. The fix widens the
    default to 3, matching the industry retry budget for synchronous
    LLM-call wrappers.
    """
    fn = _load_run_agent_phase_node()
    args = fn.args

    # Locate the position of `max_retries` in the full positional+kwonly list.
    all_arg_names = [a.arg for a in args.args]
    assert "max_retries" in all_arg_names, (
        "run_agent_phase signature no longer has a max_retries parameter; "
        "the brief assumes its presence"
    )

    # args.defaults aligns with the TAIL of args.args (Python semantics:
    # the last N args have defaults, where N == len(defaults)).
    n_args = len(args.args)
    n_defaults = len(args.defaults)
    first_default_idx = n_args - n_defaults
    max_retries_idx = all_arg_names.index("max_retries")
    assert max_retries_idx >= first_default_idx, (
        f"max_retries at position {max_retries_idx} appears to have no default; "
        f"defaults align starting at position {first_default_idx}"
    )

    default_node = args.defaults[max_retries_idx - first_default_idx]
    assert isinstance(default_node, ast.Constant), (
        f"max_retries default is not a literal Constant; got {ast.dump(default_node)}"
    )
    assert default_node.value == 3, (
        f"max_retries default is {default_node.value!r}, expected 3 "
        f"(widened from 1 per brief_hooks_run_agent_phase_retry_budget.md)"
    )


def test_run_agent_phase_uses_exponential_backoff() -> None:
    """The body of run_agent_phase should call time.sleep(...) with a 2**N exponent.

    The acceptance pattern is `time.sleep(min(60, 2 ** attempt))` or any
    semantically equivalent expression where the sleep argument transitively
    contains a `BinOp` with `op=ast.Pow()` and `left=ast.Constant(value=2)`.
    This proves the retry path waits a growing amount of time between
    attempts rather than hammering the API immediately on failure.
    """
    fn = _load_run_agent_phase_node()

    # Find every time.sleep(...) call inside the function body.
    sleep_calls: list[ast.Call] = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "sleep"
            and isinstance(func.value, ast.Name)
            and func.value.id == "time"
        ):
            sleep_calls.append(node)

    assert sleep_calls, (
        "no `time.sleep(...)` call found inside run_agent_phase body; "
        "exponential backoff between retries is missing"
    )

    # At least one of those sleeps must take an argument containing 2 ** N.
    def _contains_pow_of_two(call: ast.Call) -> bool:
        for arg in call.args:
            for sub in ast.walk(arg):
                if (
                    isinstance(sub, ast.BinOp)
                    and isinstance(sub.op, ast.Pow)
                    and isinstance(sub.left, ast.Constant)
                    and sub.left.value == 2
                ):
                    return True
        return False

    assert any(_contains_pow_of_two(c) for c in sleep_calls), (
        "no `time.sleep(...)` call inside run_agent_phase has a `2 ** N` "
        "exponent in its argument; expected something like "
        "`time.sleep(min(60, 2 ** attempt))`"
    )
