"""RED oracle for CLAIM A — accept gemini-only LEAF plans (throughput lever).

Context: ``_check_hallucination`` discards a leaf plan whose tasks are all
``proposed_by=gemini`` with no reconciled task (``all_gemini_no_reconciled``),
forcing a full ~230s planner re-kickoff. For an EXTERNAL leaf build this discard
is wasted work: ``plan_normalizer.normalize_plan`` collapses the leaf to a single
``data_model`` task and INJECTS the committed oracle + stdlib/determinism
constraints, so a gemini-only plan normalizes to the SAME build contract as a
reconciled one. Attribution metadata is read NOWHERE in the build path except
this heuristic, so accepting these plans is build-safe; a low-quality plan still
fails its injected-oracle verification gate and rolls back (a cheaper failure
than a re-kickoff).

Fix: add an opt-in ``config`` arg to ``_check_hallucination``. When
``synthesis.accept_single_agent_leaf_plans`` is true, the ``all_gemini`` LEAF
case returns ``(False, '')`` instead of discarding. ALL other guards
(``wall<min``, ``empty_epic``, ``empty_plan``) and the default-off behavior are
preserved unchanged. Epic plans never reach the all_gemini block (they return
early on ``plan_kind == 'epic'``), so this relaxation is inherently leaf-only.
"""
from __future__ import annotations

import inspect

from harness import autowork_daemon
from harness.autowork_daemon import _check_hallucination

_ACCEPT = {'synthesis': {'accept_single_agent_leaf_plans': True}}
_REJECT = {'synthesis': {'accept_single_agent_leaf_plans': False}}


def _all_gemini_leaf() -> dict:
    return {
        'tasks': [
            {'task_id': 'T1', 'attribution_metadata': {'proposed_by': 'gemini', 'reconciled': False}},
            {'task_id': 'T2', 'attribution_metadata': {'proposed_by': 'gemini', 'reconciled': False}},
        ]
    }


def test_all_gemini_leaf_accepted_when_flag_true() -> None:
    """The lever: flag on -> a gemini-only leaf plan is NOT a hallucination."""
    halluc, why = _check_hallucination(_all_gemini_leaf(), wall_seconds=30.0, config=_ACCEPT)
    assert halluc is False, f'gemini-only leaf still discarded under flag: {why!r}'
    assert why == ''


def test_all_gemini_leaf_discarded_when_flag_false() -> None:
    halluc, why = _check_hallucination(_all_gemini_leaf(), wall_seconds=30.0, config=_REJECT)
    assert halluc is True
    assert why == 'all_gemini_no_reconciled'


def test_all_gemini_leaf_discarded_when_config_none() -> None:
    """Default-off: no config (or no flag) preserves the existing discard."""
    halluc, why = _check_hallucination(_all_gemini_leaf(), wall_seconds=30.0)
    assert halluc is True
    assert why == 'all_gemini_no_reconciled'


def test_all_gemini_leaf_discarded_when_flag_absent() -> None:
    halluc, why = _check_hallucination(_all_gemini_leaf(), wall_seconds=30.0, config={'synthesis': {}})
    assert halluc is True
    assert why == 'all_gemini_no_reconciled'


def test_empty_plan_still_hallucinated_under_flag() -> None:
    """Guard intact: an empty leaf plan is still empty_plan even with the flag on."""
    halluc, why = _check_hallucination({'tasks': []}, wall_seconds=30.0, config=_ACCEPT)
    assert halluc is True
    assert why == 'empty_plan'


def test_wall_below_min_still_hallucinated_under_flag() -> None:
    """Guard intact: a sub-min-wall plan is still wall<min even with the flag on."""
    halluc, why = _check_hallucination(_all_gemini_leaf(), wall_seconds=2.0, config=_ACCEPT)
    assert halluc is True
    assert why == 'wall<min'


def test_empty_epic_still_hallucinated_under_flag() -> None:
    """Guard intact: the flag never relaxes the epic path."""
    halluc, why = _check_hallucination({'plan_kind': 'epic', 'child_slugs': []}, wall_seconds=30.0, config=_ACCEPT)
    assert halluc is True
    assert why == 'empty_epic'


def test_reconciled_leaf_unaffected_by_flag() -> None:
    """A reconciled/claude leaf is accepted regardless of the flag (regression bar)."""
    plan = {'tasks': [{'task_id': 'T', 'attribution_metadata': {'proposed_by': 'claude', 'reconciled': True}}]}
    for cfg in (None, _ACCEPT, _REJECT):
        halluc, why = _check_hallucination(plan, wall_seconds=30.0, config=cfg)
        assert halluc is False, f'reconciled leaf wrongly discarded under cfg={cfg!r}: {why!r}'
        assert why == ''


def test_auto_promote_wires_config_and_stays_intact() -> None:
    """Structural guard: the call site threads config through AND _auto_promote is
    not truncated by the symbol-patch edit. If the large function were truncated
    (a known large-symbol risk), its late-body ledger sentinels would vanish and
    this fails -> auto-commit rolls back, protecting the live daemon."""
    src = inspect.getsource(autowork_daemon._auto_promote)
    # the wiring landed: config is threaded into THIS call (scope to a window so
    # the existing config=config on _auto_promote_brief_eligible is not matched).
    assert '_check_hallucination(' in src, 'call site missing from _auto_promote'
    idx = src.index('_check_hallucination(')
    call_region = src[idx:idx + 220]
    assert 'config=config' in call_region, 'config not threaded into _check_hallucination call'
    # not truncated: late-body emit sentinels survive intact
    assert 'plan_kickoff' in src, '_auto_promote truncated (lost plan_kickoff)'
    assert 'planner_hallucination_discarded' in src, '_auto_promote truncated (lost discard row)'
