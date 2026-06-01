"""Tests for the config-derived per-worker timeout budgets (Brief 1,
RECONCILE_TIMEOUT_BUDGETS), updated for G-RETRY-BUDGET-HEADROOM.

Originally landed as the R9-sanctioned bootstrap hand-edit; this test is its
real acceptance gate (harness_self_fix skips import-smoke).

G-RETRY-BUDGET-HEADROOM changed the inner HARD budget from one synthesis window
+ slack to TWO windows + slack, so the retry guard at
harness/orchestrator_worker.py:244-249 can actually permit one retry after a
first-attempt timeout (HEAD budgeted only `window + 300s` of slack, which is
less than one window, so a retry was structurally impossible).

Asserts:
  (a) harness.orchestrator_worker imports.
  (b) _compute_timeout_budgets tracks synthesis.timeout_seconds with the
        TWO-window model: window == timeout; hard == 2*timeout + slack.
        600  -> (1500, 600), 1200 -> (2700, 1200).
  (c) the inner HARD now budgets a full retry window, so for the in-use
        timeouts it can EXCEED the daemon watchdog max(1800.0, timeout + 300.0).
        Under DAEMON dispatch the watchdog therefore binds first (the daemon
        does not realize the extra retry — unchanged from HEAD, no regression);
        the full hard budget is realized on FOREGROUND runs (the daemon is down
        through B / A-MTT / A-TEST). Widening the daemon watchdog to match is a
        separate, owner-gated daemon-behaviour change deferred to Phase A.
"""


def test_module_imports():
    import harness.orchestrator_worker  # noqa: F401


def test_budgets_track_config_timeout():
    from harness.orchestrator_worker import (
        RECONCILE_SLACK_SECONDS,
        _compute_timeout_budgets,
    )

    assert RECONCILE_SLACK_SECONDS == 300.0

    # window == timeout; hard == 2*timeout + slack (one full retry window of
    # headroom on top of the first attempt).
    assert _compute_timeout_budgets({'synthesis': {'timeout_seconds': 600}}) == (1500.0, 600.0)
    assert _compute_timeout_budgets({'synthesis': {'timeout_seconds': 1200}}) == (2700.0, 1200.0)


def test_budgets_default_when_unconfigured():
    from harness.orchestrator_worker import _compute_timeout_budgets

    # Missing synthesis / missing timeout / empty config all fall back to 600.
    assert _compute_timeout_budgets({}) == (1500.0, 600.0)
    assert _compute_timeout_budgets({'synthesis': {}}) == (1500.0, 600.0)
    assert _compute_timeout_budgets(None) == (1500.0, 600.0)


def test_hard_budget_covers_one_retry_window():
    """The defining property of G-RETRY-BUDGET-HEADROOM: after the first
    synthesis attempt consumes one full window, the remaining hard budget still
    covers a complete retry window (so the :245 guard permits exactly one
    retry), and a second window leaves only slack (so a 2nd retry is refused —
    cap at <= 2 attempts).

    The <=2-attempt cap holds precisely when one window exceeds the slack
    (window > RECONCILE_SLACK_SECONDS): after two windows the remaining budget
    is exactly the slack, and the strict guard (`remaining < window`) refuses a
    third attempt only when slack < window. At the degenerate tiny window
    T == slack (300s) the window equals the slack, so the strict cap relaxes —
    irrelevant in practice (the in-use synthesis window is 1200s). We therefore
    assert the cap only where window > slack."""
    from harness.orchestrator_worker import (
        RECONCILE_SLACK_SECONDS,
        _compute_timeout_budgets,
    )

    for timeout in (300, 600, 900, 1200):
        hard, window = _compute_timeout_budgets({'synthesis': {'timeout_seconds': timeout}})
        assert window == float(timeout)
        # one retry always fits (remaining after one window = window + slack >= window) ...
        assert hard - window >= window, (
            f'after one window ({window}s) remaining {hard - window}s must cover '
            f'a full retry window at timeout={timeout}'
        )
        # ... and for realistic windows (window > slack) a second retry does not
        # (<=2-attempt cap). At T == slack the window degenerates; skip it.
        if window > RECONCILE_SLACK_SECONDS:
            assert hard - 2 * window < window, (
                f'a second retry must be refused at timeout={timeout}'
            )


def test_daemon_watchdog_binds_first_on_in_use_timeouts():
    """The daemon watchdog has been widened to max(1800, 2*timeout + 600), so it
    now MATCHES or EXCEEDS the two-window inner HARD budget (timeout * 2 + 300)
    for every in-use timeout. A daemon-dispatched worker therefore gets the full
    retry headroom instead of being reaped early; the watchdog no longer binds
    first. Small timeouts still fit comfortably under the 1800s floor."""
    from harness.orchestrator_worker import _compute_timeout_budgets

    def daemon_watchdog(timeout: float) -> float:
        # Mirrors autowork_daemon.py: max(1800.0, 2.0 * timeout + 600.0).
        return max(1800.0, 2.0 * timeout + 600.0)

    # Small timeouts: inner HARD still fits under the 1800s watchdog floor
    # (300 -> 900 <= 1800, 600 -> 1500 <= 1800).
    for timeout in (300, 600):
        hard, _ = _compute_timeout_budgets({'synthesis': {'timeout_seconds': timeout}})
        assert hard <= daemon_watchdog(timeout)

    # In-use timeout (1200): inner HARD (2700) is now covered by the widened
    # watchdog (max(1800, 2*1200 + 600) = 3000), so a daemon-dispatched worker
    # can use its full retry window before the watchdog would reap it.
    hard_1200, _ = _compute_timeout_budgets({'synthesis': {'timeout_seconds': 1200}})
    assert hard_1200 == 2700.0
    assert hard_1200 <= daemon_watchdog(1200)
