"""P6_WATCHDOG_GATE adversarial oracle.

Drives the REAL ``harness.autowork_daemon._check_inactivity_watchdog`` and
asserts on its REAL fire-signal, which is the pair:

  * the marker file ``state/control/autowork/inactivity_escalated.json`` is
    written, AND
  * ``_escalate_inactivity(state_dir, config)`` is invoked.

We monkeypatch ``_escalate_inactivity`` to a recorder (no real subprocess
spawn) and monkeypatch ``harness.brief_status.compute_autowork_backlog`` (the
function lazily imports it at call time) to report unfinished allowlisted work.

The bug under test: on HEAD the watchdog declares "stuck" whenever there is
unfinished work and no agent-level event for > 1200.0s -- it ignores (a) live
worker/planner pids and (b) the fact that a single long task can legitimately
run for verification_timeout_seconds + timeout_seconds (~3000s) with no
agent_level_event. So a normal long run / a live worker FALSELY fires the
self-heal escalation. The fixed watchdog must NOT fire when a live worker pid
exists and/or when the elapsed time is within the config-derived worst-case
single-task wall.

Hermetic: tmp state dir, monkeypatched time-on-disk (event ts), no network, no
real subprocess spawn.
"""
import json
import pathlib

import pytest

from harness import autowork_daemon as daemon


def _running_dir(state_dir: pathlib.Path) -> pathlib.Path:
    return state_dir / "control" / "autowork" / "running"


def _marker_path(state_dir: pathlib.Path) -> pathlib.Path:
    return state_dir / "control" / "autowork" / "inactivity_escalated.json"


def _write_event_ledger(state_dir: pathlib.Path, age_sec: float, now: float) -> None:
    """Write an agent_level_event ``age_sec`` seconds in the past."""
    ledger = state_dir / "impl_progress.jsonl"
    ledger.parent.mkdir(parents=True, exist_ok=True)
    row = {"event": "worker_start", "ts": now - age_sec, "task_id": "BRIEF_A"}
    ledger.write_text(json.dumps(row) + "\n", encoding="utf-8")


def _install_common_monkeypatches(monkeypatch, state_dir, now, has_work=True):
    """Backlog says there is unfinished allowlisted work; _escalate_inactivity is
    a recorder; time.time() is frozen at ``now``."""
    calls = []

    def _fake_backlog(repo_root, sd, *a, **k):
        return {
            "eligible_with_work": (["BRIEF_A"] if has_work else []),
            "eligible_without_work": [],
            "detail": {},
        }

    # _check_inactivity_watchdog does `from harness.brief_status import
    # compute_autowork_backlog` at call time -> patch on the source module.
    import harness.brief_status as bs

    monkeypatch.setattr(bs, "compute_autowork_backlog", _fake_backlog)
    monkeypatch.setattr(
        daemon, "_escalate_inactivity", lambda sd, cfg: calls.append((sd, cfg))
    )
    monkeypatch.setattr(daemon.time, "time", lambda: now)
    return calls


def _config():
    # Mirrors harness/config.yaml: planner_timeout_sec=1800,
    # verification_timeout_seconds=1200, timeout_seconds=1800 -> worst-case
    # single-task wall ~3000s, all far above the legacy 1200s bar.
    return {
        "autowork": {"planner_timeout_sec": 1800},
        "synthesis": {"timeout_seconds": 1800, "verification_timeout_seconds": 1200},
    }


# ---------------------------------------------------------------------------
# (1) NO-FALSE-FIRE: live worker present + elapsed within worst-case wall.
# ---------------------------------------------------------------------------
def test_watchdog_does_not_fire_with_live_worker(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    now = 1_000_000.0
    calls = _install_common_monkeypatches(monkeypatch, state_dir, now)

    # Last agent_level_event 1500s ago: ABOVE the legacy 1200 bar, but a live
    # worker is running and we are well within the ~3000s worst-case wall.
    _write_event_ledger(state_dir, age_sec=1500.0, now=now)

    # A live worker pidfile: this very test process is unquestionably alive,
    # so os.kill(pid, 0) succeeds.
    import os

    rdir = _running_dir(state_dir)
    rdir.mkdir(parents=True, exist_ok=True)
    (rdir / "BRIEF_A.pid").write_text(str(os.getpid()), encoding="utf-8")

    daemon._check_inactivity_watchdog(tmp_path, state_dir, _config())

    assert not _marker_path(state_dir).exists(), (
        "watchdog FALSELY fired (marker written) while a live worker pid "
        "exists and elapsed time is within the worst-case single-task wall"
    )
    assert calls == [], (
        "watchdog FALSELY escalated daemon_inactivity_stuck while a live "
        "worker pid exists"
    )


# ---------------------------------------------------------------------------
# (1b) NO-FALSE-FIRE: no live worker, but elapsed is within the config-derived
# worst-case single-task wall (verification_timeout + timeout ~= 3000s).
# ---------------------------------------------------------------------------
def test_watchdog_does_not_fire_within_worstcase_wall(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    now = 1_000_000.0
    calls = _install_common_monkeypatches(monkeypatch, state_dir, now)

    # 2500s since last event: above legacy 1200, but below the ~3000s
    # worst-case single-task wall a normal long run can occupy with no event.
    _write_event_ledger(state_dir, age_sec=2500.0, now=now)

    daemon._check_inactivity_watchdog(tmp_path, state_dir, _config())

    assert not _marker_path(state_dir).exists(), (
        "watchdog FALSELY fired at 2500s, which is within the config-derived "
        "worst-case single-task wall (~3000s)"
    )
    assert calls == [], "watchdog FALSELY escalated within the worst-case wall"


# ---------------------------------------------------------------------------
# (2) POSITIVE CONTROL: genuinely idle -> still fires.
# ---------------------------------------------------------------------------
def test_watchdog_fires_when_genuinely_idle(tmp_path, monkeypatch):
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    now = 1_000_000.0
    calls = _install_common_monkeypatches(monkeypatch, state_dir, now)

    # No live worker pidfile, and last event 4000s ago -> beyond any
    # reasonable worst-case wall. This must still fire.
    _write_event_ledger(state_dir, age_sec=4000.0, now=now)

    daemon._check_inactivity_watchdog(tmp_path, state_dir, _config())

    assert _marker_path(state_dir).exists(), (
        "watchdog failed to fire when genuinely idle (no live worker, "
        "elapsed beyond worst-case wall)"
    )
    assert len(calls) == 1, "watchdog should escalate exactly once when idle"
