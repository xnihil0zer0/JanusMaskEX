"""RED behavioral oracle for the data_model differential-fuzzing policy flip.

Pins the contract that ``data_model`` meta-tasks must NO LONGER bypass the
differential fuzzer, while every type that is pinned-bypassed today stays
bypassed and the ``BYPASS_FUZZER_TYPES`` derivation-from-dict invariant holds.

This oracle is RED against HEAD (where ``data_model`` is ``bypass_fuzzer: True``)
and turns GREEN only after the paired implementation flips the single policy
flag. Expectations are derived from the live policy semantics -- nothing here
compares against a frozen copy of the whole expected bypass set, so the test is
not satisfiable by pasting an answer-key literal into both test and impl.
"""
from harness.planner.taxonomies import BYPASS_FUZZER_TYPES, META_TASK_POLICY, META_TASK_TYPES, SIDE_EFFECT_META_TYPES, SKIP_SMOKE_GATE_TYPES
from harness.orchestrator import Task, should_bypass_fuzzer

def _derive_bypass_set() -> 'frozenset[str]':
    """Recompute the bypass set from the *live* policy dict (no pasted literal)."""
    return frozenset((k for k, v in META_TASK_POLICY.items() if v['bypass_fuzzer']))

def test_data_model_flag_and_membership_flipped() -> None:
    assert 'data_model' not in BYPASS_FUZZER_TYPES
    assert META_TASK_POLICY['data_model']['bypass_fuzzer'] is False

def test_bypass_set_derives_from_policy_dict_generically() -> None:
    assert BYPASS_FUZZER_TYPES == _derive_bypass_set()

def test_representative_pinned_bypassed_types_still_bypassed() -> None:
    pinned = {'test_unit', 'test_integration', 'hooks_integration'}
    assert pinned <= BYPASS_FUZZER_TYPES

def test_should_bypass_fuzzer_false_for_data_model() -> None:
    task = Task(task_id='t', meta_task_type='data_model')
    assert should_bypass_fuzzer(task) is False

def test_every_policy_entry_membership_matches_its_flag() -> None:
    for k, v in META_TASK_POLICY.items():
        assert (k in BYPASS_FUZZER_TYPES) is bool(v['bypass_fuzzer']), k

def test_currently_non_bypassed_types_stay_out_of_bypass_set() -> None:
    non_bypassed = frozenset((k for k, v in META_TASK_POLICY.items() if not v['bypass_fuzzer']))
    assert non_bypassed
    assert non_bypassed.isdisjoint(BYPASS_FUZZER_TYPES)
    representative_non_bypassed = {'cli_tooling', 'refactor', 'logging_observability'}
    assert representative_non_bypassed <= non_bypassed
    assert representative_non_bypassed.isdisjoint(BYPASS_FUZZER_TYPES)

def test_taxonomy_derivation_invariant_remains_intact() -> None:
    assert META_TASK_TYPES == frozenset(META_TASK_POLICY.keys())
    assert BYPASS_FUZZER_TYPES == _derive_bypass_set()
    assert SIDE_EFFECT_META_TYPES == frozenset((k for k, v in META_TASK_POLICY.items() if v['skip_structural_decomp']))
    assert SKIP_SMOKE_GATE_TYPES == frozenset((k for k, v in META_TASK_POLICY.items() if v.get('skip_smoke_gates', False)))