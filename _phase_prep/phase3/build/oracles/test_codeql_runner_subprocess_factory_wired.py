"""RED oracle for ngv2.codeql_runner.make_subprocess_runner (EDIT leaf B1).

The real subprocess-backed runner: builds ``[codeql_bin] + argv`` and yields the
(rc, out, err, sarif) 4-tuple, parsing SARIF from stdout when the argv requests
sarif output. The oracle scripts ``subprocess.run`` so it NEVER spawns codeql.
Also pins that the existing builders feed argv the factory can run end-to-end.
"""
import json
import subprocess

from ngv2.codeql_runner import (
    make_subprocess_runner,
    create_database,
    run_security_queries,
)


def test_factory_builds_argv_and_parses_sarif(monkeypatch):
    captured = {}
    sarif_doc = {'runs': [{'tool': {'driver': {'rules': []}}, 'results': []}]}

    class _CP:
        returncode = 0
        stdout = json.dumps(sarif_doc)
        stderr = ''

    def fake_run(full_argv, **kwargs):
        captured['argv'] = full_argv
        captured['kwargs'] = kwargs
        return _CP()

    monkeypatch.setattr(subprocess, 'run', fake_run)
    runner = make_subprocess_runner('/opt/codeql/codeql')
    rc, out, err, sarif = runner(['database', 'analyze', 'db',
                                  '--format=sarif-latest', '--output=-'])
    assert rc == 0
    assert captured['argv'][0] == '/opt/codeql/codeql'
    assert captured['argv'][1:4] == ['database', 'analyze', 'db']
    assert sarif == sarif_doc  # parsed from stdout


def test_factory_non_sarif_command_yields_no_sarif(monkeypatch):
    class _CP:
        returncode = 0
        stdout = 'Created database.'
        stderr = ''

    monkeypatch.setattr(subprocess, 'run', lambda *a, **k: _CP())
    runner = make_subprocess_runner('codeql')
    rc, out, err, sarif = runner(['database', 'create', 'db',
                                  '--language=python', '--source-root', '/x'])
    assert rc == 0
    assert sarif is None


def test_factory_failure_is_fail_closed(monkeypatch):
    def boom(*a, **k):
        raise OSError('codeql not found')

    monkeypatch.setattr(subprocess, 'run', boom)
    runner = make_subprocess_runner('codeql')
    rc, out, err, sarif = runner(['database', 'analyze', 'db', '--format=sarif-latest'])
    assert rc != 0
    assert sarif is None


def test_existing_builders_drive_the_factory(monkeypatch):
    # create_database + run_security_queries build argv the factory runs
    sarif_doc = {'runs': [{'tool': {'driver': {'rules': []}}, 'results': []}]}

    def fake_run(full_argv, **kwargs):
        class _CP:
            returncode = 0
            stdout = json.dumps(sarif_doc) if '--format=sarif-latest' in full_argv else ''
            stderr = ''
        return _CP()

    monkeypatch.setattr(subprocess, 'run', fake_run)
    runner = make_subprocess_runner('codeql')
    db = create_database('/tmp/repo', 'python', runner)
    assert db == 'repo-python'
    findings = run_security_queries(db, 'python', runner)
    assert findings == []
