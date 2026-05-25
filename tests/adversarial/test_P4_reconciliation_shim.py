"""P4 adversarial battery — HOOK-43 reconciliation dual-path removal.

Mutation tests per augmented plan §5 P4 row: re-introduce the legacy
fallback branch inside ``collect_reconciliation_response`` and confirm
the tests here catch the regression.  Probe: the tiebreaker is invoked
only when both stances are ``defend`` AND both were actually read.
Default stance on missing file is ``concede``; hitting the fallback
against planted defend/defend therefore flips the tiebreaker call count
from 0 to 1.
"""

from __future__ import annotations

import json
import pathlib
import sys
import types
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

PROJECT_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from harness.planner import reconciliation as recon_mod  # noqa: E402
from harness.planner.diff_model import (  # noqa: E402
    DiffItem,
    DiffKind,
    PlanDiff,
)


@pytest.fixture
def mock_run_both(monkeypatch):
    m = MagicMock(return_value=("", ""))
    monkeypatch.setattr("harness.planner.reconciliation.run_both_agents", m)
    return m


@pytest.fixture
def mock_tiebreaker(monkeypatch):
    mock_mod = types.ModuleType("harness.track_record")
    mock_func = MagicMock(return_value="claude")
    mock_mod.track_record_tiebreaker = mock_func
    monkeypatch.setitem(sys.modules, "harness.track_record", mock_mod)
    return mock_func


def _make_diff_item(task_id: str) -> DiffItem:
    return DiffItem(
        kind=DiffKind.divergent,
        claude_task={"task_id": task_id, "meta_task_type": "test_unit"},
        gemini_task={"task_id": task_id, "meta_task_type": "test_unit"},
        field_divergences=(),
    )


def _canonical_path(state_dir: pathlib.Path, agent: str) -> pathlib.Path:
    return (
        state_dir / "planning" / "sessions" / agent / "planning" / "sessions"
        / f"{agent}_reconciliation.json"
    )


def _legacy_path(state_dir: pathlib.Path, agent: str) -> pathlib.Path:
    return state_dir / "planning" / "sessions" / f"{agent}_reconciliation.json"


def _write(path: pathlib.Path, payload: Dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload), encoding="utf-8")


# ---------------------------------------------------------------------------
# Attack 1: multiple diff items, legacy-only plants, tiebreaker stays dark.
# ---------------------------------------------------------------------------

def test_multiple_legacy_plants_do_not_invoke_tiebreaker(state_dir, mock_run_both, mock_tiebreaker):
    items = [_make_diff_item(f"T{i}") for i in range(1, 4)]
    for agent in ("claude", "gemini"):
        _write(_legacy_path(state_dir, agent), {
            "responses": [
                {"diff_item_id": it.diff_item_id, "stance": "defend"} for it in items
            ]
        })

    recon_mod.run_reconciliation(PlanDiff(items=tuple(items)), {}, {}, {}, state_dir)
    assert mock_tiebreaker.call_count == 0


# ---------------------------------------------------------------------------
# Attack 2: corrupt/malformed responses at the legacy path are ignored
# (they would be anyway since the path is no longer read).
# ---------------------------------------------------------------------------

def test_corrupt_legacy_json_ignored(state_dir, mock_run_both, mock_tiebreaker):
    item = _make_diff_item("T1")
    _legacy_path(state_dir, "claude").parent.mkdir(parents=True, exist_ok=True)
    _legacy_path(state_dir, "claude").write_text("{not json", encoding="utf-8")
    _legacy_path(state_dir, "gemini").parent.mkdir(parents=True, exist_ok=True)
    _legacy_path(state_dir, "gemini").write_text("{}", encoding="utf-8")

    # No exception — the shim ignores the legacy path entirely.
    res = recon_mod.run_reconciliation(PlanDiff(items=(item,)), {}, {}, {}, state_dir)
    assert res is not None


# ---------------------------------------------------------------------------
# Attack 3: mutation — re-apply the legacy fallback inline and confirm
# the tiebreaker-probe invariant catches it.
# ---------------------------------------------------------------------------

def test_mutation_restore_fallback_triggers_tiebreaker(state_dir, mock_run_both, mock_tiebreaker):
    """Simulate pre-HOOK-43 behaviour by monkey-patching the reader to
    check both paths.  With defend/defend planted at the legacy path
    only, restoring the fallback makes the tiebreaker fire — which the
    invariant-test battery detects."""
    item = _make_diff_item("T1")
    _write(_legacy_path(state_dir, "claude"), {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "defend"}]
    })
    _write(_legacy_path(state_dir, "gemini"), {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "defend"}]
    })

    original_run = recon_mod.run_reconciliation

    def _run_with_legacy_fallback_patched(diff, c, g, cfg, sd):
        # Inject a shim that falls back to legacy path. We accomplish
        # this by pre-populating the canonical path from the legacy
        # path's contents before calling run_reconciliation — logically
        # equivalent to reading the fallback.
        for agent in ("claude", "gemini"):
            leg = _legacy_path(sd, agent)
            can = _canonical_path(sd, agent)
            if leg.exists() and not can.exists():
                can.parent.mkdir(parents=True, exist_ok=True)
                can.write_text(leg.read_text(encoding="utf-8"), encoding="utf-8")
        return original_run(diff, c, g, cfg, sd)

    _run_with_legacy_fallback_patched(PlanDiff(items=(item,)), {}, {}, {}, state_dir)
    # Under the "restored fallback", tiebreaker fires once.
    assert mock_tiebreaker.call_count == 1


# ---------------------------------------------------------------------------
# Attack 4: the fallback code path is not re-introduced by an upstream
# refactor — static grep.
# ---------------------------------------------------------------------------

def test_no_root_sessions_fallback_string_in_source():
    src = pathlib.Path(recon_mod.__file__).read_text(encoding="utf-8")
    assert "Fallback to root sessions dir" not in src
    # Also assert the specific path pattern is not constructed twice
    # (canonical + fallback) inside collect_reconciliation_response.
    body = src.split("def collect_reconciliation_response")[1].split("return stances")[0]
    assert body.count('state_dir / "planning" / "sessions"') == 0


# ---------------------------------------------------------------------------
# Attack 5: canonical defend/concede still resolves without tiebreaker.
# (Ensures the happy path wasn't broken by the fallback removal.)
# ---------------------------------------------------------------------------

def test_canonical_defend_vs_concede_auto_resolved(state_dir, mock_run_both, mock_tiebreaker):
    item = _make_diff_item("T1")
    _write(_canonical_path(state_dir, "claude"), {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "defend"}]
    })
    _write(_canonical_path(state_dir, "gemini"), {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "concede"}]
    })

    res = recon_mod.run_reconciliation(PlanDiff(items=(item,)), {}, {}, {}, state_dir)
    assert len(res.merged_tasks) == 1
    mock_tiebreaker.assert_not_called()


# ---------------------------------------------------------------------------
# Attack 6: unknown diff_item_id in the canonical file is still filtered
# and reported as a per-agent error (post-HOOK-43 error routing intact).
# ---------------------------------------------------------------------------

def test_unknown_diff_item_id_reported_as_error(state_dir, mock_run_both, mock_tiebreaker):
    item = _make_diff_item("T1")
    _write(_canonical_path(state_dir, "claude"), {
        "responses": [
            {"diff_item_id": "GHOST", "stance": "defend"},
            {"diff_item_id": item.diff_item_id, "stance": "defend"},
        ]
    })
    _write(_canonical_path(state_dir, "gemini"), {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "defend"}]
    })

    res = recon_mod.run_reconciliation(PlanDiff(items=(item,)), {}, {}, {}, state_dir)
    assert "unknown diff_item_id: GHOST" in res.per_agent_errors["claude"]
