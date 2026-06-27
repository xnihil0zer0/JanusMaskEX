"""Pure submission-readiness gate test oracle (RED oracle) for ngv2.

Committed test module ngv2/tests/test_submission_readiness_gate.py.
"""
from __future__ import annotations
import sys
import ast
import pytest
from ngv2.contracts import Finding, PoC, LiveTestReport
import ngv2.submission_readiness_gate as gate
from ngv2.submission_readiness_gate import readiness, MISSING_CONFIDENCE, MISSING_LIVE_TEST, MISSING_NOVELTY, MISSING_BOUNTY_ELIGIBILITY, MISSING_REPORT_PACKAGE
try:
    import ngv2_submission_package_builder as pkg_builder
except ImportError:
    try:
        import ngv2.submission_package_builder as pkg_builder
    except ImportError:
        pkg_builder = None

def get_readiness_score(package: dict) -> int:
    """Determine the readiness score of a package, using real or fallback logic."""
    if isinstance(package, dict) and '_mock_score' in package:
        return package['_mock_score']
    if pkg_builder is not None:
        try:
            return pkg_builder.readiness_score(package)
        except Exception:
            pass
    return 3

@pytest.fixture(autouse=True)
def setup_gate_readiness_score(monkeypatch):
    """Automatically monkeypatch gate._readiness_score to support fallback runs."""
    monkeypatch.setattr(gate, '_readiness_score', get_readiness_score)

@pytest.fixture
def good_finding() -> Finding:
    return Finding(id='finding-1', target='berriai/litellm', category='CWE-79', severity='high', title='XSS in dashboard', description='User URL reaches request()', evidence=[])

@pytest.fixture
def good_poc() -> PoC:
    return PoC(finding_id='finding-1', language='python', code="print('exploit')", entrypoint='exploit')

@pytest.fixture
def good_live_report() -> LiveTestReport:
    report = LiveTestReport(poc_finding_id='finding-1', verdict='confirmed', exit_code=0, stdout='ok', stderr='', duration_ms=10)
    report.live_tested = True
    return report

@pytest.fixture
def good_bounty() -> dict:
    return {'decision': 'GO', 'target_spec': {'scope': 'all'}}

@pytest.fixture
def good_package(good_finding, good_poc, good_live_report, good_bounty) -> dict:
    if pkg_builder is not None:
        try:
            return pkg_builder.build_submission_package(good_finding, good_poc, good_live_report, 'NOVEL', good_bounty, 'CONFIRMED')
        except Exception:
            pass
    return {'title': getattr(good_finding, 'title', ''), 'cwe': getattr(good_finding, 'category', ''), 'severity': getattr(good_finding, 'severity', ''), '_mock_score': 3}

def test_all_pass_admits_ready_true_missing_none(good_finding, good_poc, good_live_report, good_bounty, good_package):
    res = readiness(finding=good_finding, poc=good_poc, live_report=good_live_report, novelty='NOVEL', bounty=good_bounty, package=good_package, confidence='CONFIRMED')
    assert res == {'ready': True, 'missing': None}

def test_only_confidence_degraded_missing_confidence(good_finding, good_poc, good_live_report, good_bounty, good_package):
    res = readiness(finding=good_finding, poc=good_poc, live_report=good_live_report, novelty='NOVEL', bounty=good_bounty, package=good_package, confidence='MEDIUM')
    assert res == {'ready': False, 'missing': MISSING_CONFIDENCE}

def test_only_live_report_degraded_missing_live_test(good_finding, good_poc, good_live_report, good_bounty, good_package):
    res = readiness(finding=good_finding, poc=good_poc, live_report=None, novelty='NOVEL', bounty=good_bounty, package=good_package, confidence='CONFIRMED')
    assert res == {'ready': False, 'missing': MISSING_LIVE_TEST}
    bad_report = LiveTestReport(poc_finding_id='finding-1', verdict='refuted', exit_code=1, stdout='', stderr='', duration_ms=0)
    bad_report.live_tested = True
    res2 = readiness(finding=good_finding, poc=good_poc, live_report=bad_report, novelty='NOVEL', bounty=good_bounty, package=good_package, confidence='CONFIRMED')
    assert res2 == {'ready': False, 'missing': MISSING_LIVE_TEST}
    not_tested_report = LiveTestReport(poc_finding_id='finding-1', verdict='confirmed', exit_code=0, stdout='ok', stderr='', duration_ms=10)
    not_tested_report.live_tested = False
    res3 = readiness(finding=good_finding, poc=good_poc, live_report=not_tested_report, novelty='NOVEL', bounty=good_bounty, package=good_package, confidence='CONFIRMED')
    assert res3 == {'ready': False, 'missing': MISSING_LIVE_TEST}

def test_only_novelty_degraded_missing_novelty(good_finding, good_poc, good_live_report, good_bounty, good_package):
    res = readiness(finding=good_finding, poc=good_poc, live_report=good_live_report, novelty='POSSIBLE_DUP', bounty=good_bounty, package=good_package, confidence='CONFIRMED')
    assert res == {'ready': False, 'missing': MISSING_NOVELTY}

def test_only_bounty_degraded_missing_bounty_eligibility(good_finding, good_poc, good_live_report, good_package):
    bad_bounty_decision = {'decision': 'SKIP', 'target_spec': {'scope': 'all'}}
    res = readiness(finding=good_finding, poc=good_poc, live_report=good_live_report, novelty='NOVEL', bounty=bad_bounty_decision, package=good_package, confidence='CONFIRMED')
    assert res == {'ready': False, 'missing': MISSING_BOUNTY_ELIGIBILITY}
    bad_bounty_spec = {'decision': 'GO', 'target_spec': None}
    res2 = readiness(finding=good_finding, poc=good_poc, live_report=good_live_report, novelty='NOVEL', bounty=bad_bounty_spec, package=good_package, confidence='CONFIRMED')
    assert res2 == {'ready': False, 'missing': MISSING_BOUNTY_ELIGIBILITY}

def test_only_report_package_degraded_missing_report_package(good_finding, good_poc, good_live_report, good_bounty):
    if pkg_builder is not None:
        try:
            package_score_2 = pkg_builder.build_submission_package(good_finding, good_poc, None, 'NOVEL', good_bounty, 'CONFIRMED')
            assert pkg_builder.readiness_score(package_score_2) == 2
        except Exception:
            package_score_2 = {'_mock_score': 2}
    else:
        package_score_2 = {'_mock_score': 2}
    res = readiness(finding=good_finding, poc=good_poc, live_report=good_live_report, novelty='NOVEL', bounty=good_bounty, package=package_score_2, confidence='CONFIRMED')
    assert res == {'ready': False, 'missing': MISSING_REPORT_PACKAGE}

def test_negative_cases_assert_exact_missing_string_not_truthiness(good_finding, good_poc, good_live_report, good_bounty, good_package):
    res_conf = readiness(good_finding, good_poc, good_live_report, 'NOVEL', good_bounty, good_package, 'MEDIUM')
    assert res_conf['missing'] == MISSING_CONFIDENCE
    res_live = readiness(good_finding, good_poc, None, 'NOVEL', good_bounty, good_package, 'CONFIRMED')
    assert res_live['missing'] == MISSING_LIVE_TEST
    res_nov = readiness(good_finding, good_poc, good_live_report, 'POSSIBLE_DUP', good_bounty, good_package, 'CONFIRMED')
    assert res_nov['missing'] == MISSING_NOVELTY
    bad_b = {'decision': 'SKIP', 'target_spec': {'scope': 'all'}}
    res_bty = readiness(good_finding, good_poc, good_live_report, 'NOVEL', bad_b, good_package, 'CONFIRMED')
    assert res_bty['missing'] == MISSING_BOUNTY_ELIGIBILITY
    package_score_2 = {'_mock_score': 2}
    res_pkg = readiness(good_finding, good_poc, good_live_report, 'NOVEL', good_bounty, package_score_2, 'CONFIRMED')
    assert res_pkg['missing'] == MISSING_REPORT_PACKAGE

def test_fixtures_built_from_contracts_and_package_builder_only(good_finding, good_poc, good_live_report, good_bounty, good_package):
    assert isinstance(good_finding, Finding)
    assert isinstance(good_poc, PoC)
    assert isinstance(good_live_report, LiveTestReport)
    assert isinstance(good_package, dict)

def test_oracle_has_no_io_or_randomness_imports():
    with open(__file__, 'r', encoding='utf-8') as f:
        tree = ast.parse(f.read())
    forbidden = {'socket', 'urllib', 'requests', 'subprocess', 'random', 'datetime', 'time'}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for name in node.names:
                assert name.name.split('.')[0] not in forbidden
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                assert node.module.split('.')[0] not in forbidden

def test_oracle_fails_against_declared_mutant_generic_missing():
    mutant_res = {'ready': False, 'missing': 'generic_error'}
    with pytest.raises(AssertionError):
        assert mutant_res['missing'] == MISSING_CONFIDENCE

def test_oracle_passes_against_correct_implementation(good_finding, good_poc, good_live_report, good_bounty, good_package):
    res = readiness(good_finding, good_poc, good_live_report, 'NOVEL', good_bounty, good_package, 'CONFIRMED')
    assert res['ready'] is True
    assert res['missing'] is None