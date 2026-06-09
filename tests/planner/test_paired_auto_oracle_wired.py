"""RED oracle for the paired-auto-oracle exemption to the wiring-oracle rule
(harness_self_fix: wiring_oracle_paired_exemption).

Contract: a module-creating impl leaf whose verification_command does NOT name a
``*_wired`` test is normally rejected with ``missing_wiring_oracle``. BUT when the
SAME plan contains a paired ``test_authoring`` oracle whose ``mutation_target``
resolves to the module the impl creates, the impl is EXEMPT -- the auto-authored
oracle (built impl-first, then mutation-gated) IS the module's wiring/contract
proof, so the impl's own verification_command may be a smoke check.

Rationale: the auto-oracle's non-vacuity gate mutates the module-under-test, so the
module must exist before the oracle is authored (the normalizer's
``_enforce_module_first`` forces impl-first). That makes it structurally impossible
for the impl to be verified by the not-yet-authored ``*_wired`` test. This exemption
reconciles the auto-oracle flow with the wiring gate for NEW-FILE modules.

We assert specifically on the presence/absence of the ``missing_wiring_oracle`` code
so the tests are robust to any other unrelated violations the plan may carry.
"""
from harness.planner.plan_validator import validate_plan


def _impl(*, vcmd, files, task_id="IMPL_1", deps=()):
    return {
        "task_id": task_id,
        "title": "create a new module",
        "meta_task_type": "orchestration",
        "priority": 1,
        "dependencies": list(deps),
        "files_touched": files,
        "acceptance_criteria": ["module exists"],
        "spec_author": "test",
        "estimated_complexity": "S",
        "verification_command": vcmd,
    }


def _oracle(*, mutation_target, files, task_id="ORACLE_1", deps=()):
    return {
        "task_id": task_id,
        "title": "author oracle",
        "meta_task_type": "test_authoring",
        "mutation_target": mutation_target,
        "priority": 1,
        "dependencies": list(deps),
        "files_touched": files,
        "acceptance_criteria": ["oracle fails on mutant"],
        "spec_author": "test",
        "estimated_complexity": "S",
        "verification_command": "python -m pytest %s -q" % files[0],
    }


def _plan(*tasks):
    return {"plan_kind": "implementation", "tasks": list(tasks)}


def _codes(violations):
    return {v.code for v in violations}


def test_impl_with_paired_auto_oracle_is_exempt():
    # impl creates ngv2/analyzer.py with a smoke vcmd (no *_wired), but a paired
    # test_authoring oracle targets ngv2.analyzer -> exempt from missing_wiring_oracle.
    impl = _impl(vcmd='python -c "import ngv2.analyzer"', files=["ngv2/analyzer.py"], deps=["ORACLE_1"])
    oracle = _oracle(mutation_target="ngv2.analyzer", files=["tests/test_analyzer_wired.py"])
    assert "missing_wiring_oracle" not in _codes(validate_plan(_plan(impl, oracle)))


def test_impl_without_paired_oracle_still_rejected():
    # No paired oracle for ngv2.analyzer -> the rule still fires.
    impl = _impl(vcmd='python -c "import ngv2.analyzer"', files=["ngv2/analyzer.py"])
    assert "missing_wiring_oracle" in _codes(validate_plan(_plan(impl)))


def test_paired_oracle_for_different_module_does_not_exempt():
    # Oracle targets a DIFFERENT module -> impl still rejected.
    impl = _impl(vcmd='python -c "import ngv2.analyzer"', files=["ngv2/analyzer.py"])
    oracle = _oracle(mutation_target="ngv2.handlers", files=["tests/test_handlers_wired.py"])
    assert "missing_wiring_oracle" in _codes(validate_plan(_plan(impl, oracle)))


def test_explicit_wired_oracle_still_passes():
    # The pre-existing satisfaction path (impl names a *_wired test) is unchanged.
    impl = _impl(vcmd="python -m pytest tests/test_analyzer_wired.py -q", files=["ngv2/analyzer.py"])
    assert "missing_wiring_oracle" not in _codes(validate_plan(_plan(impl)))
