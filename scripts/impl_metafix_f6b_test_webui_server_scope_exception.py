"""Scope exception for META-FIX-F6b (F6b contract tests META-commit).

F6b (TestDispatchTable contract tests pinning F1b+F2b dispatch tables)
shipped a structurally correct 162-line Claude submission per the F6b
spec — 7 contract test methods named exactly per the brief, valid use
of the existing module-scope ``sidecar`` fixture, no overlap with the
existing ~18 D3 tests in test_webui_server.py.

The orchestrator dispatch FAILED at the fuzz phase
(/tmp/orchestrator_multifmt_F6b.log:372) with
``Fuzzing error: Failed to build input strategy from code_a:
Function 'main' not found in code``. Root cause: the test file has
no top-level non-test ``def`` for fuzz_from_task's target-function
discovery to lock onto, and META_TASK_POLICY['test_integration']
currently carries ``bypass_fuzzer=False`` (taxonomies.py:7-9) so the
bypass gate at diff_fuzzer.py:541/551/557 never fires. (F5d
coincidentally passed only because both submissions carried a
``def _git(...)`` helper that the discovery picked up.)

META direct-impl: surgical append of Claude's class verbatim to
tests/integration/test_webui_server.py — preserves existing 18+
tests, threads through the existing ``sidecar`` fixture, no
production-code changes. The orchestrator's pre-fuzz output is
preserved bit-identical in the outbox archive.

Pairs with brief_hooks_orchestrator_multifmt_dispatch.md (F6b's
brief, [FREEZE-LIFT] under multifmt-dispatch umbrella). The
underlying harness gap is captured in
brief_hooks_taxonomies_test_bypass.md (G4 — 5th harness self-fix,
filed FREEZE-LIFT as P-phase blocker for F6c-class re-dispatch).
"""


def is_in_scope(path: str) -> bool:
    return path == "tests/integration/test_webui_server.py"
