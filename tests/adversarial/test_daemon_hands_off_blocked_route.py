"""Adversarial bars for the daemon STRUCTURAL hands-off (session #28).

Guards three gaps that previously let an eligible-but-non-accepting task rot
silently instead of recovering on its own:

- **G-ZOMBIE-RT**: a NON-ACCEPT worker terminal (reject / no_diff /
  verification_failed / auto_commit_failed) used to park the task in
  ``state/tasks/processed/`` forever; ``compute_brief_status`` counts that as
  staged, so the daemon's ``_auto_promote`` never re-staged it. The worker now
  routes non-accept terminals through ``orchestrator._mark_blocked`` ->
  ``state/tasks/blocked/<id>.json`` + a ``{attempts,last_outcome,ts}`` retry
  sidecar, and emits a ``task_blocked`` ledger row.
- **G-BLOCKED**: real ``blocked/*.json`` tasks are now re-staged by
  ``autowork_daemon._retry_blocked_tasks`` under a retry budget + escalating
  backoff (300s -> 3600s -> 86400s), parking past budget with a
  ``retry_exhausted`` row.
- **G-ORPHAN**: a SIGKILL/OOM that leaves ``<id>.json.processing`` with no live
  worker is reclaimed to ``blocked/`` by
  ``autowork_daemon._reclaim_orphan_processing`` (guarded by the post-reap live
  set so an in-flight worker's claim is never stolen).

These are plain (non-xfail) regression guards: the behavior landed via reviewed
direct edit in session #28, so the bars assert the live wiring and behavior.
"""

from __future__ import annotations

import ast
import json
import pathlib
import time

from harness import autowork_daemon as d
from harness import orchestrator as orch

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]


def _fn(module_path: pathlib.Path, name: str) -> ast.FunctionDef:
    tree = ast.parse(module_path.read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"{module_path.name}:{name} not found (renamed/moved?)")


# --------------------------------------------------------------------------- #
# Structural wiring                                                            #
# --------------------------------------------------------------------------- #

def test_orchestrator_defines_mark_blocked_and_sidecar() -> None:
    orch_py = REPO_ROOT / "harness" / "orchestrator.py"
    names = {
        n.name
        for n in ast.walk(ast.parse(orch_py.read_text(encoding="utf-8")))
        if isinstance(n, ast.FunctionDef)
    }
    assert "_mark_blocked" in names, "orchestrator._mark_blocked missing"
    assert "_write_retry_sidecar" in names, "orchestrator._write_retry_sidecar missing"


def test_worker_routes_non_accept_terminals_to_mark_blocked() -> None:
    """The worker's non-accept terminals must call ``_mark_blocked``; the
    decompose terminal must stay on ``_mark_processed`` (a decomposed parent is
    genuinely done -- its children are enqueued)."""
    worker_py = REPO_ROOT / "harness" / "orchestrator_worker.py"
    src = worker_py.read_text(encoding="utf-8")
    blocked_calls = src.count("orch._mark_blocked(")
    # 6 pure-reject sites + 3 auto_commit_failed branches = 9.
    assert blocked_calls >= 8, (
        f"expected >= 8 _mark_blocked call sites in the worker, found {blocked_calls}"
    )
    # decompose still routes to processed/.
    assert "'reason': 'decomposed'" in src
    main_fn = _fn(worker_py, "main")
    body = ast.unparse(main_fn)
    assert "_mark_processed" in body, "decompose terminal must keep _mark_processed"


def test_daemon_defines_orphan_and_blocked_helpers() -> None:
    daemon_py = REPO_ROOT / "harness" / "autowork_daemon.py"
    names = {
        n.name
        for n in ast.walk(ast.parse(daemon_py.read_text(encoding="utf-8")))
        if isinstance(n, ast.FunctionDef)
    }
    for need in ("_reclaim_orphan_processing", "_retry_blocked_tasks", "_bump_blocked_sidecar"):
        assert need in names, f"autowork_daemon.{need} missing"


def test_iteration_calls_reclaim_and_auto_promote_calls_retry() -> None:
    daemon_py = REPO_ROOT / "harness" / "autowork_daemon.py"
    it_body = ast.unparse(_fn(daemon_py, "_iteration"))
    assert "_reclaim_orphan_processing" in it_body, (
        "_iteration must call _reclaim_orphan_processing after _reap_running"
    )
    ap_body = ast.unparse(_fn(daemon_py, "_auto_promote"))
    assert "_retry_blocked_tasks" in ap_body, (
        "_auto_promote must call _retry_blocked_tasks"
    )


# --------------------------------------------------------------------------- #
# Behavior                                                                     #
# --------------------------------------------------------------------------- #

def _mkstate(tmp_path: pathlib.Path) -> pathlib.Path:
    state = tmp_path / "state"
    (state / "tasks").mkdir(parents=True)
    return state


def test_mark_blocked_routes_non_accept_to_blocked_with_sidecar(tmp_path) -> None:
    state = _mkstate(tmp_path)
    tasks = state / "tasks"
    (tasks / "ZT.json.processing").write_text(json.dumps({"task_id": "ZT"}))
    orch._mark_blocked(state, "ZT", "smoke_failed")
    assert (tasks / "blocked" / "ZT.json").exists()
    assert not (tasks / "ZT.json.processing").exists()
    side = json.loads((tasks / "blocked" / "ZT.retry.json").read_text())
    assert side["attempts"] == 1 and side["last_outcome"] == "smoke_failed"
    # ledger carries a task_blocked row
    ledger = (state / "impl_progress.jsonl").read_text()
    assert "task_blocked" in ledger


def test_reclaim_orphan_routes_dead_processing_to_blocked(tmp_path) -> None:
    state = _mkstate(tmp_path)
    tasks = state / "tasks"
    (tasks / "ORPH.json.processing").write_text(json.dumps({"task_id": "ORPH"}))
    reclaimed = d._reclaim_orphan_processing(state, set())
    assert reclaimed == 1
    assert (tasks / "blocked" / "ORPH.json").exists()
    assert json.loads((tasks / "blocked" / "ORPH.retry.json").read_text())["last_outcome"] == "orphaned"


def test_reclaim_orphan_preserves_live_worker_claim(tmp_path) -> None:
    state = _mkstate(tmp_path)
    tasks = state / "tasks"
    (tasks / "LIVE.json.processing").write_text(json.dumps({"task_id": "LIVE"}))
    reclaimed = d._reclaim_orphan_processing(state, {"LIVE"})
    assert reclaimed == 0
    assert (tasks / "LIVE.json.processing").exists()
    assert not (tasks / "blocked" / "LIVE.json").exists()


def test_retry_blocked_restages_after_backoff(tmp_path) -> None:
    state = _mkstate(tmp_path)
    tasks = state / "tasks"
    blocked = tasks / "blocked"
    blocked.mkdir()
    (blocked / "RT.json").write_text(json.dumps({"task_id": "RT"}))
    (blocked / "RT.retry.json").write_text(
        json.dumps({"attempts": 1, "last_outcome": "rejected", "ts": time.time() - 9999})
    )
    restaged = d._retry_blocked_tasks(state, {"extracts": 0})
    assert restaged == 1
    assert (tasks / "RT.json").exists()
    assert not (blocked / "RT.json").exists()


def test_retry_blocked_holds_during_backoff_window(tmp_path) -> None:
    state = _mkstate(tmp_path)
    tasks = state / "tasks"
    blocked = tasks / "blocked"
    blocked.mkdir()
    (blocked / "HOLD.json").write_text(json.dumps({"task_id": "HOLD"}))
    (blocked / "HOLD.retry.json").write_text(
        json.dumps({"attempts": 1, "last_outcome": "rejected", "ts": time.time()})
    )
    restaged = d._retry_blocked_tasks(state, {"extracts": 0})
    assert restaged == 0
    assert not (tasks / "HOLD.json").exists()
    assert (blocked / "HOLD.json").exists()


def test_retry_blocked_parks_past_budget(tmp_path) -> None:
    state = _mkstate(tmp_path)
    tasks = state / "tasks"
    blocked = tasks / "blocked"
    blocked.mkdir()
    (blocked / "EX.json").write_text(json.dumps({"task_id": "EX"}))
    (blocked / "EX.retry.json").write_text(
        json.dumps({"attempts": 3, "last_outcome": "rejected", "ts": time.time() - 99999})
    )
    restaged = d._retry_blocked_tasks(state, {"extracts": 0})
    assert restaged == 0
    assert (blocked / "EX.json").exists()
    assert (blocked / "EX.exhausted").exists()
    assert "retry_exhausted" in (state / "impl_progress.jsonl").read_text()


def test_blocked_retry_sidecar_is_monotonic(tmp_path) -> None:
    """Re-blocking a task bumps attempts (read-modify-write), so the budget is
    monotonic across re-stage cycles."""
    state = _mkstate(tmp_path)
    a1 = d._bump_blocked_sidecar(state, "M", "rejected")
    a2 = d._bump_blocked_sidecar(state, "M", "smoke_failed")
    assert (a1, a2) == (1, 2)
    side = json.loads((state / "tasks" / "blocked" / "M.retry.json").read_text())
    assert side["attempts"] == 2 and side["last_outcome"] == "smoke_failed"
