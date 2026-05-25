"""Scope exception for META-FIX-U2.5 (G2 verified-diff META-commit).

G2 (orchestrator.py:697 nondet carve-out for test_*) shipped via orchestrator
as commit 50af9a6 with structurally perfect diff (2 spec'd lines + 6
docstring lines) but was reverted by V2 due to an UNRELATED test isolation
contamination bug in tests/test_orchestrator.py:TestCollectSubmissions
(JANUSMASK_TASK_ID env var leaks from orchestrator dispatch into vcmd
pytest invocation, breaking the test's hardcoded task_id='default'
expectation).

The orchestrator's auto-commit diff itself was verified-correct against the
G2 brief's acceptance criteria; META-commit restores the exact same +9
insertions / 0 deletions patch by hand.

Pairs with brief_hooks_orchestrator_test_nondet_carveout.md (G2's brief,
[FREEZE-LIFT] approved by operator). G3 brief (vcmd env isolation) will
be filed as a separate cycle to fix the meta-bug; this SE covers ONLY
the META-commit re-application of G2's verified diff.
"""


def is_in_scope(path: str) -> bool:
    return path == "harness/orchestrator.py"
