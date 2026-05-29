"""Tests for the config-derived per-worker timeout budgets (Brief 1,
RECONCILE_TIMEOUT_BUDGETS). Landed as the R9-sanctioned bootstrap hand-edit;
this test is its real acceptance gate (harness_self_fix skips import-smoke).

Asserts:
  (a) harness.orchestrator_worker imports.
  (b) _compute_timeout_budgets tracks synthesis.timeout_seconds:
        600  -> (900, 600), 1200 -> (1500, 1200).
  (c) the inner HARD budget always sits below the daemon watchdog
        max(1800.0, timeout + 300.0) for representative timeouts.
"""


def test_module_imports():
    import harness.orchestrator_worker  # noqa: F401


def test_budgets_track_config_timeout():
    from harness.orchestrator_worker import (
        RECONCILE_SLACK_SECONDS,
        _compute_timeout_budgets,
    )

    assert RECONCILE_SLACK_SECONDS == 300.0

    # window == timeout; hard == timeout + slack.
    assert _compute_timeout_budgets({'synthesis': {'timeout_seconds': 600}}) == (900.0, 600.0)
    assert _compute_timeout_budgets({'synthesis': {'timeout_seconds': 1200}}) == (1500.0, 1200.0)


def test_budgets_default_when_unconfigured():
    from harness.orchestrator_worker import _compute_timeout_budgets

    # Missing synthesis / missing timeout / empty config all fall back to 600.
    assert _compute_timeout_budgets({}) == (900.0, 600.0)
    assert _compute_timeout_budgets({'synthesis': {}}) == (900.0, 600.0)
    assert _compute_timeout_budgets(None) == (900.0, 600.0)


def test_inner_hard_below_daemon_watchdog():
    from harness.orchestrator_worker import _compute_timeout_budgets

    def daemon_watchdog(timeout: float) -> float:
        # Mirrors autowork_daemon: max(1800.0, timeout + 300.0).
        return max(1800.0, timeout + 300.0)

    # Representative / in-use timeouts: inner HARD stays strictly below the
    # outer watchdog with margin.
    for timeout in (300, 600, 900, 1200):
        hard, window = _compute_timeout_budgets({'synthesis': {'timeout_seconds': timeout}})
        assert window == float(timeout)
        assert hard < daemon_watchdog(timeout), (
            f'inner HARD {hard} must stay below watchdog {daemon_watchdog(timeout)} '
            f'at timeout={timeout}'
        )

    # Boundary the plan flags for a future daemon revisit: at timeout=1500 the
    # inner HARD (1800) meets the watchdog floor (1800) — no margin. Anything
    # above 1500 would invert the invariant, so the daemon formula must be
    # revisited before raising synthesis.timeout_seconds past 1500.
    hard_1500, _ = _compute_timeout_budgets({'synthesis': {'timeout_seconds': 1500}})
    assert hard_1500 == daemon_watchdog(1500) == 1800.0
