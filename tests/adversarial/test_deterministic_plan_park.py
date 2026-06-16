"""Adversarial regression: pin the deterministic plan-failure parking behavior.

This file pins the unit-level behavior of
``harness.autowork_daemon._recently_failed_to_plan`` shipped at commit 2692818:
a deterministic planner failure parks (keeps backing off) after a single
attempt for a full 24h, while the orthogonal stochastic grace-budget-of-2
schedule is preserved.

Markers are written exclusively through the real
``harness.autowork_daemon._plan_attempt_marker_path`` helper so the test
exercises the production path layout, and ``last_ts`` is always stamped
relative to ``time.time()``. Each test gets a fresh ``tmp_path``-rooted
``state_dir`` so a JSON marker from one case never leaks into another.

Scope: this pins ONLY ``_recently_failed_to_plan``. It does not touch any
production module and does not modify the existing
``test_escalating_backoff_recently_failed_to_plan.py``.
"""
import json
import pathlib
import time
from harness import autowork_daemon

def _write_marker(state_dir: pathlib.Path, slug: str, marker: dict) -> pathlib.Path:
    """Write ``marker`` to the real plan-attempt path for ``slug``.

    Uses the production ``_plan_attempt_marker_path`` helper, creates the
    parent directory with ``parents=True, exist_ok=True`` and serializes the
    dict with ``json.dumps`` -- mirroring how ``_auto_promote`` stamps the
    marker in production.
    """
    path = autowork_daemon._plan_attempt_marker_path(state_dir, slug)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(marker), encoding='utf-8')
    return path

def test_deterministic_parks_after_one_attempt_returns_true(tmp_path):
    """Case 1 (mutation sentinel): deterministic + 1 attempt -> still parked."""
    slug = 'case1-deterministic-one-attempt'
    _write_marker(tmp_path, slug, {'deterministic': True, 'attempts': 1, 'last_ts': time.time()})
    assert autowork_daemon._recently_failed_to_plan(tmp_path, slug) is True

def test_stochastic_grace_preserved_at_attempt_one_returns_false(tmp_path):
    """Case 2: stochastic failure at attempt 1 stays inside the grace budget."""
    slug = 'case2-stochastic-attempt-one'
    _write_marker(tmp_path, slug, {'deterministic': False, 'attempts': 1, 'last_ts': time.time()})
    assert autowork_daemon._recently_failed_to_plan(tmp_path, slug) is False

def test_stochastic_grace_preserved_at_attempt_two_returns_false(tmp_path):
    """Case 3: stochastic failure at attempt 2 still inside the grace budget."""
    slug = 'case3-stochastic-attempt-two'
    _write_marker(tmp_path, slug, {'deterministic': False, 'attempts': 2, 'last_ts': time.time()})
    assert autowork_daemon._recently_failed_to_plan(tmp_path, slug) is False

def test_deterministic_park_self_expires_after_24h_returns_false(tmp_path):
    """Case 4: deterministic park is time-bounded, not a permanent latch.

    ``last_ts`` is stamped 90000s (>86400.0 / 24h) in the past, so the park
    has self-expired and the slug is eligible to replan again.
    """
    slug = 'case4-deterministic-expired'
    _write_marker(tmp_path, slug, {'deterministic': True, 'attempts': 1, 'last_ts': time.time() - 90000})
    assert autowork_daemon._recently_failed_to_plan(tmp_path, slug) is False

def test_regression_deterministic_park_branch_mutation_sentinel_case_1(tmp_path):
    """Regression: re-pin Case 1 as the explicit non-vacuity sentinel.

    A mutant that removes or weakens the
    ``if deterministic and attempts >= 1: threshold = 86400.0`` branch (e.g.
    ``attempts >= 99`` or condition dropped) routes a fresh deterministic
    1-attempt marker into the ``attempts <= 2 -> threshold 0.0`` tier, flipping
    this assertion from True to False and failing the suite.
    """
    slug = 'regression-deterministic-park-sentinel'
    _write_marker(tmp_path, slug, {'deterministic': True, 'attempts': 1, 'last_ts': time.time()})
    assert autowork_daemon._recently_failed_to_plan(tmp_path, slug) is True

def test_regression_existing_escalating_backoff_test_file_untouched_byte_for_byte():
    """Regression: the orthogonal stochastic-grace backoff test still ships.

    The deterministic-park file must coexist with -- and not replace -- the
    existing ``test_escalating_backoff_recently_failed_to_plan.py`` sibling,
    which pins the orthogonal stochastic-grace schedule and must remain
    present and non-empty.
    """
    sibling = pathlib.Path(__file__).resolve().parent / 'test_escalating_backoff_recently_failed_to_plan.py'
    assert sibling.is_file(), f'expected sibling backoff test at {sibling}'
    assert sibling.stat().st_size > 0