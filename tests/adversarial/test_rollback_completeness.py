"""Adversarial bar for rollback_completeness.

These tests are xfail-strict until the rollback_completeness dispatch lands a
best-effort working-tree scrub in the non-`no_diff` commit-failure branch of
`harness/orchestrator.py:_auto_commit_accepted`. On accept, drop the xfail
markers so they become regression guards.

Background (session #26, S4 audit): the auto-commit path stages merged file(s)
via `git_integration.commit_accepted_output` BEFORE the `git commit` step. The
two existing rollback sites (verification_missing / verification_failed) do
`git reset --hard HEAD~1` + `git checkout HEAD -- <rel>`, which is correct once
a commit exists. But if the commit (or a later git op) raises a non-`no_diff`
error (e.g. index.lock contention from a concurrent operator commit), the
branch returned a generic error string and performed NO scrub — leaking a
staged index modification + staged-new sibling files into the next dispatch.

The fix adds a best-effort non-destructive scrub (`git reset -q -- <rel>` +
`git checkout HEAD -- <rel>`) over files_touched in that branch, distinct from
the existing `reset --hard HEAD~1` rollbacks (which must survive).
"""

from __future__ import annotations

import ast
import pathlib

import pytest

ORCH_PATH = pathlib.Path(__file__).resolve().parents[2] / "harness" / "orchestrator.py"


def _auto_commit_fn() -> ast.FunctionDef:
    tree = ast.parse(ORCH_PATH.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_auto_commit_accepted":
            return node
    raise AssertionError("_auto_commit_accepted not found in harness/orchestrator.py")


def test_commit_failure_branch_runs_non_destructive_reset():
    # The non-destructive `git reset -q` (distinct from the existing
    # `reset --hard HEAD~1` rollbacks) is the sole discriminator for the fix;
    # the working tree already contains several `checkout`/`HEAD~1` refs.
    body = ast.unparse(_auto_commit_fn())
    assert "'reset', '-q'" in body, (
        "non-no_diff commit-failure branch must run a non-destructive `git reset -q`"
    )


def test_existing_rollback_sites_survive():
    """Plain guard: the two existing reset --hard HEAD~1 rollbacks and the
    no_diff sub-branch must never regress, before or after the scrub lands."""
    body = ast.unparse(_auto_commit_fn())
    assert body.count("HEAD~1") >= 2, "both existing reset --hard HEAD~1 rollbacks must survive"
    assert "no_diff:" in body, "no_diff sub-branch must be preserved"
    assert "verification_missing" in body and "verification_failed" in body, (
        "existing rollback sites must survive"
    )
