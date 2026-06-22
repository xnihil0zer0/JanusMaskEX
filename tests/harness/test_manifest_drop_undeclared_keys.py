"""Hermetic RED oracle for the tolerant-manifest behaviour.

Locks in the new contract on ``harness.orchestrator``:

* an undeclared ``__JANUSMASK_MANIFEST__`` key is DROPPED (with a WARNING)
  instead of hard-rejected with ``manifest_undeclared_key``;
* the MISSING-key direction still rejects with ``manifest_incomplete``;
* the new top-level helper ``_restrict_sidecar_to_declared`` restricts the
  ``state/output/<task_id>.files.json`` sidecar to the declared subset.

This is a hermetic unit oracle, NOT an integration test: it uses tmp_path
only, touches no real git / daemon / network / state tree, and drives the
REAL ``_validate_submission`` and the REAL ``_restrict_sidecar_to_declared``
directly.

RED today: the module-top import of ``_restrict_sidecar_to_declared`` fails
(symbol does not exist yet) and the validator currently rejects an undeclared
key. Both flip GREEN once the tolerant-manifest change lands.
"""
import json
import logging
import harness.orchestrator as orchestrator
from harness.orchestrator import _validate_submission, _parse_manifest, _restrict_sidecar_to_declared
_ORCH_LOGGER = orchestrator.logger.name
FOO_SRC = 'def f():\n    return 1\n'
BAR_SRC = 'def g():\n    return 2\n'
YAML_SRC = 'k: v\n'

def _make_manifest_code(mapping):
    """Serialize {rel_path: source} into a __JANUSMASK_MANIFEST__ assignment.

    ``repr`` of a ``dict[str, str]`` yields a literal whose keys/values are all
    string ``Constant`` nodes, which is exactly what ``_parse_manifest`` accepts.
    """
    return '__JANUSMASK_MANIFEST__ = ' + repr(dict(mapping)) + '\n'

def _dropped_key_warning_present(caplog, key='config/foo.yaml'):
    """True iff a WARNING record names the dropped/undeclared key."""
    for rec in caplog.records:
        if rec.levelno == logging.WARNING:
            msg = rec.getMessage()
            if key in msg or 'undeclared' in msg.lower() or 'dropped' in msg.lower():
                return True
    return False

def test_validate_submission_drops_undeclared_key_and_passes():
    code = _make_manifest_code({'harness/foo.py': FOO_SRC, 'config/foo.yaml': YAML_SRC})
    task = {'files_touched': ['harness/foo.py'], 'meta_task_type': 'harness_self_fix'}
    assert _parse_manifest(code) == {'harness/foo.py': FOO_SRC, 'config/foo.yaml': YAML_SRC}
    ok, violations = _validate_submission(code, 'claude', task)
    assert ok is True
    assert not any((getattr(v, 'rule', None) == 'manifest_undeclared_key' for v in violations))

def test_validate_submission_effective_manifest_is_declared_subset_only(caplog):
    code = _make_manifest_code({'harness/foo.py': FOO_SRC, 'config/foo.yaml': YAML_SRC})
    task = {'files_touched': ['harness/foo.py'], 'meta_task_type': 'harness_self_fix'}
    with caplog.at_level(logging.INFO, logger=_ORCH_LOGGER):
        ok, violations = _validate_submission(code, 'claude', task)
    assert ok is True
    info_msgs = [r.getMessage() for r in caplog.records if r.levelno == logging.INFO]
    assert not any(('manifest entry config/' in m for m in info_msgs))
    assert _dropped_key_warning_present(caplog)

def test_validate_submission_emits_warning_naming_dropped_key(caplog):
    code = _make_manifest_code({'harness/foo.py': FOO_SRC, 'config/foo.yaml': YAML_SRC})
    task = {'files_touched': ['harness/foo.py'], 'meta_task_type': 'harness_self_fix'}
    with caplog.at_level(logging.INFO, logger=_ORCH_LOGGER):
        ok, _violations = _validate_submission(code, 'claude', task)
    assert ok is True
    assert _dropped_key_warning_present(caplog)

def test_validate_submission_missing_key_still_rejects_manifest_incomplete():
    code = _make_manifest_code({'harness/foo.py': FOO_SRC})
    task = {'files_touched': ['harness/foo.py', 'harness/bar.py'], 'meta_task_type': 'harness_self_fix'}
    ok, violations = _validate_submission(code, 'claude', task)
    assert ok is False
    assert any((getattr(v, 'rule', None) == 'manifest_incomplete' for v in violations))

def test_validate_submission_clean_manifest_passes_unchanged_no_warning(caplog):
    code = _make_manifest_code({'harness/foo.py': FOO_SRC, 'harness/bar.py': BAR_SRC})
    task = {'files_touched': ['harness/foo.py', 'harness/bar.py'], 'meta_task_type': 'harness_self_fix'}
    with caplog.at_level(logging.INFO, logger=_ORCH_LOGGER):
        ok, violations = _validate_submission(code, 'claude', task)
    assert ok is True
    rules = {getattr(v, 'rule', None) for v in violations}
    assert 'manifest_undeclared_key' not in rules
    assert 'manifest_incomplete' not in rules
    assert not _dropped_key_warning_present(caplog)

def test_restrict_sidecar_to_declared_drops_stray_key_and_rewrites_subset(tmp_path):
    sidecar = tmp_path / 'state' / 'output' / 'manifest-task.files.json'
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    original = {'harness/foo.py': FOO_SRC, 'config/foo.yaml': YAML_SRC}
    sidecar.write_text(json.dumps(original, indent=2, sort_keys=True) + '\n')
    dropped = _restrict_sidecar_to_declared(sidecar, ['harness/foo.py'])
    assert dropped == ['config/foo.yaml']
    on_disk = json.loads(sidecar.read_text())
    assert on_disk == {'harness/foo.py': FOO_SRC}

def test_restrict_sidecar_to_declared_noop_when_all_keys_declared(tmp_path):
    sidecar = tmp_path / 'state' / 'output' / 'clean-task.files.json'
    sidecar.parent.mkdir(parents=True, exist_ok=True)
    sidecar.write_text(json.dumps({'harness/foo.py': FOO_SRC}))
    before = sidecar.read_bytes()
    dropped = _restrict_sidecar_to_declared(sidecar, ['harness/foo.py'])
    after = sidecar.read_bytes()
    assert dropped == []
    assert before == after

def test_restrict_sidecar_to_declared_robust_to_malformed_or_nondict_sidecar(tmp_path):
    malformed = tmp_path / 'malformed.files.json'
    malformed.write_text('{not json')
    assert _restrict_sidecar_to_declared(malformed, ['harness/foo.py']) == []
    nondict = tmp_path / 'nondict.files.json'
    nondict.write_text('[1, 2, 3]')
    assert _restrict_sidecar_to_declared(nondict, ['harness/foo.py']) == []