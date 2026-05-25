"""Scope exception for META-FIX-F5 (Claude's F5d preserved submission + V2 fixture patch).

F5 has burned 4 dispatch cycles uncovering 4 orthogonal bugs:
  1. F5b: Gemini scratch-file sandbox (→ G1 commit b4189a0)
  2. F5c: orchestrator AST nondet validator missed test_* (→ G2 / META-FIX-U2.5 commit 0461d6a)
  3. F5c→G2: vcmd JANUSMASK_TASK_ID env leak (→ G3 brief filed at brief_hooks_vcmd_env_isolation.md)
  4. F5d: V2 collateral on M2-merge-fixture task dict missing verification_command

The agent's F5d submission is structurally correct (4 non-py cases + target_suffix
kwarg + TestCommitsNonPyTarget class + ORIGINAL_MODULE template + _exercise_non_py
helper); the only remaining gap is bug #4 which the agent could not have known about
(spec didn't mention V2 fixture impact). META direct-impl copies Claude's preserved
F5d submission verbatim + adds `"verification_command": "true"` to the M2-merge-fixture
task dict at line 191-195 (single fix, all callers benefit).

Pairs with plan_hooks_orchestrator_multifmt_dispatch_rerun.json's F5d entry (which is
in processed/ post-V2 revert of cbacca7). Closes the F-task plan's F5 row with
behavioural equivalence to a successful orchestrator dispatch.
"""


def is_in_scope(path: str) -> bool:
    return path == "tests/integration/test_auto_commit_merge.py"
