"""P4 invariant: planner reconciliation canonical path (HOOK-43).

Sub-plan 04 §3.6: ``collect_reconciliation_response`` must read only the
canonical path. Under HOOK-41, both the MCP proxy and the hook RPC
module (``harness.hooks.rpc.submit_reconciliation.persist``) write to
``{JANUSMASK_STATE_DIR}/planning/sessions/{agent}_reconciliation.json``;
with ``_ReconciliationConfig`` dynamically returning the per-agent
directory as ``state_dir`` during spawn, this resolves to
``{state_dir}/planning/sessions/{agent}/planning/sessions/{agent}_reconciliation.json``
— the single canonical location.  The legacy root-level fallback is
removed.

Probe strategy: use the tiebreaker mock as a sentinel.  If both stances
are ``defend``, the tiebreaker is invoked.  Stances default to
``concede`` when the reconciliation file is missing/unparseable; in
that case the tiebreaker is NOT invoked.  So planting ``defend/defend``
at the legacy path only, and asserting the tiebreaker was never
called, proves the legacy fallback is no longer consulted.
"""

from __future__ import annotations

import json
import pathlib
import sys
import types
from typing import Any, Dict
from unittest.mock import MagicMock

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[3]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

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


def _write_canonical(state_dir: pathlib.Path, agent: str, payload: Dict[str, Any]) -> None:
    """Canonical path #1: {state_dir}/planning/sessions/{agent}/planning/sessions/{agent}_reconciliation.json"""
    recon_file = (
        state_dir / "planning" / "sessions" / agent / "planning" / "sessions"
        / f"{agent}_reconciliation.json"
    )
    recon_file.parent.mkdir(parents=True, exist_ok=True)
    recon_file.write_text(json.dumps(payload), encoding="utf-8")


def _write_legacy_fallback(state_dir: pathlib.Path, agent: str, payload: Dict[str, Any]) -> None:
    """Legacy path #2: {state_dir}/planning/sessions/{agent}_reconciliation.json"""
    recon_file = state_dir / "planning" / "sessions" / f"{agent}_reconciliation.json"
    recon_file.parent.mkdir(parents=True, exist_ok=True)
    recon_file.write_text(json.dumps(payload), encoding="utf-8")


def test_canonical_defend_defend_invokes_tiebreaker(state_dir, mock_run_both, mock_tiebreaker):
    """Plant defend/defend at the canonical path — tiebreaker is invoked."""
    item = _make_diff_item("T1")
    _write_canonical(state_dir, "claude", {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "defend"}]
    })
    _write_canonical(state_dir, "gemini", {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "defend"}]
    })

    recon_mod.run_reconciliation(PlanDiff(items=(item,)), {}, {}, {}, state_dir)
    mock_tiebreaker.assert_called_once()


def test_legacy_fallback_not_read_post_hook43(state_dir, mock_run_both, mock_tiebreaker):
    """Plant defend/defend ONLY at the legacy fallback path.  Pre-HOOK-43
    the shim would have picked it up and invoked the tiebreaker; post
    HOOK-43 the stances fall back to the ``concede`` default, and the
    tiebreaker is never called."""
    item = _make_diff_item("T1")
    _write_legacy_fallback(state_dir, "claude", {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "defend"}]
    })
    _write_legacy_fallback(state_dir, "gemini", {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "defend"}]
    })

    recon_mod.run_reconciliation(PlanDiff(items=(item,)), {}, {}, {}, state_dir)
    mock_tiebreaker.assert_not_called()


def test_canonical_wins_when_both_paths_populated(state_dir, mock_run_both, mock_tiebreaker):
    """Canonical says ``defend`` for both; legacy plants ``concede`` for
    both.  If the shim still read the legacy path, both concedes would
    short-circuit before the tiebreaker.  Post HOOK-43, only the
    canonical is consulted, so the tiebreaker fires."""
    item = _make_diff_item("T1")
    _write_canonical(state_dir, "claude", {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "defend"}]
    })
    _write_canonical(state_dir, "gemini", {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "defend"}]
    })
    _write_legacy_fallback(state_dir, "claude", {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "concede"}]
    })
    _write_legacy_fallback(state_dir, "gemini", {
        "responses": [{"diff_item_id": item.diff_item_id, "stance": "concede"}]
    })

    recon_mod.run_reconciliation(PlanDiff(items=(item,)), {}, {}, {}, state_dir)
    mock_tiebreaker.assert_called_once()


def test_rpc_persist_target_matches_canonical_subpath():
    """The hook rpc module writes under ``planning/sessions/`` relative
    to state_dir; combined with ``_ReconciliationConfig``'s per-agent
    state_dir that matches the canonical reader path."""
    from harness.hooks.rpc import submit_reconciliation as rpc_mod  # noqa: WPS433

    source = pathlib.Path(rpc_mod.__file__).read_text(encoding="utf-8")
    assert '"planning" / "sessions"' in source
    assert 'f"{agent}_reconciliation.json"' in source


def test_fallback_code_removed():
    """Static check: the legacy 'Fallback to root sessions dir' code path
    is gone. Guards against careless reverts that would re-introduce
    silent dual-path reads. Post-META-PLAN-OUTBOX-FALLBACK (6043333),
    the function gains a SECOND recon_file assignment at line 213 for
    the workspace-outbox lookup (when permission-mode drops --settings
    and the canonical path isn't writable). The 2nd assignment is
    explicitly authorized — it's NOT the legacy fallback.
    """
    recon_src = pathlib.Path(recon_mod.__file__).read_text(encoding="utf-8")
    assert "Fallback to root sessions dir" not in recon_src
    body = recon_src.split("def collect_reconciliation_response")[1].split("return stances")[0]
    # 1 canonical assignment (line 201) + 1 outbox-fallback assignment (line 213).
    assert body.count("recon_file =") == 2
