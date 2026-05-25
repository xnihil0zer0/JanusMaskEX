"""Adversarial regression bar for G28 — _validate_submission must reject
single-file submissions when files_touched declares > 1 file.

Background: harness/orchestrator.py:_validate_submission currently checks
``manifest = _parse_manifest(code)``. When the parse returns ``None`` (i.e.
the agent did not emit ``__JANUSMASK_MANIFEST__``), validation falls
through to single-file AST validation against ``files_touched[0]``. If the
single-file code parses cleanly, validation passes — silently leaving
N-1 files un-modified. The downstream commit then hits
``multi_file_missing_sidecar`` and falls back to committing only
``files_touched[0]``, after which V2 rollback fires when the vcmd fails on
the missing files. Witnessed: G25 v1 (commit de45e9a, rolled back) and
AW5a v1 (commit c05c8f7, reverted as a405562).

The fix: enforce manifest emission at validation time. When ``manifest is
None`` AND ``len(files_touched) > 1``, return ``(False, [Violation(
rule='manifest_missing', ...)])`` so the existing AST-retry loop forces
the agent to resubmit as a manifest. After max_ast_retries (3), the task
gets rejected without committing.

Three tests:
1. ``test_validate_submission_accepts_manifest_for_multifile`` — contract,
   always passes: a manifest dict for a multi-file task is accepted.
2. ``test_validate_submission_accepts_single_file_for_single_file_task``
   — contract, always passes: single-file code stays valid for
   single-file tasks (no regression on the normal path).
3. ``test_validate_submission_rejects_single_file_for_multifile`` —
   regression bar: single-file code on a multi-file task yields a
   ``manifest_missing`` error violation. Passes naturally after G28
   landed in commit 3cdcd6f.
"""
from __future__ import annotations

from harness.orchestrator import _validate_submission


_MANIFEST_CODE = """__JANUSMASK_MANIFEST__ = {
    'a.py': r'''def alpha() -> int:
    return 1
''',
    'b.py': r'''def beta() -> int:
    return 2
''',
}
"""

_SINGLE_FILE_CODE = """def alpha() -> int:
    return 1
"""


def test_validate_submission_accepts_manifest_for_multifile() -> None:
    task = {
        "task_id": "TEST_MULTIFILE_MANIFEST",
        "files_touched": ["a.py", "b.py"],
        "meta_task_type": "harness_self_fix",
    }
    valid, violations = _validate_submission(_MANIFEST_CODE, "claude", task)
    errors = [v for v in violations if v.severity == "error"]
    assert valid, f"manifest submission rejected; errors={errors!r}"
    assert errors == [], (
        f"manifest submission produced errors: {errors!r}"
    )


def test_validate_submission_accepts_single_file_for_single_file_task() -> None:
    task = {
        "task_id": "TEST_SINGLE_FILE",
        "files_touched": ["a.py"],
        "meta_task_type": "harness_self_fix",
    }
    valid, violations = _validate_submission(_SINGLE_FILE_CODE, "claude", task)
    errors = [v for v in violations if v.severity == "error"]
    assert valid, f"single-file submission rejected for single-file task; errors={errors!r}"


def test_validate_submission_rejects_single_file_for_multifile() -> None:
    task = {
        "task_id": "TEST_MULTIFILE_NO_MANIFEST",
        "files_touched": ["a.py", "b.py"],
        "meta_task_type": "harness_self_fix",
    }
    valid, violations = _validate_submission(_SINGLE_FILE_CODE, "claude", task)
    assert not valid, (
        "single-file submission on multi-file task should be REJECTED; "
        "the agent forgot to wrap files in __JANUSMASK_MANIFEST__"
    )
    error_rules = {v.rule for v in violations if v.severity == "error"}
    assert "manifest_missing" in error_rules, (
        f"missing 'manifest_missing' error rule; got: {error_rules!r}"
    )
