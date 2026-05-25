"""Adversarial coverage for scripts/impl_context_emit.py per HH5 / W72 / W72b.

These tests exercise the `Active scope_exception paths` banner emitted by
``impl_context_emit.emit``. Per HH5 design, each path in the banner is
annotated with a status tag derived from the ledger:

- ``(active)``   SE row within 14 days AND no matching test_pass row AND path exists
- ``(consumed)`` a test_pass row exists for the same task_id after the SE row
- ``(missing)``  SE-listed path does not exist on disk (W72b); overrides
                 active/stale, but loses to consumed/revoked
- ``(stale)``    SE row older than 14 days AND no matching test_pass row AND path exists
- ``(revoked)``  pre-existing markup, preserved as-is

Each test seeds its own temporary ledger under ``tmp_path`` and drives the
emitter via monkeypatched ``LEDGER_PATH`` + ``load_ledger``. The real
``state/impl_progress.jsonl`` is NEVER mutated.

Test path conventions (W72b): tests that expect ``(active)``, ``(stale)``,
or any other "exists" tag MUST use a real existing path under the repo
(e.g. ``scripts/impl_pre_write.py``). Tests covering the W72b ``(missing)``
tag use synthetic, guaranteed-absent paths (``harness/never_existed_*``).
"""

from __future__ import annotations

import datetime
import importlib
import importlib.util
import io
import json
import pathlib
import sys

import pytest


REPO = pathlib.Path(__file__).resolve().parents[2]
SCRIPTS = REPO / "scripts"


def _load_emit_module():
    """Load ``impl_context_emit`` under a private name so monkeypatching
    does not leak across tests."""
    if str(SCRIPTS) not in sys.path:
        sys.path.insert(0, str(SCRIPTS))
    spec = importlib.util.spec_from_file_location(
        "impl_context_emit_under_test", SCRIPTS / "impl_context_emit.py"
    )
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def emit_module():
    return _load_emit_module()


def _iso(dt: datetime.datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _now() -> datetime.datetime:
    return datetime.datetime.now(datetime.timezone.utc)


def _write_ledger(path: pathlib.Path, rows: list[dict]) -> None:
    path.write_text(
        "\n".join(json.dumps(r) for r in rows) + ("\n" if rows else ""),
        encoding="utf-8",
    )


def _se_row(
    *,
    paths: list[str],
    task_id: str,
    days_ago: float = 0.0,
    approved_by: str = "human",
) -> dict:
    ts = _now() - datetime.timedelta(days=days_ago)
    return {
        "ts": _iso(ts),
        "phase": "META",
        "task_id": task_id,
        "event": "scope_exception",
        "detail": f"auth {paths}",
        "paths": list(paths),
        "approved_by": approved_by,
        "consume_on": "test_pass",
        "files": [],
        "exit": 0,
    }


def _pass_row(*, task_id: str, days_ago: float = 0.0) -> dict:
    ts = _now() - datetime.timedelta(days=days_ago)
    return {
        "ts": _iso(ts),
        "phase": "META",
        "task_id": task_id,
        "event": "test_pass",
        "detail": "all green",
        "files": [],
        "exit": 0,
    }


def _revoke_row(*, paths: list[str], task_id: str, days_ago: float = 0.0) -> dict:
    ts = _now() - datetime.timedelta(days=days_ago)
    return {
        "ts": _iso(ts),
        "phase": "META",
        "task_id": task_id,
        "event": "scope_revoke",
        "detail": f"revoke {paths}",
        "paths": list(paths),
        "files": [],
        "exit": 0,
    }


def _capture_emit(emit_module, tmp_path, rows, monkeypatch) -> str:
    """Write ``rows`` to a temp ledger, patch LEDGER_PATH, run emit, return stdout."""
    ledger_path = tmp_path / "impl_progress.jsonl"
    _write_ledger(ledger_path, rows)

    # Patch ledger resolution inside the emit module's imported symbols.
    monkeypatch.setattr(emit_module, "LEDGER_PATH", ledger_path)

    # load_ledger was imported by name; patch its behavior to read our file.
    import impl_common

    original_load = impl_common.load_ledger

    def _load(path=None):
        return original_load(ledger_path)

    monkeypatch.setattr(emit_module, "load_ledger", _load)
    monkeypatch.setattr(impl_common, "LEDGER_PATH", ledger_path)

    # Also stub out _git_head so tests are hermetic.
    monkeypatch.setattr(emit_module, "_git_head", lambda: "deadbeef" * 5)

    buf = io.StringIO()
    monkeypatch.setattr(sys, "stdout", buf)
    try:
        emit_module.emit("prompt")
    finally:
        sys.stdout = sys.__stdout__
    return buf.getvalue()


# ----------------------------------------------------------------- test cases


def test_empty_ledger_banner_absent_or_empty(emit_module, tmp_path, monkeypatch):
    """(a) With no SE rows, either no banner line or an empty-ish list is fine;
    crucially no exception and no annotations."""
    out = _capture_emit(emit_module, tmp_path, [], monkeypatch)
    # No scope_exception row means scope_exception_paths returns [] so the
    # banner line is suppressed (existing behavior). Must not appear.
    assert "Active scope_exception paths" not in out


# Real paths under the repo, used as "exists" sentinels by tests that exercise
# tags other than (missing). Picked from stable script/harness modules so
# that future renames are unlikely to break these tests silently.
_EXISTS_A = "scripts/impl_pre_write.py"
_EXISTS_B = "scripts/impl_common.py"
_EXISTS_C = "harness/orchestrator.py"
_EXISTS_D = "scripts/impl_context_emit.py"
_EXISTS_E = "scripts/impl_post_write.py"

# Synthetic absolutely-not-existing path for W72b (missing) coverage.
_MISSING_A = "harness/never_existed_xyz_12345.py"
_MISSING_B = "harness/also_never_existed_abc_67890.py"


def test_consumed_tag_when_test_pass_follows_se(emit_module, tmp_path, monkeypatch):
    """(b) SE row + later test_pass for same task_id -> (consumed)."""
    rows = [
        _se_row(paths=[_EXISTS_A], task_id="T-CONSUMED", days_ago=1.0),
        _pass_row(task_id="T-CONSUMED", days_ago=0.5),
    ]
    out = _capture_emit(emit_module, tmp_path, rows, monkeypatch)
    assert "Active scope_exception paths" in out
    assert f"{_EXISTS_A} (consumed)" in out


def test_active_tag_when_recent_se_and_no_pass(emit_module, tmp_path, monkeypatch):
    """(c) Recent SE row (<=14d) with no test_pass -> (active)."""
    rows = [_se_row(paths=[_EXISTS_A], task_id="T-ACTIVE", days_ago=3.0)]
    out = _capture_emit(emit_module, tmp_path, rows, monkeypatch)
    assert f"{_EXISTS_A} (active)" in out


def test_stale_tag_when_old_se_and_no_pass(emit_module, tmp_path, monkeypatch):
    """(d) SE row older than 14d with no test_pass on an existing path -> (stale)."""
    rows = [_se_row(paths=[_EXISTS_B], task_id="T-STALE", days_ago=20.0)]
    out = _capture_emit(emit_module, tmp_path, rows, monkeypatch)
    assert f"{_EXISTS_B} (stale)" in out
    # Must NOT be silently dropped for auditability.
    assert _EXISTS_B in out


def test_duplicate_paths_deduped_same_status(emit_module, tmp_path, monkeypatch):
    """(e) Same path authorised twice by distinct SE rows should appear once
    in the banner when status is identical."""
    rows = [
        _se_row(paths=[_EXISTS_C], task_id="T-DUP-1", days_ago=2.0),
        _se_row(paths=[_EXISTS_C], task_id="T-DUP-2", days_ago=1.0),
    ]
    out = _capture_emit(emit_module, tmp_path, rows, monkeypatch)
    # Both entries are (active) since neither task has a test_pass and the
    # path exists on disk.
    assert out.count(f"{_EXISTS_C} (active)") == 1
    # Should not appear as a bare, unannotated entry.
    assert f"'{_EXISTS_C}'," not in out and f"'{_EXISTS_C}']" not in out


def test_revoked_tag_preserved(emit_module, tmp_path, monkeypatch):
    """(f) scope_revoke row must still win and show (revoked) tag."""
    rows = [
        _se_row(paths=[_EXISTS_A], task_id="T-REV", days_ago=1.0),
        _revoke_row(paths=[_EXISTS_A], task_id="T-REV", days_ago=0.5),
    ]
    out = _capture_emit(emit_module, tmp_path, rows, monkeypatch)
    assert f"{_EXISTS_A} (revoked)" in out
    # Revoked wins over status tags; no double annotation.
    assert f"{_EXISTS_A} (active)" not in out
    assert f"{_EXISTS_A} (stale)" not in out
    assert f"{_EXISTS_A} (consumed)" not in out
    assert f"{_EXISTS_A} (missing)" not in out


def test_mixed_statuses_all_present_in_order(emit_module, tmp_path, monkeypatch):
    """Bonus: mixed statuses are all emitted (auditability guarantee)."""
    rows = [
        _se_row(paths=[_EXISTS_A], task_id="T-A", days_ago=2.0),
        _se_row(paths=[_EXISTS_B], task_id="T-B", days_ago=2.0),
        _pass_row(task_id="T-B", days_ago=1.0),
        _se_row(paths=[_EXISTS_C], task_id="T-C", days_ago=30.0),
    ]
    out = _capture_emit(emit_module, tmp_path, rows, monkeypatch)
    assert f"{_EXISTS_A} (active)" in out
    assert f"{_EXISTS_B} (consumed)" in out
    assert f"{_EXISTS_C} (stale)" in out


def test_consumed_requires_pass_after_se(emit_module, tmp_path, monkeypatch):
    """Edge: a test_pass row that predates the SE must NOT mark it consumed."""
    rows = [
        _pass_row(task_id="T-EARLY", days_ago=5.0),
        _se_row(paths=[_EXISTS_D], task_id="T-EARLY", days_ago=1.0),
    ]
    out = _capture_emit(emit_module, tmp_path, rows, monkeypatch)
    assert f"{_EXISTS_D} (active)" in out
    assert f"{_EXISTS_D} (consumed)" not in out


# ----------------------------------------------------------- W72b (missing) tag


def test_missing_tag_when_path_does_not_exist(emit_module, tmp_path, monkeypatch):
    """W72b: SE-listed path that doesn't exist on disk -> (missing).

    Recent SE row, no test_pass, path absent from working tree. Without W72b
    this would have been tagged (active), masking the fact that the writer
    never landed (or the file was retired). The (missing) tag surfaces it.
    """
    rows = [_se_row(paths=[_MISSING_A], task_id="T-MISS", days_ago=1.0)]
    out = _capture_emit(emit_module, tmp_path, rows, monkeypatch)
    assert f"{_MISSING_A} (missing)" in out
    assert f"{_MISSING_A} (active)" not in out


def test_missing_overrides_stale(emit_module, tmp_path, monkeypatch):
    """W72b: SE row >14d old AND path absent -> (missing), not (stale).

    Both predicates match; (missing) is more actionable because it says
    "the artifact never landed" rather than "the artifact landed and was
    forgotten". Surface the existence problem first.
    """
    rows = [_se_row(paths=[_MISSING_B], task_id="T-MISS-STALE", days_ago=21.0)]
    out = _capture_emit(emit_module, tmp_path, rows, monkeypatch)
    assert f"{_MISSING_B} (missing)" in out
    assert f"{_MISSING_B} (stale)" not in out


def test_missing_loses_to_consumed(emit_module, tmp_path, monkeypatch):
    """W72b: SE row + test_pass for same task_id, even on an absent path,
    must keep (consumed). The work was completed; the file may have been
    moved or renamed afterward, but the audit story is "done", not "TODO"."""
    rows = [
        _se_row(paths=[_MISSING_A], task_id="T-MISS-CONS", days_ago=1.0),
        _pass_row(task_id="T-MISS-CONS", days_ago=0.5),
    ]
    out = _capture_emit(emit_module, tmp_path, rows, monkeypatch)
    assert f"{_MISSING_A} (consumed)" in out
    assert f"{_MISSING_A} (missing)" not in out


def test_existing_path_keeps_existing_tag(emit_module, tmp_path, monkeypatch):
    """W72b regression: paths that DO exist on disk must keep their W72
    (active)/(consumed)/(stale) tag — they must NEVER be tagged (missing)."""
    rows = [
        _se_row(paths=[_EXISTS_A], task_id="T-REG-A", days_ago=2.0),
        _se_row(paths=[_EXISTS_B], task_id="T-REG-B", days_ago=2.0),
        _pass_row(task_id="T-REG-B", days_ago=1.0),
        _se_row(paths=[_EXISTS_E], task_id="T-REG-E", days_ago=30.0),
    ]
    out = _capture_emit(emit_module, tmp_path, rows, monkeypatch)
    assert f"{_EXISTS_A} (active)" in out
    assert f"{_EXISTS_B} (consumed)" in out
    assert f"{_EXISTS_E} (stale)" in out
    # None of the existing paths should be tagged (missing).
    assert f"{_EXISTS_A} (missing)" not in out
    assert f"{_EXISTS_B} (missing)" not in out
    assert f"{_EXISTS_E} (missing)" not in out
