"""RED oracle for P5b — single-agent promotion hatch + config keys + gating.

Contract (REV26 P5b):
  When ONE synthesis agent deterministically and consistently FAILS AST
  validation (e.g. Gemini's test-gen always emitting banned ``eval()``,
  ast_enforcer.py:70-72) and the OTHER consistently PASSES, the dual-agent
  AND-gate (orchestrator_worker.py:297 / :238; orchestrator.py:2919) can never
  be satisfied and the task is permanently blocked. P5b adds an OPT-IN hatch:
  after ``synthesis.single_agent_promotion_ceiling`` (default 3) consecutive
  retries with the same pattern, IF ``synthesis.enable_single_agent_promotion``
  is true AND the surviving agent's code passes ALL AST/credential/
  nondeterminism rules, promote the valid agent and DROP the failing one,
  persisting (telemetry/ledger) which agent was dropped and why.

  HARD SECURITY GATE: for a sensitive target (meta_task_type=='harness_self_fix'
  and/or a files_touched path under _SENSITIVE_APPLY_GLOBS = harness/** etc.),
  promotion MUST additionally require an operator approval decision
  (``state/control/decisions/<task_id>.json`` decision=approve, per
  orchestrator._apply_approval_granted). P5 alone MUST NOT promote a sensitive
  target — it drops the dual-agent independent-equivalence guarantee.

  This oracle asserts on a NET-NEW promotion-decision helper the implementation
  must expose: ``orchestrator_worker._single_agent_promotion_decision`` (or the
  config-key reads + decision contract it encodes). All three asserts are RED
  on HEAD because neither the config keys nor any promotion path exist yet.
"""
from __future__ import annotations
import json
import pathlib
import pytest


def test_config_keys_present_and_ceiling_materialized():
    """The two NET-NEW synthesis config keys must exist and be materialized.

    OWNER POSTURE (2026-06-05): single-agent promotion is intentionally ON under
    the active autonomy posture (the in-env Claude planning role dies rc=2 in-jail
    so plans are gemini-only; single-agent promotion is what lets the daemon plan
    children hands-off). The key must still be MATERIALIZED (present, not absent)
    and the ceiling present.
    """
    from harness import orchestrator as orch
    cfg = orch.load_config(pathlib.Path('harness/config.yaml'))
    syn = cfg.get('synthesis', {})
    # materialized + ON under the active posture
    assert 'enable_single_agent_promotion' in syn, (
        'enable_single_agent_promotion must be a materialized synthesis config key'
    )
    assert syn.get('enable_single_agent_promotion') is True, (
        'enable_single_agent_promotion is ON under the active fully-unattended posture'
    )
    # ceiling present (default 3) — key must be materialized, not absent
    assert 'single_agent_promotion_ceiling' in syn, (
        'single_agent_promotion_ceiling must be a materialized synthesis config key'
    )
    assert int(syn['single_agent_promotion_ceiling']) >= 1


def test_promotion_helper_promotes_valid_agent_and_persists_drop():
    """With the flag on, a non-sensitive target, ceiling reached, and the valid
    agent passing ALL rules, the helper promotes the valid agent and records
    which agent was dropped and why."""
    import harness.orchestrator_worker as worker

    decide = getattr(worker, '_single_agent_promotion_decision', None)
    assert decide is not None, (
        'P5b must expose orchestrator_worker._single_agent_promotion_decision'
    )
    # Signature the implementation must satisfy (kwargs, order-independent):
    #   (config, task, state_dir, *, valid_agent, valid_code,
    #    failing_agent, failing_violations, consecutive_failures, approval_ok)
    # Returns (promote: bool, reason: str). Here: flag on, ceiling reached,
    # non-sensitive target -> promote True, reason names the dropped agent.
    decision = decide(
        config={'synthesis': {'enable_single_agent_promotion': True,
                              'single_agent_promotion_ceiling': 3}},
        task={'task_id': 't1', 'meta_task_type': 'validation',
              'files_touched': ['external/mod.py']},
        state_dir=None,
        valid_agent='claude',
        valid_code='def f():\n    return 1\n',
        failing_agent='gemini',
        failing_violations=[],
        consecutive_failures=3,
        approval_ok=False,
    )
    promote, reason = decision
    assert promote is True
    assert 'gemini' in reason.lower()


def test_sensitive_target_refused_without_operator_approval():
    """A sensitive (harness/**) target must NOT be promoted without operator
    approval, even with the flag on and the ceiling reached."""
    import harness.orchestrator_worker as worker

    decide = getattr(worker, '_single_agent_promotion_decision', None)
    assert decide is not None, (
        'P5b must expose orchestrator_worker._single_agent_promotion_decision'
    )
    promote, reason = decide(
        config={'synthesis': {'enable_single_agent_promotion': True,
                              'single_agent_promotion_ceiling': 3}},
        task={'task_id': 't2', 'meta_task_type': 'harness_self_fix',
              'files_touched': ['harness/orchestrator.py']},
        state_dir=None,
        valid_agent='claude',
        valid_code='def f():\n    return 1\n',
        failing_agent='gemini',
        failing_violations=[],
        consecutive_failures=3,
        approval_ok=False,   # no operator decision present
    )
    assert promote is False, (
        'sensitive harness/** target must be REFUSED single-agent promotion '
        'without operator approval'
    )


def test_flag_off_never_promotes():
    """Default-off: with the flag false, promotion is never offered."""
    import harness.orchestrator_worker as worker
    decide = getattr(worker, '_single_agent_promotion_decision', None)
    assert decide is not None, (
        'P5b must expose orchestrator_worker._single_agent_promotion_decision'
    )
    promote, _reason = decide(
        config={'synthesis': {'enable_single_agent_promotion': False,
                              'single_agent_promotion_ceiling': 3}},
        task={'task_id': 't3', 'meta_task_type': 'validation',
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
