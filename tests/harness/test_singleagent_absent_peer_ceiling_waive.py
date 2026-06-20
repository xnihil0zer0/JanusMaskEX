"""RED oracle: absent/empty-peer waives the single-agent promotion ceiling.

ROOT-CAUSE CONTEXT
------------------
``orchestrator_worker._single_agent_promotion_decision`` refuses promotion
while ``consecutive_failures < single_agent_promotion_ceiling`` (default 3).

When the failing peer produced an ABSENT/EMPTY submission (timeout/crash ->
``failing_violations == []``), the worker's absent-peer XOR branch
(orchestrator_worker.py, added in afcf85e) routes the lone AST-valid agent to
this decision helper -- but the ceiling can NEVER be reached on that path: a
deterministic ``synthesis_or_ast_failed`` gets a retry budget of 1 -> at most
2 dispatches -> ``consecutive_failures`` maxes at 2 < ceiling 3 -> promotion
never fires. Retrying a deterministic timeout on a large task is futile, so
waiting for 3 consecutive failures is both unreachable AND pointless.

CONTRACT (the fix this oracle pins)
-----------------------------------
When the failing peer is ABSENT/EMPTY (``failing_violations == []`` -- the
explicit signal the absent-peer call site passes), the ceiling check is WAIVED:
the lone AST-valid agent is promoted IMMEDIATELY, still behind the unchanged
sensitivity + operator-approval + AST-re-validation gates.

A peer that produced REAL violations (a genuine AST failure -> non-empty
``failing_violations``) is ALSO waived now: the ceiling is structurally
unreachable for it too (the deterministic retry cap of 1 caps
``consecutive_failures`` at 1), so an AST-invalid peer is treated the same as an
absent peer. See ``test_single_agent_promotion_invalid_peer.py`` for the
invalid-peer oracle that pins this; the survivor is still independently
re-validated and the sensitivity/approval gate is unchanged.

All assertions are RED on HEAD: HEAD returns ``(False, 'Ceiling not reached ...')``
for the absent-peer-below-ceiling case.
"""
from __future__ import annotations

import harness.orchestrator_worker as worker


_CFG = {'synthesis': {'enable_single_agent_promotion': True,
                      'single_agent_promotion_ceiling': 3}}


def test_absent_peer_below_ceiling_promotes_nonsensitive():
    """Absent peer (failing_violations == []) + below ceiling + non-sensitive
    target + flag on -> promote immediately (ceiling WAIVED)."""
    promote, reason = worker._single_agent_promotion_decision(
        config=_CFG,
        task={'task_id': 't1', 'meta_task_type': 'validation',
              'files_touched': ['external/mod.py']},
        state_dir=None,
        valid_agent='claude',
        valid_code='def f():\n    return 1\n',
        failing_agent='gemini',
        failing_violations=[],          # ABSENT/EMPTY peer signal
        consecutive_failures=1,         # BELOW ceiling (3) -- unreachable in practice
        approval_ok=False,
    )
    assert promote is True, reason
    assert 'gemini' in reason.lower()


def test_absent_peer_below_ceiling_sensitive_with_approval_promotes():
    """Absent peer + below ceiling + SENSITIVE target WITH operator approval
    -> promote (ceiling waived; approval gate satisfied)."""
    promote, reason = worker._single_agent_promotion_decision(
        config=_CFG,
        task={'task_id': 't2', 'meta_task_type': 'harness_self_fix',
              'files_touched': ['harness/orchestrator_worker.py']},
        state_dir=None,
        valid_agent='claude',
        valid_code='def f():\n    return 1\n',
        failing_agent='gemini',
        failing_violations=[],
        consecutive_failures=2,
        approval_ok=True,               # operator approved
    )
    assert promote is True, reason
    assert 'gemini' in reason.lower()


def test_absent_peer_below_ceiling_sensitive_without_approval_refused():
    """Absent peer + below ceiling + SENSITIVE target WITHOUT approval ->
    REFUSED. The ceiling waiver must NOT bypass the sensitivity/approval gate."""
    promote, reason = worker._single_agent_promotion_decision(
        config=_CFG,
        task={'task_id': 't3', 'meta_task_type': 'harness_self_fix',
              'files_touched': ['harness/orchestrator_worker.py']},
        state_dir=None,
        valid_agent='claude',
        valid_code='def f():\n    return 1\n',
        failing_agent='gemini',
        failing_violations=[],
        consecutive_failures=2,
        approval_ok=False,              # NOT approved
    )
    assert promote is False
    assert 'approval' in reason.lower()


def test_flag_off_absent_peer_never_promotes():
    """Flag OFF -> never promote, even for an absent peer."""
    promote, _reason = worker._single_agent_promotion_decision(
        config={'synthesis': {'enable_single_agent_promotion': False,
                              'single_agent_promotion_ceiling': 3}},
        task={'task_id': 't4', 'meta_task_type': 'validation',
              'files_touched': ['external/mod.py']},
        state_dir=None,
        valid_agent='claude',
        valid_code='def f():\n    return 1\n',
        failing_agent='gemini',
        failing_violations=[],
        consecutive_failures=99,
        approval_ok=True,
    )
    assert promote is False


def test_real_violations_below_ceiling_promotes():
    """CORRECTED CONTRACT (invalid-peer waive): a peer with REAL (non-empty)
    violations below the ceiling now PROMOTES the valid survivor, exactly like an
    absent peer. The earlier "still refused" assertion codified the very defect
    being fixed: a deterministic synthesis_or_ast_failed outcome caps the retry
    budget at 1, so consecutive_failures can never reach the ceiling (3) and the
    ceiling is STRUCTURALLY UNREACHABLE for an AST-invalid peer -- it would park
    a valid, approved survivor forever. The ceiling is therefore waived for an
    AST-invalid peer too; the survivor is still independently re-validated below.
    See tests/harness/test_single_agent_promotion_invalid_peer.py for the full
    invalid-peer oracle."""
    from harness.ast_enforcer import Violation
    real_violations = [Violation('security', 'error', 1, 'eval() is banned')]
    promote, reason = worker._single_agent_promotion_decision(
        config=_CFG,
        task={'task_id': 't5', 'meta_task_type': 'validation',
              'files_touched': ['external/mod.py']},
        state_dir=None,
        valid_agent='claude',
        valid_code='def f():\n    return 1\n',
        failing_agent='gemini',
        failing_violations=real_violations,   # REAL failure, not absent
        consecutive_failures=1,               # below ceiling (unreachable anyway)
        approval_ok=False,
    )
    assert promote is True, reason
    assert 'gemini' in reason.lower()


def test_real_violations_at_ceiling_still_promotes():
    """REGRESSION: the pre-existing at-ceiling promotion path is unchanged --
    a real-violations peer AT the ceiling still promotes (non-sensitive)."""
    from harness.ast_enforcer import Violation
    real_violations = [Violation('security', 'error', 1, 'eval() is banned')]
    promote, reason = worker._single_agent_promotion_decision(
        config=_CFG,
        task={'task_id': 't6', 'meta_task_type': 'validation',
              'files_touched': ['external/mod.py']},
        state_dir=None,
        valid_agent='claude',
        valid_code='def f():\n    return 1\n',
        failing_agent='gemini',
        failing_violations=real_violations,
        consecutive_failures=3,               # AT ceiling
        approval_ok=False,
    )
    assert promote is True, reason
    assert 'gemini' in reason.lower()


def test_no_patch_or_manifest_sentinels_in_module():
    """Anti-cheat: this is an oracle test, not a patch bundle. The imported
    worker module must expose no JanusMask patch/manifest sentinels."""
    assert not hasattr(worker, '__JANUSMASK_PATCHES__')
    assert not hasattr(worker, '__JANUSMASK_MANIFEST__')
