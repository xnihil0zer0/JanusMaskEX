"""Adversarial regression bar for R-PROMOTE-3.

Bug: ``harness.autowork_daemon._run_planner_subprocess`` discards
``proc.stderr`` even though ``capture_output=True`` is set on the
``subprocess.run`` call. Failed planner runs emit
``planner_hallucination_discarded`` rows with ``wall=X reason=Y`` and no
clue about the subprocess error. Becomes load-bearing as backlog burndown
drives many planner runs per session.

Fix shape (this brief):
- Widen ``_run_planner_subprocess`` return from ``(rc, wall)`` to
  ``(rc, wall, stderr_tail)`` where stderr_tail is the last 512 bytes
  decoded utf-8 errors='replace'.
- ``_auto_promote`` appends the (truncated/escaped) stderr_tail to the
  ``planner_hallucination_discarded`` telemetry detail string.

The two xfail markers in this file are dropped in a follow-up META commit
once the fix lands.
"""
from __future__ import annotations

import importlib
import json
import pathlib

import pytest


@pytest.fixture
def autowork(monkeypatch: pytest.MonkeyPatch):
    """Reload ``harness.autowork_daemon`` so the test sees the live
    on-disk module bytecode (not a stale import from a prior session).
    """
    import harness.autowork_daemon as ad
    importlib.reload(ad)
    return ad


def test_run_planner_subprocess_returns_three_tuple(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    autowork,
) -> None:
    """``_run_planner_subprocess`` must return a 3-tuple where the third
    element is the planner's stderr tail (str, last 512 bytes,
    utf-8 errors='replace').

    Validated by stubbing ``subprocess.Popen`` so the helper observes a
    sentinel stderr — the assertion is on the helper's return shape +
    third-element value. The production helper uses Popen + communicate()
    (NOT subprocess.run) so it can kill the planner's whole process group on
    timeout; the seam is therefore Popen, and that is what we stub here.
    """
    ad = autowork

    class _FakePopen:
        def __init__(self, *args, **kwargs):
            self.returncode = None

        def communicate(self, timeout=None):
            self.returncode = 1
            return (b"", b"STDERR_SENTINEL_RP3_PROPAGATE")

    monkeypatch.setattr(ad.subprocess, "Popen", _FakePopen)

    brief = tmp_path / "brief.md"
    brief.write_text("# Title\n", encoding="utf-8")
    plan = tmp_path / "plan.json"
    state = tmp_path / "state"
    state.mkdir()

    result = ad._run_planner_subprocess(brief, plan, state, timeout_sec=10.0)

    assert isinstance(result, tuple), f"expected tuple return, got {type(result).__name__}"
    assert len(result) == 3, (
        f"_run_planner_subprocess must return (rc, wall, stderr_tail); "
        f"got {len(result)}-tuple: {result!r}"
    )
    rc, wall, stderr_tail = result
    assert isinstance(rc, int), f"rc must be int, got {type(rc).__name__}"
    assert isinstance(wall, float), f"wall must be float, got {type(wall).__name__}"
    assert isinstance(stderr_tail, str), (
        f"stderr_tail must be str, got {type(stderr_tail).__name__}"
    )
    assert "STDERR_SENTINEL_RP3_PROPAGATE" in stderr_tail, (
        f"stderr_tail did not capture the subprocess stderr sentinel; "
        f"got {stderr_tail!r}"
    )


def test_planner_hallucination_discarded_detail_contains_stderr_tail(
    tmp_path: pathlib.Path,
    monkeypatch: pytest.MonkeyPatch,
    autowork,
) -> None:
    """When ``_auto_promote`` rejects a hallucinated planner output, the
    ``planner_hallucination_discarded`` ledger row's ``detail`` field must
    contain the captured stderr tail so the operator can diagnose why the
    planner failed.
    """
    ad = autowork

    # Stub _run_planner_subprocess to return a hallucinated-fast result
    # plus a stderr sentinel. The 3-tuple shape pre-supposes the fix has
    # landed; xfail covers the pre-fix state where this monkeypatch will
    # cause a tuple-unpack error inside _auto_promote.
    def _fake_planner(brief_path, output_plan, state_dir, timeout_sec=300.0):
        return (1, 0.5, "STDERR_SENTINEL_HALLUCINATED_RP3")

    monkeypatch.setattr(ad, "_run_planner_subprocess", _fake_planner)

    # Build a minimal repo + state layout that compute_brief_status will
    # pick up an unplanned brief from.
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = repo_root / "state"
    (state_dir / "tasks").mkdir(parents=True)
    (state_dir / "control" / "autowork").mkdir(parents=True)
    # REPL-1/G-EMPTYALLOW: a missing allowlist is now deny-all, so the unplanned
    # brief must be explicitly allowlisted for _auto_promote to kick off the planner.
    (state_dir / "control" / "autowork" / "auto_promote.allowlist").write_text(
        "rp3_sentinel\n", encoding="utf-8"
    )

    brief_path = repo_root / "brief_hooks_rp3_sentinel.md"
    brief_path.write_text(
        "---\ntitle: RP3 sentinel\n---\n\n"
        "# Title\nRP3 sentinel\n\n"
        "# Scope\nSentinel brief for RP3 adversarial test.\n\n"
        "# Non-goals\nNone.\n\n"
        "# Inputs\nNone.\n\n"
        "# Deliverables\nNone.\n",
        encoding="utf-8",
    )

    monkeypatch.chdir(repo_root)
    ad._auto_promote(repo_root, state_dir)

    ledger_path = state_dir / "impl_progress.jsonl"
    assert ledger_path.exists(), "ledger not written by _auto_promote"

    rows = []
    for line in ledger_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue

    discarded = [r for r in rows if r.get("event") == "planner_hallucination_discarded"]
    assert discarded, (
        f"expected at least one planner_hallucination_discarded row; "
        f"got events: {[r.get('event') for r in rows]}"
    )
    detail = str(discarded[-1].get("detail", ""))
    assert "STDERR_SENTINEL_HALLUCINATED_RP3" in detail, (
        f"planner_hallucination_discarded detail missing stderr_tail; "
        f"got detail={detail!r}"
    )
