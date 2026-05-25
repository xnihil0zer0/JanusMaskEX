"""Adversarial regression bar for AW11 — _auto_promote guards (R-PROMOTE-1).

Background: ``harness/autowork_daemon.py:_auto_promote`` (session #17 sha
872dd97) enumerates ALL briefs returned by ``compute_brief_status`` and
stages their ``unstaged_task_ids`` with NO staleness filter, NO allowlist,
and NO kill-switch. A daemon restart against the current repo state would
flood the queue with 21+ tasks across 6 abandoned/stale briefs.

This test pins three contracts AW11 is required to satisfy:

1. ``state/control/autowork/auto_promote.disabled`` short-circuits
   ``_auto_promote`` immediately (zero extracts, zero plan_kickoffs, zero
   discards, zero ledger rows).
2. Briefs older than ``DEFAULT_BRIEF_MAX_AGE_SEC`` (7 days, hard-coded
   constant) are skipped in the extract phase regardless of plan validity.
3. When ``state/control/autowork/auto_promote.allowlist`` exists, only
   briefs whose slug appears in the file are processed; others are skipped
   even when their plans are fresh and well-formed.

Pattern mirrors session #14 G27/G28 and session #17 AW9c: META commit lands
the test with ``xfail(strict=False, reason=...)``. AW11's
verification_command runs pytest with ``--runxfail`` so the markers are
bypassed at gate time; the post-AW11 META commit drops the markers and the
tests pass naturally.
"""
from __future__ import annotations

import json
import os
import pathlib
import time

import pytest


@pytest.fixture
def repo_state(tmp_path: pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    """Return ``(repo_root, state_dir)`` with the minimum directory shape
    ``compute_brief_status`` + ``_auto_promote`` expect."""
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    (state_dir / "tasks").mkdir(parents=True)
    (state_dir / "tasks" / "processed").mkdir()
    (state_dir / "tasks" / "blocked").mkdir()
    (state_dir / "control" / "autowork").mkdir(parents=True)
    return repo_root, state_dir


def _ledger_rows(state_dir: pathlib.Path) -> list[dict]:
    p = state_dir / "impl_progress.jsonl"
    if not p.exists():
        return []
    out: list[dict] = []
    for line in p.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


@pytest.mark.xfail(
    strict=False,
    reason="AW11 not landed: _auto_promote has no kill-switch. Drops post-AW11.",
)
def test_disable_flag_short_circuits(
    repo_state: tuple[pathlib.Path, pathlib.Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``auto_promote.disabled`` flag must zero-out the entire pass."""
    repo_root, state_dir = repo_state

    (repo_root / "brief_hooks_demo_disable.md").write_text(
        "# disable demo\n", encoding="utf-8"
    )
    plan = {"tasks": [{"task_id": "DEMO_DISABLE_TASK", "files_touched": ["x.py"]}]}
    (repo_root / "plan_hooks_demo_disable.json").write_text(
        json.dumps(plan), encoding="utf-8"
    )

    (state_dir / "control" / "autowork" / "auto_promote.disabled").write_text("")

    monkeypatch.chdir(repo_root)
    from harness.autowork_daemon import _auto_promote

    summary = _auto_promote(repo_root, state_dir)

    assert summary == {
        "extracts": 0,
        "plan_kickoffs": 0,
        "discarded": 0,
    }, f"AW11: disable flag must zero all counters, got {summary!r}"

    assert not (state_dir / "tasks" / "DEMO_DISABLE_TASK.json").exists(), (
        "AW11: disable flag must prevent any extract from happening"
    )

    rows = _ledger_rows(state_dir)
    bad = [r for r in rows if r.get("event") in {"extract", "plan_kickoff", "planner_hallucination_discarded"}]
    assert not bad, (
        f"AW11: disable flag must suppress all auto_promote ledger rows, got {bad!r}"
    )


@pytest.mark.xfail(
    strict=False,
    reason="AW11 not landed: _auto_promote has no brief_mtime staleness filter. Drops post-AW11.",
)
def test_stale_brief_skipped(
    repo_state: tuple[pathlib.Path, pathlib.Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Briefs older than DEFAULT_BRIEF_MAX_AGE_SEC must be skipped."""
    repo_root, state_dir = repo_state

    brief = repo_root / "brief_hooks_demo_stale.md"
    brief.write_text("# stale demo\n", encoding="utf-8")

    plan = {"tasks": [{"task_id": "DEMO_STALE_TASK", "files_touched": ["y.py"]}]}
    plan_path = repo_root / "plan_hooks_demo_stale.json"
    plan_path.write_text(json.dumps(plan), encoding="utf-8")

    old_ts = time.time() - 30 * 86400  # 30 days ago
    os.utime(brief, (old_ts, old_ts))

    monkeypatch.chdir(repo_root)
    from harness.autowork_daemon import _auto_promote

    _auto_promote(repo_root, state_dir)

    assert not (state_dir / "tasks" / "DEMO_STALE_TASK.json").exists(), (
        "AW11: 30-day-stale brief must NOT have its task staged"
    )

    extract_rows = [
        r for r in _ledger_rows(state_dir) if r.get("event") == "extract"
    ]
    assert not any(
        r.get("task_id") == "DEMO_STALE_TASK" for r in extract_rows
    ), "AW11: no extract row should be emitted for a stale brief"


@pytest.mark.xfail(
    strict=False,
    reason="AW11 not landed: _auto_promote has no allowlist scoping. Drops post-AW11.",
)
def test_allowlist_restricts_processing(
    repo_state: tuple[pathlib.Path, pathlib.Path],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``auto_promote.allowlist`` restricts processing to listed slugs."""
    repo_root, state_dir = repo_state

    (repo_root / "brief_hooks_demo_included.md").write_text(
        "# included\n", encoding="utf-8"
    )
    (repo_root / "plan_hooks_demo_included.json").write_text(
        json.dumps({"tasks": [{"task_id": "INCLUDED_TASK", "files_touched": ["a.py"]}]}),
        encoding="utf-8",
    )

    (repo_root / "brief_hooks_demo_excluded.md").write_text(
        "# excluded\n", encoding="utf-8"
    )
    (repo_root / "plan_hooks_demo_excluded.json").write_text(
        json.dumps({"tasks": [{"task_id": "EXCLUDED_TASK", "files_touched": ["b.py"]}]}),
        encoding="utf-8",
    )

    (state_dir / "control" / "autowork" / "auto_promote.allowlist").write_text(
        "# allow only the included demo\ndemo_included\n", encoding="utf-8"
    )

    monkeypatch.chdir(repo_root)
    from harness.autowork_daemon import _auto_promote

    _auto_promote(repo_root, state_dir)

    assert (state_dir / "tasks" / "INCLUDED_TASK.json").exists(), (
        "AW11: allowlisted brief's task MUST be staged"
    )
    assert not (state_dir / "tasks" / "EXCLUDED_TASK.json").exists(), (
        "AW11: non-allowlisted brief's task MUST NOT be staged"
    )
