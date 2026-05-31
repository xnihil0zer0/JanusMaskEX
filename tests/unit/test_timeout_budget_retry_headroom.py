"""Fix-detector for G-RETRY-BUDGET-HEADROOM.

The per-worker retry guard at harness/orchestrator_worker.py:244-249 refuses a
retry when the remaining wall budget is below one synthesis window:

    remaining_budget = HARD_TIMEOUT_SECONDS - (elapsed)
    if remaining_budget < SYNTHESIS_WINDOW_SECONDS: ... return exit_code 2

On HEAD, `_compute_timeout_budgets` returns HARD = WINDOW + RECONCILE_SLACK
(slack = 300s). After the FIRST synthesis attempt consumes ~one WINDOW, the
remaining budget is only ~300s, which is < WINDOW for any realistic window
(600/1200s). So a retry is *structurally impossible* — every AST-invalid /
single-agent-missing loop trips `retry_budget_exhausted` on the first retry.
This is what produced `retry_budget_exhausted` on both prior A-test runs.

THE FIX makes HARD = 2*WINDOW + slack, so:
  - after consuming exactly ONE window, remaining = WINDOW + slack >= WINDOW
    -> ONE retry is permitted (the discriminating assertion (a) below);
  - after a SECOND window, remaining = slack < WINDOW -> a second retry is
    correctly refused, capping at <= 2 attempts (assertion (b)).

THIS TEST FAILS ON HEAD (assertion (a): HEAD HARD-WINDOW = 300 < WINDOW) and
PASSES once `_compute_timeout_budgets` is fixed. It is a genuine fail-then-pass
detector. The window value (WINDOW == T) is left unchanged by the fix.
"""

import pytest

from harness.orchestrator_worker import (
    RECONCILE_SLACK_SECONDS,
    _compute_timeout_budgets,
)


@pytest.mark.parametrize("T", [1200, 600])
def test_one_retry_window_of_headroom(T):
    """(a) DISCRIMINATING fail-then-pass check.

    The window is unchanged (WINDOW == T) AND, after consuming exactly one
    full synthesis window, the remaining hard budget still covers a full retry
    window (HARD - WINDOW >= WINDOW). FAILS on HEAD (HARD-WINDOW = 300 < WINDOW).
    """
    hard, window = _compute_timeout_budgets({'synthesis': {'timeout_seconds': T}})

    assert window == float(T), "synthesis window must track timeout_seconds unchanged"
    assert hard - window >= window, (
        f"after one window ({window}s) the remaining budget {hard - window}s "
        f"must still cover a full retry window ({window}s) — HEAD fails this "
        f"(HARD-WINDOW = {RECONCILE_SLACK_SECONDS}s < window)"
    )


@pytest.mark.parametrize("T", [1200, 600])
def test_second_retry_is_refused_cap_at_two_attempts(T):
    """(b) <=2-attempt cap: after a SECOND window the remaining budget is below
    one window, so a second retry is correctly refused. Holds on HEAD too (not
    discriminating) — kept to pin the cap post-fix."""
    hard, window = _compute_timeout_budgets({'synthesis': {'timeout_seconds': T}})

    assert hard - 2 * window < window, (
        f"a SECOND retry must be refused: remaining after two windows "
        f"({hard - 2 * window}s) must be < one window ({window}s)"
    )


@pytest.mark.parametrize("T", [1200, 600])
def test_exact_post_fix_formula(T):
    """(c) Lock the post-fix shape: HARD == 2*T + RECONCILE_SLACK_SECONDS.

    FAILS on HEAD (HEAD: HARD == T + slack)."""
    hard, window = _compute_timeout_budgets({'synthesis': {'timeout_seconds': T}})

    assert window == float(T)
    assert hard == 2 * float(T) + RECONCILE_SLACK_SECONDS, (
        f"post-fix HARD must be 2*T + slack = {2 * float(T) + RECONCILE_SLACK_SECONDS}s, "
        f"got {hard}s"
    )
