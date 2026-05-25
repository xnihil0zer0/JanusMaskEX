"""Adversarial regression bar for rollback_worktree_checkout.

Bug: ``harness.orchestrator._auto_commit_accepted`` reverts a rejected
commit with ``git reset --hard HEAD~1`` only. If the reset partially
fails (timeout mid-operation, index drift, partial stat error) the
target file in the worktree can carry the half-applied change forward
into the next iteration -- contaminating the pytest baseline that the
very next ``verification_command`` reads. This is the criterion-7
(rollback completeness) blocker called out in
``Janusmask-backlog-review-subreport-02.md`` rank 2.

Fix shape (this brief):
- After each ``git reset --hard HEAD~1`` call in _auto_commit_accepted,
  invoke ``subprocess.run(['git', 'checkout', 'HEAD', '--', target_rel],
  cwd=str(worktree_root), check=False, timeout=30)`` wrapped in a
  matching ``(subprocess.TimeoutExpired, FileNotFoundError, OSError)``
  try/except with ``logger.error`` on the failure path.
- Idempotent against a clean post-reset worktree; a no-op when the
  reset succeeded. Belt-and-suspenders.

The two xfail markers in this file are dropped in a follow-up META
commit once the fix lands (same pattern as RP3 / RP7).
"""
from __future__ import annotations

import ast
import pathlib

import pytest


REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
ORCH_PATH = REPO_ROOT / "harness" / "orchestrator.py"


def _load_auto_commit_accepted() -> tuple[str, ast.FunctionDef]:
    """Return (source_text, FunctionDef AST node) for _auto_commit_accepted.

    Source-grep + ast-walk keeps the test robust against minor formatting
    drift (whitespace, line-break placement) inside the function body.
    """
    src = ORCH_PATH.read_text(encoding="utf-8")
    module = ast.parse(src)
    candidates = [
        n
        for n in ast.walk(module)
        if isinstance(n, ast.FunctionDef) and n.name == "_auto_commit_accepted"
    ]
    assert candidates, (
        "_auto_commit_accepted not found in harness/orchestrator.py; "
        "module structure changed unexpectedly"
    )
    return src, candidates[0]


def _find_checkout_after_reset_in_block(
    fn: ast.FunctionDef, event_literal: str
) -> tuple[ast.Call | None, ast.Call | None, ast.Call | None]:
    """Locate the (reset_call, checkout_call, write_jsonl_row_call) trio
    in the branch whose ``write_jsonl_row`` payload contains a string
    literal ``event_literal`` (e.g. ``"verification_missing"`` or
    ``"verification_failed"``).

    Returns ``(reset, checkout, ledger)`` where each element is the
    ``ast.Call`` node or ``None`` if not located. The expected source
    order is reset -> checkout -> ledger.
    """
    # Walk every Call inside the function and unparse for substring
    # matching -- robust against minor arg-ordering / kwarg drift.
    reset_call: ast.Call | None = None
    checkout_call: ast.Call | None = None
    ledger_call: ast.Call | None = None

    calls_in_order: list[ast.Call] = [
        n for n in ast.walk(fn) if isinstance(n, ast.Call)
    ]
    # Sort by source position so "after the reset" means lineno-greater.
    calls_in_order.sort(key=lambda n: (n.lineno, n.col_offset))

    # Find the ledger call (write_jsonl_row whose payload mentions event_literal).
    for call in calls_in_order:
        try:
            src = ast.unparse(call)
        except Exception:
            continue
        if (
            "write_jsonl_row" in src
            and f"'event': '{event_literal}'" in src
        ):
            ledger_call = call
            break

    if ledger_call is None:
        return (None, None, None)

    # Find the most-recent reset --hard HEAD~1 call before the ledger row.
    for call in calls_in_order:
        if call.lineno >= ledger_call.lineno:
            break
        try:
            src = ast.unparse(call)
        except Exception:
            continue
        if "'git'" in src and "'reset'" in src and "'--hard'" in src:
            reset_call = call  # keep updating -- want the latest before ledger

    # Find a checkout call strictly between reset and ledger (exclusive).
    if reset_call is not None:
        for call in calls_in_order:
            if call.lineno <= reset_call.lineno:
                continue
            if call.lineno >= ledger_call.lineno:
                break
            try:
                src = ast.unparse(call)
            except Exception:
                continue
            if (
                "'git'" in src
                and "'checkout'" in src
                and "'HEAD'" in src
            ):
                checkout_call = call
                break

    return (reset_call, checkout_call, ledger_call)


def _load_rollback_helper() -> tuple[str, ast.FunctionDef]:
    """Return (source_text, FunctionDef) for _rollback_rejected_commit.

    G-RESET-RACE (#27) extracted the reset+checkout rollback out of
    _auto_commit_accepted into this shared helper so the rollback can guard
    on HEAD (revert instead of reset --hard when a peer commit landed on top).
    The reset->checkout rollback-completeness invariant now lives here.
    """
    src = ORCH_PATH.read_text(encoding="utf-8")
    module = ast.parse(src)
    candidates = [
        n
        for n in ast.walk(module)
        if isinstance(n, ast.FunctionDef) and n.name == "_rollback_rejected_commit"
    ]
    assert candidates, (
        "_rollback_rejected_commit not found in harness/orchestrator.py; "
        "G-RESET-RACE rollback helper missing"
    )
    return src, candidates[0]


def _branch_delegates_rollback(fn: ast.FunctionDef, event_literal: str) -> bool:
    """True iff the branch whose ledger row carries ``event_literal`` calls
    ``_rollback_rejected_commit`` at some point before that ledger row."""
    calls = sorted(
        (n for n in ast.walk(fn) if isinstance(n, ast.Call)),
        key=lambda n: (n.lineno, n.col_offset),
    )
    ledger = None
    for call in calls:
        try:
            s = ast.unparse(call)
        except Exception:
            continue
        if "write_jsonl_row" in s and f"'event': '{event_literal}'" in s:
            ledger = call
            break
    if ledger is None:
        return False
    for call in calls:
        if call.lineno >= ledger.lineno:
            break
        try:
            s = ast.unparse(call)
        except Exception:
            continue
        if "_rollback_rejected_commit" in s:
            return True
    return False


def _helper_pairs_reset_and_checkout() -> bool:
    """True iff _rollback_rejected_commit pairs a ``git reset --hard HEAD~1``
    with a ``git checkout HEAD`` (the rollback-completeness invariant)."""
    _, helper = _load_rollback_helper()
    body = ast.unparse(helper)
    has_reset = "'reset'" in body and "'--hard'" in body and "'HEAD~1'" in body
    has_checkout = "'checkout'" in body and "'HEAD'" in body
    return has_reset and has_checkout


def test_verification_missing_branch_has_checkout_after_reset() -> None:
    """The ``verification_missing`` branch must delegate rollback to
    ``_rollback_rejected_commit`` (G-RESET-RACE #27), and that helper must pair
    its ``git reset --hard HEAD~1`` with a ``git checkout HEAD`` so the worktree
    never carries a half-reverted target file into the next iteration's baseline.
    """
    src, fn = _load_auto_commit_accepted()
    assert "'event': 'verification_missing'" in src, (
        "verification_missing branch missing from _auto_commit_accepted; "
        "module structure changed unexpectedly"
    )
    assert _branch_delegates_rollback(fn, "verification_missing"), (
        "verification_missing branch must call _rollback_rejected_commit before "
        "its ledger row (rollback was not delegated to the guarded helper)"
    )
    assert _helper_pairs_reset_and_checkout(), (
        "_rollback_rejected_commit must pair 'git reset --hard HEAD~1' with a "
        "'git checkout HEAD' (rollback completeness)"
    )


def test_verification_failed_branch_has_checkout_after_reset() -> None:
    """The ``verification_failed`` branch must delegate rollback to
    ``_rollback_rejected_commit`` (G-RESET-RACE #27), and that helper must pair
    its ``git reset --hard HEAD~1`` with a ``git checkout HEAD``.
    """
    src, fn = _load_auto_commit_accepted()
    assert "'event': 'verification_failed'" in src, (
        "verification_failed branch missing from _auto_commit_accepted; "
        "module structure changed unexpectedly"
    )
    assert _branch_delegates_rollback(fn, "verification_failed"), (
        "verification_failed branch must call _rollback_rejected_commit before "
        "its ledger row (rollback was not delegated to the guarded helper)"
    )
    assert _helper_pairs_reset_and_checkout(), (
        "_rollback_rejected_commit must pair 'git reset --hard HEAD~1' with a "
        "'git checkout HEAD' (rollback completeness)"
    )
