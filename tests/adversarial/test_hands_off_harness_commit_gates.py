"""Hands-off enablement — the widened (autowork.enabled) auto-approve path must
actually be able to COMMIT a non-deny harness/** file with NO operator decision
file. Two gate gaps blocked this (reproduced dispatching symbol-ledger-module):

  GAP1 — git_integration._enforce_apply_scope hard-required
         meta_task_type=='harness_self_fix' for any harness/** path, ignoring the
         widened posture that B0 (_auto_approve_sensitive_eligible) grants under
         autowork.enabled. So an approved harness_plumbing harness/ write was
         rejected. FIX: a widened_auto_approve grant (the caller's
         _granted_via_auto_approve, set only AFTER B0's deny-list + content + RO
         gates) relaxes the meta requirement — but the irreducible
         _NEVER_AUTO_APPROVE deny-list is STILL refused (defense-in-depth).

  GAP2 — auto_approve_ro_gate (_verify_from_ro_parent) ran the 3 fixed
         _RO_GATE_TESTS from a bare `git archive` tarball; one of them
         (test_replication_clean_room_static.py) is NON-hermetic (reads git
         tracking + state/impl_progress.jsonl, absent from the archive) so it
         errored -> the gate fail-closed on EVERY auto-approve commit. FIX:
         _RO_GATE_TESTS keeps only the hermetic security invariants.
"""
from __future__ import annotations

import harness.git_integration as gi
import harness.orchestrator as orch


# ---------------- GAP1: _enforce_apply_scope widened posture ----------------

_HARNESS_NEW = ['harness/symbol_ledger.py']           # non-deny harness/** new file
_DENY = ['harness/orchestrator.py']                    # _NEVER_AUTO_APPROVE


def test_gap1_widened_grant_commits_non_deny_harness_plumbing():
    # approved (B0 widened) + harness_plumbing + non-deny harness/ -> accepted
    err = gi._enforce_apply_scope(
        _HARNESS_NEW, allowed_files=set(_HARNESS_NEW),
        meta_task_type='harness_plumbing', approval_ok=True,
        widened_auto_approve=True,
    )
    assert err is None, f"widened approved non-deny harness/ write must commit, got: {err}"


def test_gap1_strict_floor_unchanged_without_widened():
    # NOT widened: harness_plumbing harness/ write still rejected (strict floor)
    err = gi._enforce_apply_scope(
        _HARNESS_NEW, allowed_files=set(_HARNESS_NEW),
        meta_task_type='harness_plumbing', approval_ok=True,
        widened_auto_approve=False,
    )
    assert err is not None and 'protected path' in err, \
        "strict floor must still require harness_self_fix when not widened"


def test_gap1_widened_still_requires_approval():
    # widened but approval_ok False -> still rejected (approval is mandatory)
    err = gi._enforce_apply_scope(
        _HARNESS_NEW, allowed_files=set(_HARNESS_NEW),
        meta_task_type='harness_plumbing', approval_ok=False,
        widened_auto_approve=True,
    )
    assert err is not None, "widened relaxation must still require approval_ok"


def test_gap1_deny_list_still_refused_under_widened():
    # The irreducible deny-list is refused even with widened+approval (def-in-depth)
    err = gi._enforce_apply_scope(
        _DENY, allowed_files=set(_DENY),
        meta_task_type='harness_plumbing', approval_ok=True,
        widened_auto_approve=True,
    )
    assert err is not None and 'protected path' in err, \
        "a _NEVER_AUTO_APPROVE path must NEVER auto-approve, even widened"


def test_gap1_strict_harness_self_fix_path_still_works():
    # The operator harness_self_fix + approval path is unchanged.
    err = gi._enforce_apply_scope(
        _HARNESS_NEW, allowed_files=set(_HARNESS_NEW),
        meta_task_type='harness_self_fix', approval_ok=True,
        widened_auto_approve=False,
    )
    assert err is None, f"operator harness_self_fix + approval must still commit, got: {err}"


# ---------------- GAP2: _RO_GATE_TESTS hermetic + gate passes ----------------

def test_gap2_ro_gate_tests_drop_non_hermetic():
    assert 'tests/adversarial/test_replication_clean_room_static.py' not in orch._RO_GATE_TESTS, \
        "the non-hermetic clean-room-static test must not gate auto-approve (reads git/state)"
    # The hermetic security invariants remain.
    assert 'tests/adversarial/test_sec_inv2_trustroot.py' in orch._RO_GATE_TESTS
    assert 'tests/adversarial/test_p10b_denylist_widen.py' in orch._RO_GATE_TESTS


def test_gap2_verify_from_ro_parent_passes_for_clean_head(tmp_path):
    # End-to-end: the RO-parent gate must now return True for HEAD verified
    # against the live repo as the candidate (it fail-closed before the fix).
    import subprocess
    repo_root = orch.PROJECT_DIR if hasattr(orch, 'PROJECT_DIR') else None
    if repo_root is None:
        import pathlib
        repo_root = pathlib.Path(__file__).resolve().parents[2]
    head = subprocess.run(['git', 'rev-parse', 'HEAD'], cwd=str(repo_root),
                          capture_output=True, text=True).stdout.strip()
    ok = gi._verify_from_ro_parent(repo_root, head, repo_root, orch._RO_GATE_TESTS, timeout_sec=120)
    assert ok is True, "RO-parent gate must pass for a clean HEAD with the hermetic gate set"
