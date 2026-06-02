"""Oracle for PHASE_SEC_SERVICES_GLOB.

Asserts that services/** paths are treated as sensitive apply paths, requiring
meta_task_type='harness_self_fix' and operator approval to commit, just like
harness/**, config/**, and scripts/**.

Target path: tests/adversarial/test_sec_services_glob.py
"""

from __future__ import annotations

import pathlib
import sys
import pytest

# Ensure repo root is on sys.path
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import harness.git_integration as gi


def test_services_glob_matches_sensitive():
    """Assert that a path in services/** is matched as sensitive by gi._matches_sensitive."""
    path = "services/neurosymbolic/ast_verifier.py"
    assert gi._matches_sensitive(path, gi._SENSITIVE_APPLY_GLOBS) is True, (
        f"Path '{path}' should match sensitive globs: {gi._SENSITIVE_APPLY_GLOBS}"
    )


def test_services_glob_enforce_apply_scope_rejected_by_default():
    """Assert that services/** paths are rejected by default (no approval, no self-fix)."""
    path = "services/neurosymbolic/ast_verifier.py"
    err = gi._enforce_apply_scope(
        [path],
        allowed_files=None,
        meta_task_type=None,
        approval_ok=False,
    )
    assert err is not None, (
        f"Path '{path}' should be rejected when meta_task_type=None and approval_ok=False"
    )
    assert "protected path" in err, (
        f"Expected a protected path scope violation message, got: {err}"
    )


def test_services_glob_enforce_apply_scope_approval_semantics():
    """Assert that services/ paths are allowed only under harness_self_fix + operator approval."""
    # Allowed case: harness_self_fix AND approval_ok is True
    allowed_err = gi._enforce_apply_scope(
        ["services/x.py"],
        allowed_files=None,
        meta_task_type="harness_self_fix",
        approval_ok=True,
    )
    assert allowed_err is None, (
        "services/x.py should be allowed with meta_task_type='harness_self_fix' and approval_ok=True"
    )

    # Disallowed case: harness_self_fix BUT approval_ok is False
    denied_err = gi._enforce_apply_scope(
        ["services/x.py"],
        allowed_files=None,
        meta_task_type="harness_self_fix",
        approval_ok=False,
    )
    assert denied_err is not None, (
        "services/x.py should be rejected when approval_ok is False"
    )
    assert "protected path" in denied_err, (
        f"Expected a protected path scope violation message, got: {denied_err}"
    )


def test_services_glob_green_preserving_controls():
    """Assert that existing sensitive paths remain gated, and other paths remain un-gated."""
    # Existing sensitive directories must still be gated
    for path in ["harness/orchestrator.py", "config/config.yaml", "scripts/run.sh"]:
        err = gi._enforce_apply_scope(
            [path],
            allowed_files=None,
            meta_task_type=None,
            approval_ok=False,
        )
        assert err is not None, f"Existing sensitive path '{path}' should be gated by default"
        assert "protected path" in err, f"Expected protected path violation for '{path}', got: {err}"

    # Sibling directory 'services_backup/x.py' should NOT be sensitive (i.e. returns None)
    backup_err = gi._enforce_apply_scope(
        ["services_backup/x.py"],
        allowed_files=None,
        meta_task_type=None,
        approval_ok=False,
    )
    assert backup_err is None, "Sibling path 'services_backup/x.py' should not be sensitive"

    # Unrelated directory 'tests/test_x.py' should NOT be sensitive (i.e. returns None)
    tests_err = gi._enforce_apply_scope(
        ["tests/test_x.py"],
        allowed_files=None,
        meta_task_type=None,
        approval_ok=False,
    )
    assert tests_err is None, "Unrelated path 'tests/test_x.py' should not be sensitive"
