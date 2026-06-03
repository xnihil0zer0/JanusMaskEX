"""Self-heal Link #2 oracle: the AST-validation reject terminal must persist the
per-agent violation reason to the ledger so the daemon's ``_escalate_to_autobrief``
diagnosing agent (via ``autowork_daemon._get_errors_for_task``) sees *why* the task
failed (e.g. ``gemini ... eval() is banned``) instead of "No error logs found".

RED on HEAD: ``orchestrator_worker``'s ``synthesis_or_ast_failed`` terminal emits only
``phase_transition`` + ``task_terminal`` + ``_mark_blocked`` -- none carry the
per-agent violations that are in scope at that point (``agent_a_violations`` /
``agent_b_violations``). The fix wires a ledger emission carrying those violations.
"""
from __future__ import annotations

import json
import pathlib

from harness import autowork_daemon as d

REPO = pathlib.Path(__file__).resolve().parents[2]
WORKER = REPO / "harness" / "orchestrator_worker.py"


def test_ast_reject_terminal_persists_violation_detail() -> None:
    """The synthesis_or_ast_failed terminal must persist the per-agent AST
    violations to the ledger (a ``detail`` field) so the self-heal diagnosis is
    grounded. RED until the terminal emits the violations."""
    src = WORKER.read_text(encoding="utf-8")
    anchor = "_mark_blocked(state_dir, task_id, 'synthesis_or_ast_failed')"
    assert anchor in src, "AST-reject terminal anchor moved/renamed"
    i = src.index(anchor)
    # Slice the EXACT terminal block: from the `if not synthesis_success:` guard
    # that opens it up to the _mark_blocked route. This excludes the retry-loop's
    # prompt-building code (which also references the violations), so the test can
    # only go green if the emission lives in the terminal itself and carries the
    # violations -- not by accidentally matching unrelated upstream code.
    guard = src.rfind("if not synthesis_success:", 0, i)
    assert guard != -1, "synthesis_success terminal guard not found before anchor"
    window = src[guard:i]
    refs_violations = (
        "agent_a_violations" in window
        or "agent_b_violations" in window
        or "violation" in window.lower()
    )
    emits_ledger = (
        ("_emit_lifecycle" in window and "detail" in window)
        or "write_jsonl" in window
    )
    assert refs_violations and emits_ledger, (
        "synthesis_or_ast_failed terminal must persist the per-agent AST violation "
        "summary to impl_progress.jsonl (detail=...) so _get_errors_for_task can "
        "surface it to the diagnosing agent"
    )


def test_get_errors_surfaces_ast_violation_detail(tmp_path) -> None:
    """Round-trip guard: a ledger row in the shape the terminal must write is
    surfaced by ``_get_errors_for_task`` -- proves the chosen ledger shape actually
    reaches the diagnosing agent. (Passes on HEAD; pins the contract the terminal
    must satisfy.)"""
    state = tmp_path / "state"
    (state / "tasks").mkdir(parents=True)
    tid = "method_d_05_taxonomy_flip"
    row = {
        "ts": "2026-06-03T00:00:00Z",
        "phase": "rejected",
        "task_id": tid,
        "event": "ast_validation_failed",
        "detail": "gemini: security (Line 1): eval() is banned for security reasons",
    }
    (state / "impl_progress.jsonl").write_text(json.dumps(row) + "\n", encoding="utf-8")
    out = d._get_errors_for_task(state, tid)
    assert "eval()" in out and "banned" in out, (
        f"_get_errors_for_task did not surface the AST violation detail; got: {out!r}"
    )
