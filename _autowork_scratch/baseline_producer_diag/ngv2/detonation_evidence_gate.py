"""Deterministic, fail-closed detonation-evidence-kind gate.

This pure module classifies the EVIDENCE KIND behind a detonation report
(``live_execution`` | ``static_assertion`` | ``mock_execution``) and forbids a
``"confirmed"`` verdict unless the target was actually executed at runtime.

It closes the verified defect where a regex/AST source-pattern PoC was
mislabeled a "live detonation" and reported "confirmed": a pure source-pattern
assertion is never a detonation, and running against a self-hosted mock is
never running against the real target.

The module is PURE: it runs/fuzzes/detonates nothing and performs no I/O,
network, subprocess, filesystem, source parsing, target import, wall-clock,
randomness, or module-level side effects. Standard library only.

Classification precedence (fail-closed -- absent evidence is never live):

    1. method in {'regex_assert', 'ast_assert'} -> static_assertion
       (dominates every other key)
    2. elif self_hosted_mock truthy            -> mock_execution
       (a mock run can never be called live)
    3. elif ran_target AND observed_runtime_effect -> live_execution
       (the ONLY path to 'confirmed')
    4. else                                    -> static_assertion

Then ``may_confirm == (evidence_kind == 'live_execution')`` and
``downgraded_verdict == 'confirmed'`` iff ``may_confirm`` else ``'unproven'``.

Wiring contract: importing ``classify_detonation_evidence`` from this live
module is what places the gate on the NobleGreed detonation->report->verdict
chokepoint, so no report can be promoted to 'confirmed' unless this gate
returns ``may_confirm == True``.
"""
from typing import Dict
__all__ = ['classify_detonation_evidence']
_STATIC_ASSERT_METHODS = frozenset({'regex_assert', 'ast_assert'})

def classify_detonation_evidence(report: Dict) -> Dict:
    """Classify the evidence kind behind a detonation ``report``.

    The ``report`` is a plain dict that may contain any subset of the keys
    ``method``, ``ran_target``, ``target_endpoint``, ``observed_runtime_effect``,
    ``fs_effect``, ``self_hosted_mock``; every key may be absent.

    Returns a dict with EXACTLY three keys:

        * ``evidence_kind``: 'live_execution' | 'static_assertion' | 'mock_execution'
        * ``may_confirm``: bool, True iff evidence_kind == 'live_execution'
        * ``downgraded_verdict``: 'confirmed' iff may_confirm else 'unproven'
    """
    method = report.get('method')
    if method in _STATIC_ASSERT_METHODS:
        evidence_kind = 'static_assertion'
    elif report.get('self_hosted_mock'):
        evidence_kind = 'mock_execution'
    elif report.get('ran_target') and report.get('observed_runtime_effect'):
        evidence_kind = 'live_execution'
    else:
        evidence_kind = 'static_assertion'
    may_confirm = evidence_kind == 'live_execution'
    downgraded_verdict = 'confirmed' if may_confirm else 'unproven'
    return {'evidence_kind': evidence_kind, 'may_confirm': may_confirm, 'downgraded_verdict': downgraded_verdict}