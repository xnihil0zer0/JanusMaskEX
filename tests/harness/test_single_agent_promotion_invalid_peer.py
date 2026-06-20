"""RED oracle: the single-agent promotion ceiling must be WAIVED for an
AST-INVALID peer in the XOR-valid case, exactly as it already is for an
ABSENT/empty peer.

VERIFIED DEFECT (parent HEAD): commit 45f6380 wrapped the consecutive-failures
ceiling check in ``if failing_violations:`` so the ceiling is WAIVED only when
the failing peer is absent (empty violations). But in the XOR-valid synthesis
branch (orchestrator_worker.py:506-545) ``failing_violations`` carries the
LOSING peer's violations, and when the peer is AST-INVALID those violations are
NON-empty -> the ceiling check still fires. A deterministic
``synthesis_or_ast_failed`` outcome (autowork_daemon.py ~:942) caps the retry
budget at 1, so ``consecutive_failures`` can never reach the default ceiling of
3. The ceiling is therefore STRUCTURALLY UNREACHABLE for an AST-invalid peer:
the surviving agent's valid, approved code is parked forever (real case:
claudecap-parallel-isolation-impl -- claude valid+approved, gemini AST-invalid).

CONTRACT: a deterministically-futile AST-INVALID peer must be treated the SAME
as an ABSENT peer -- both are pointless to retry under the retry cap of 1. When
the surviving agent's own code is AST-valid (re-confirmed by the canonical
validator), single-agent promotion is enabled, and the operator/sensitivity gate
is satisfied, promotion MUST proceed on attempt 1 regardless of how many
violations the dropped peer carried. The waive MUST NOT fire when the surviving
agent itself is invalid, when promotion is disabled, or when a sensitive target
lacks operator approval -- those refusals stay intact.

These cases are RED on parent HEAD (the AST-invalid-peer positive case returns
``(False, 'Ceiling not reached ...')``) and GREEN after the fix.
"""
from __future__ import annotations

import pytest


def _decide(**overrides):
    """Call _single_agent_promotion_decision with sensible XOR-valid defaults.

    Defaults model the live failure: a NON-sensitive target, single-agent
    promotion ENABLED, the surviving agent's code AST-valid, a peer rejected for
    a REAL (non-empty) AST violation, on the FIRST blocked invocation
    (consecutive_failures == 1, the maximum a deterministic outcome can reach).
    """
    import harness.orchestrator_worker as worker

    decide = getattr(worker, "_single_agent_promotion_decision", None)
    assert decide is not None, (
        "harness.orchestrator_worker._single_agent_promotion_decision must exist"
    )
    # A concrete, non-empty peer violation list (the AST-invalid-peer signal).
    from harness.ast_enforcer import Violation

    peer_violations = [Violation("security", "error", 1, "eval() is banned")]

    params = dict(
        config={
            "synthesis": {
                "enable_single_agent_promotion": True,
                "single_agent_promotion_ceiling": 3,
            }
        },
        # NON-sensitive target: external/** path, non-meta task type.
        task={
            "task_id": "t-invalid-peer",
            "meta_task_type": "validation",
            "files_touched": ["external/mod.py"],
        },
        state_dir=None,
        valid_agent="claude",
        valid_code="def f():\n    return 1\n",
        failing_agent="gemini",
        failing_violations=peer_violations,
        consecutive_failures=1,
        approval_ok=False,
    )
    params.update(overrides)
    return decide(**params)


def test_invalid_peer_below_ceiling_promotes_nonsensitive():
    """POSITIVE: surviving agent AST-valid + approved-by-non-sensitivity +
    promotion enabled, peer AST-invalid (NON-empty violations),
    consecutive_failures == 1 -> PROMOTE. RED on parent (parent returns
    (False, 'Ceiling not reached ...')) because the AST-invalid peer still hits
    the structurally-unreachable ceiling."""
    promote, reason = _decide()
    assert promote is True, (
        "An AST-invalid peer must waive the (unreachable) ceiling just like an "
        f"absent peer; got refusal: {reason!r}"
    )
    assert "gemini" in reason.lower(), (
        f"Promotion reason must name the dropped peer; got: {reason!r}"
    )


def test_surviving_agent_invalid_still_refused():
    """NEGATIVE GUARD: if the SURVIVING agent's own code is AST-invalid (banned
    eval()), the canonical re-validation gate must still REFUSE -- the waive must
    not promote an invalid survivor. Green on parent AND after the fix."""
    promote, reason = _decide(
        valid_code="def f():\n    eval('1')\n",
    )
    assert promote is False, (
        "A surviving agent whose own code fails AST validation must be refused; "
        f"got promote with reason: {reason!r}"
    )


def test_promotion_disabled_still_refused():
    """NEGATIVE GUARD: with single-agent promotion disabled, no promotion occurs
    even for an AST-invalid peer below the ceiling. Proves the waive did not
    over-broaden past the enable flag."""
    promote, _reason = _decide(
        config={
            "synthesis": {
                "enable_single_agent_promotion": False,
                "single_agent_promotion_ceiling": 3,
            }
        },
    )
    assert promote is False


def test_sensitive_invalid_peer_without_approval_still_refused():
    """NEGATIVE GUARD: a sensitive (harness/**) target with an AST-invalid peer
    must still be REFUSED without operator approval -- the sensitivity/approval
    gate is independent of the ceiling waive."""
    promote, _reason = _decide(
        task={
            "task_id": "t-sensitive-invalid-peer",
            "meta_task_type": "harness_self_fix",
            "files_touched": ["harness/orchestrator.py"],
        },
        approval_ok=False,
    )
    assert promote is False


def test_absent_peer_below_ceiling_still_promotes():
    """REGRESSION (no regression to 45f6380): the existing absent-peer waive --
    empty failing_violations, consecutive_failures == 1 -- still PROMOTES."""
    promote, reason = _decide(failing_violations=[])
    assert promote is True, (
        f"Absent-peer waive (45f6380) must still promote; got refusal: {reason!r}"
    )
    assert "gemini" in reason.lower()


def test_sensitive_invalid_peer_with_approval_promotes():
    """POSITIVE: a sensitive (harness/**) target with an AST-invalid peer and a
    granted operator approval PROMOTES on attempt 1 -- the ceiling waive applies
    once the approval gate is satisfied. RED on parent (ceiling refusal)."""
    promote, reason = _decide(
        task={
            "task_id": "t-sensitive-invalid-peer-ok",
            "meta_task_type": "harness_self_fix",
            "files_touched": ["harness/orchestrator_worker.py"],
        },
        approval_ok=True,
    )
    assert promote is True, (
        "A sensitive AST-invalid-peer case with operator approval must promote "
        f"on attempt 1; got refusal: {reason!r}"
    )
    assert "gemini" in reason.lower()
