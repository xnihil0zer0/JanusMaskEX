"""Adversarial regression bar for escalating_backoff_recently_failed_to_plan.

Pin the contract that ``harness.autowork_daemon._recently_failed_to_plan``
switches from a fixed 1-hour cooldown to attempt-count-driven exponential
backoff:

- attempts <= 1  -> 300s (5 minutes)
- attempts == 2  -> 3600s (1 hour)
- attempts >= 3  -> 86400s (24 hours)

The marker file format on disk migrates from a text file ending in
``.failed`` (whose mtime drove the TTL) to a JSON document ending in
``.json`` containing ``{"attempts": int, "last_ts": float}``.

Pattern mirrors ``tests/adversarial/test_autowork_auto_promote_staleness.py``
(session #17 AW11): tests ship with ``xfail(strict=True, reason=...)`` and
the post-accept verifier runs pytest with ``--runxfail`` so the markers
are bypassed at gate time. A follow-up META commit drops the markers and
the tests pass naturally.

Each test asserts a value that is a load-bearing DIFFERENTIAL between the
legacy fixed-1h-TTL implementation and the new tiered implementation:
- Legacy and new disagree -> xfail-strict succeeds today, flips PASS post-accept.
- Legacy and new agree -> would XPASS today and break the xfail-strict bar.

Authored by session #24 sub-agent P3.4 against
``brief_hooks_escalating_backoff_recently_failed_to_plan.md``.
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
    """Write a JSON plan-attempts marker for ``slug`` and return its path.

    Also pins the file's mtime to ``last_ts`` so the legacy mtime-based
    implementation observes the SAME age that the post-accept JSON-aware
    implementation reads from the file body. Without this, the legacy
    implementation always sees mtime~=now (the file was just created) and
    the XFAIL discriminator collapses.
    """
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
    """The marker filename must end in ``.json`` (NOT ``.failed``).

    Load-bearing differential: legacy returns ``demo.failed``, new returns
    ``demo.json``. This is the canary that the file-format migration
    landed.
    """
    from harness.autowork_daemon import _plan_attempt_marker_path

    marker = _plan_attempt_marker_path(state_dir, "demo_suffix")
    assert str(marker).endswith(".json"), (
        f"marker path must end in .json, got {marker!r}; "
        "legacy .failed suffix means the file-format migration has not landed"
    )


def test_first_attempt_past_5min_out_of_cooldown(state_dir: pathlib.Path) -> None:
    """attempts=1, age=2000s -> past 5min but under 1h -> False.

    Load-bearing differential vs legacy: legacy fixed-1h TTL returns True
    (2000 < 3600); new tier returns False (2000 > 300). This test
    asserts False, so legacy fails it (XFAIL today) and new passes
    (drops xfail post-accept).
    """
    from harness.autowork_daemon import _recently_failed_to_plan

    _write_marker(state_dir, "demo_first_stale", attempts=1, last_ts=time.time() - 2000)

    assert _recently_failed_to_plan(state_dir, "demo_first_stale") is False, (
        "attempts=1, age=2000s must be OUTSIDE the 5min cooldown (300s threshold); "
        "the legacy fixed-1h TTL would have returned True here (2000 < 3600), "
        "which is the bug this brief fixes"
    )


def test_third_attempt_within_24h_still_in_cooldown(state_dir: pathlib.Path) -> None:
    """attempts=3, age=3700s -> past 1h, within 24h -> True.

    Load-bearing differential vs legacy: legacy fixed-1h TTL returns
    False (3700 > 3600); new tier returns True (3700 < 86400). This
    test asserts True, so legacy fails it (XFAIL today) and new passes
    (drops xfail post-accept).
    """
    from harness.autowork_daemon import _recently_failed_to_plan

    _write_marker(state_dir, "demo_third_escalated", attempts=3, last_ts=time.time() - 3700)

    assert _recently_failed_to_plan(state_dir, "demo_third_escalated") is True, (
        "attempts=3, age=3700s must be INSIDE the 24h cooldown (86400s threshold); "
        "the legacy fixed-1h TTL would have returned False here (3700 > 3600), "
        "which is the bug this brief fixes"
    )


def test_attempts_key_drives_threshold_not_just_mtime(state_dir: pathlib.Path) -> None:
    """Two markers with the SAME age but different ``attempts`` must
    yield different boolean results.

    Construct one marker with attempts=1 (5min tier) and another with
    attempts=3 (24h tier), both at age=4000s. Under the legacy mtime-
    only check, both return False (4000 > 3600). Under the new
    tiered check, attempts=1 returns False (4000 > 300) and
    attempts=3 returns True (4000 < 86400). This pinpoints that the
    backoff is genuinely attempt-count-driven and not just a longer
    fixed TTL.
    """
    from harness.autowork_daemon import _recently_failed_to_plan

    _write_marker(state_dir, "demo_low_attempts", attempts=1, last_ts=time.time() - 4000)
    _write_marker(state_dir, "demo_high_attempts", attempts=3, last_ts=time.time() - 4000)

    low = _recently_failed_to_plan(state_dir, "demo_low_attempts")
    high = _recently_failed_to_plan(state_dir, "demo_high_attempts")

    assert low is False and high is True, (
        f"attempts must drive the tier: attempts=1 at age=4000s -> False (was {low!r}); "
        f"attempts=3 at age=4000s -> True (was {high!r}); "
        "the legacy mtime-only implementation would return False for both, "
        "which is the bug this brief fixes"
    )
