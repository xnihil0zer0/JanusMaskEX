"""Scope exception for META-FIX-G6 (Claude's G6v2 preserved submission).

G6v2 (G6_ast_merge_fixture_coverage re-dispatched after G8 unblocked smoke for
test_* mtt) failed at AST validation because Gemini's submission used
``__import__('uuid').uuid4()`` in 7 places — banned by
``harness/ast_enforcer.py:112`` ``_check_dangerous_calls``. Three retries did
not change the pattern. Claude's submission passed clean (0 warnings) and
satisfies every G6 done-criteria: BASE_*/OVERLAY_* fixture pairs for all 10
node-kind cases, parametrized ``test_ast_merge_per_node_kind``, and the
``_build`` ``original_override`` / ``output_override`` kwarg additions.

META direct-impl applies Claude's preserved submission to
``tests/integration/test_auto_commit_merge.py`` via the post-G5 ``_ast_merge``
(which the submission was designed to flow through). Mirrors 2026-05-17 F6b
META-FIX precedent (commit 1076af3) for the same Gemini-stubbornness class
under different rule wording.

Underlying harness gap (AST enforcer ``__import__`` rule has no auto-repair
stage that could mechanically rewrite ``__import__('X').Y`` to ``X.Y``)
captured separately as G10 brief (clean-room port of NobleGreed-legacy's
auto-repair design pattern). G10 dispatch follows immediately.
"""


def is_in_scope(path: str) -> bool:
    return path == "tests/integration/test_auto_commit_merge.py"
