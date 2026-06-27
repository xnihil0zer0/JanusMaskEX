"""RED oracle for ngv2.codeql_orchestrate.analyze_repo (Stage-2 glue).

Injected runner only -- NEVER spawns real codeql. Proves: license-token
enforcement (fail closed), create->security-suite->bundled-specs orchestration,
dedup incl. a CWE-502 path, and the repo@sha DB cache (second call builds 0 DBs).
"""
import json

import pytest

from ngv2.codeql_orchestrate import analyze_repo
from ngv2.codeql_preflight import make_pass_token

_SARIF_502 = {'runs': [{
    'tool': {'driver': {'rules': [{
        'id': 'py/unsafe-deserialization',
        'defaultConfiguration': {'level': 'error'},
        'shortDescription': {'text': 'Unsafe deserialization'},
        'properties': {'tags': ['security', 'external/cwe/cwe-502']},
    }]}},
    'results': [{
        'ruleId': 'py/unsafe-deserialization',
        'message': {'text': 'pickle.loads on request body'},
        'locations': [{'physicalLocation': {
            'artifactLocation': {'uri': 'app/runner.py'},
            'region': {'startLine': 88}}}],
    }],
}]}


def _runner_factory(create_counter):
    def runner(argv):
        verb = argv[1] if len(argv) > 1 else ''
        if verb == 'create':
            create_counter.append(1)
            return (0, 'created', '', None)
        if verb == 'analyze':
            return (0, json.dumps(_SARIF_502), '', _SARIF_502)
        return (0, '', '', None)
    return runner


def _token(owner='bentoml', repo='BentoML'):
    return make_pass_token(owner, repo, 'apache-2.0')


def test_refuses_without_valid_token():
    with pytest.raises(PermissionError):
        analyze_repo('/tmp/clone', 'python', _runner_factory([]),
                     pass_token='garbage', owner='bentoml', repo='BentoML')


def test_orchestrates_and_dedups_cwe502_path():
    findings = analyze_repo('/tmp/clone', 'python', _runner_factory([]),
                            pass_token=_token(), owner='bentoml', repo='BentoML')
    assert findings, 'expected at least one finding'
    # security-extended + every bundled spec return the same SARIF -> dedup to 1
    assert len(findings) == 1
    f = findings[0]
    assert f['cwe'] == ['CWE-502']
    assert f['file'] == 'app/runner.py' and f['line'] == 88
    assert 'query_source' in f


def test_db_cache_skips_rebuild_on_same_sha():
    counter = []
    cache = {}
    runner = _runner_factory(counter)
    common = dict(pass_token=_token(), owner='bentoml', repo='BentoML',
                  repo_sha='abc123', db_cache=cache)
    analyze_repo('/tmp/clone', 'python', runner, **common)
    assert sum(counter) == 1  # built once
    analyze_repo('/tmp/clone', 'python', runner, **common)
    assert sum(counter) == 1  # second call reused cached DB -> 0 new builds
