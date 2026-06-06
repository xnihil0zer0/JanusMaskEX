"""Adversarial regression bar for ``_recently_failed_to_plan`` backoff.

Pins the contract that ``harness.autowork_daemon._recently_failed_to_plan``
gives a GRACE RETRY BUDGET OF 2 before the escalating backoff begins, then
escalates by attempt count:

- attempts <= 2  -> 0s     (grace budget: retry immediately, no backoff)
- attempts == 3  -> 300s   (5 minutes; first backoff tier after the budget)
- attempts == 4  -> 3600s  (1 hour)
- attempts >= 5  -> 86400s (24 hours)

This SUPERSEDES the prior tiering (attempts<=1 -> 300s, ==2 -> 3600s,
>=3 -> 86400s). Motivation: planner kickoffs fail *stochastically*
(dual-agent reconciliation flakes), so the first couple of failures must
be retried promptly instead of being penalised as if deterministic. The
budget of 2 converts an unlucky stochastic streak into "retry twice, then
back off".

The marker file is a JSON document ending in ``.json`` containing
``{"attempts": int, "last_ts": float}``.

Each behavioural test asserts a value that is a load-bearing DIFFERENTIAL
between the legacy tiering and the new budget-of-2 tiering, so the legacy
implementation fails it (RED today) and the post-fix implementation passes.
"""
from __future__ import annotations

import json
import os
import pathlib
import time

import pytest


@pytest.fixture
def state_dir(tmp_path: pathlib.Path) -> pathlib.Path:
    """Return a fresh ``state_dir`` rooted under ``tmp_path``."""
    d = tmp_path / "state"
    (d / "control" / "autowork" / "plan_attempts").mkdir(parents=True)
    return d


def _write_marker(state_dir: pathlib.Path, slug: str, attempts: int, last_ts: float) -> pathlib.Path:
    """Write a JSON plan-attempts marker for ``slug`` and return its path."""
    from harness.autowork_daemon import _plan_attempt_marker_path

    marker = _plan_attempt_marker_path(state_dir, slug)
    marker.parent.mkdir(parents=True, exist_ok=True)
    marker.write_text(
        json.dumps({"attempts": attempts, "last_ts": last_ts}, sort_keys=True),
        encoding="utf-8",
    )
    os.utime(marker, (last_ts, last_ts))
    return marker


def test_marker_path_suffix_is_json(state_dir: pathlib.Path) -> None:
    """The marker filename must end in ``.json`` (NOT ``.failed``)."""
    from harness.autowork_daemon import _plan_attempt_marker_path

    marker = _plan_attempt_marker_path(state_dir, "demo_suffix")
    assert str(marker).endswith(".json"), (
        f"marker path must end in .json, got {marker!r}"
    )


def test_first_attempt_within_grace_budget_immediately_retriable(state_dir: pathlib.Path) -> None:
    """attempts=1 is within the grace budget -> always retriable (False).

    Differential vs legacy: legacy gave attempts<=1 a 300s cooldown, so a
    fresh marker (age ~0) returned True. The budget-of-2 contract returns
    False for any age because the first failure is free.
    """
    from harness.autowork_daemon import _recently_failed_to_plan

    _write_marker(state_dir, "demo_grace_1", attempts=1, last_ts=time.time() - 5)

    assert _recently_failed_to_plan(state_dir, "demo_grace_1") is False, (
        "attempts=1 is within the grace budget of 2 and must be retriable "
        "immediately; legacy gave it a 300s cooldown (True at age=5s)"
    )


def test_second_attempt_within_grace_budget_immediately_retriable(state_dir: pathlib.Path) -> None:
    """attempts=2 is the last grace retry -> still retriable (False).

    Differential vs legacy: legacy gave attempts==2 a 3600s cooldown, so a
    fresh marker returned True. The budget-of-2 contract returns False.
    """
    from harness.autowork_daemon import _recently_failed_to_plan

    _write_marker(state_dir, "demo_grace_2", attempts=2, last_ts=time.time() - 5)

    assert _recently_failed_to_plan(state_dir, "demo_grace_2") is False, (
        "attempts=2 is still within the grace budget of 2 and must be "
        "retriable immediately; legacy gave it a 3600s cooldown (True at age=5s)"
    )


def test_third_attempt_begins_300s_backoff(state_dir: pathlib.Path) -> None:
    """attempts=3 exhausts the budget and enters the 300s tier.

    Pins both sides of the 300s threshold, and the stale side is a
    differential vs legacy (which put attempts>=3 in the 86400s tier).
    """
    from harness.autowork_daemon import _recently_failed_to_plan

    _write_marker(state_dir, "demo_t3_fresh", attempts=3, last_ts=time.time() - 100)
    _write_marker(state_dir, "demo_t3_stale", attempts=3, last_ts=time.time() - 400)

    assert _recently_failed_to_plan(state_dir, "demo_t3_fresh") is True, (
        "attempts=3 at age=100s is inside the 300s backoff -> True"
    )
    assert _recently_failed_to_plan(state_dir, "demo_t3_stale") is False, (
        "attempts=3 at age=400s is past the 300s backoff -> False; "
        "legacy put attempts>=3 in the 86400s tier (True here)"
    )


def test_fourth_attempt_3600s_backoff(state_dir: pathlib.Path) -> None:
    """attempts=4 enters the 3600s tier.

    The stale side is a differential vs legacy (attempts>=3 -> 86400s).
    """
    from harness.autowork_daemon import _recently_failed_to_plan

    _write_marker(state_dir, "demo_t4_fresh", attempts=4, last_ts=time.time() - 1000)
    _write_marker(state_dir, "demo_t4_stale", attempts=4, last_ts=time.time() - 4000)

    assert _recently_failed_to_plan(state_dir, "demo_t4_fresh") is True, (
        "attempts=4 at age=1000s is inside the 3600s backoff -> True"
    )
    assert _recently_failed_to_plan(state_dir, "demo_t4_stale") is False, (
        "attempts=4 at age=4000s is past the 3600s backoff -> False; "
        "legacy put attempts>=3 in the 86400s tier (True here)"
    )


def test_fifth_attempt_24h_backoff(state_dir: pathlib.Path) -> None:
    """attempts>=5 enters the 86400s (24h) tier."""
    from harness.autowork_daemon import _recently_failed_to_plan

    _write_marker(state_dir, "demo_t5_in", attempts=5, last_ts=time.time() - 4000)
    _write_marker(state_dir, "demo_t5_out", attempts=5, last_ts=time.time() - 90000)

    assert _recently_failed_to_plan(state_dir, "demo_t5_in") is True, (
        "attempts=5 at age=4000s is inside the 24h backoff -> True"
    )
    assert _recently_failed_to_plan(state_dir, "demo_t5_out") is False, (
        "attempts=5 at age=90000s is past the 24h backoff -> False"
    )
