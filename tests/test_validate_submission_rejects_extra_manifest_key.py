"""RED oracle for manifest-key discipline in orchestrator._validate_submission.

A worker can emit a ``__JANUSMASK_MANIFEST__`` carrying EXTRA keys that are NOT
in the task's declared ``files_touched`` (e.g. re-including a renamed test file on
a config-only task). Those stray keys then get AST-merged/written and break the
build (a stale function survives the merge -> verification_failed). Brief prose
cannot constrain the worker; the pipeline must REJECT a manifest whose key set is
not a subset of the declared ``files_touched``.

Today ``_validate_submission`` only checks the MISSING direction (a declared file
absent from the manifest -> ``manifest_incomplete``). It does NOT reject the EXTRA
direction. These keystone tests are RED on HEAD (extra key accepted) and turn
GREEN once the symmetric extra-key rejection lands.

Regression (must stay GREEN): a manifest whose keys EXACTLY equal the declared
files_touched is still accepted.
"""
from harness import orchestrator

_PY = "def helper(x):\n    return x + 1\n"


def _manifest_code(mapping):
    """Build a top-level __JANUSMASK_MANIFEST__ = {rel: src} submission string."""
    return "__JANUSMASK_MANIFEST__ = %r\n" % (mapping,)


def test_extra_manifest_key_is_rejected():
    # KEYSTONE: declared one file, manifest carries a SECOND (stray) key.
    code = _manifest_code({
        "harness/foo.py": _PY,
        "tests/stray_extra.py": _PY,   # NOT in files_touched
    })
    task = {
        "task_id": "extra_key_task",
        "files_touched": ["harness/foo.py"],
        "meta_task_type": "harness_self_fix",
    }
    ok, violations = orchestrator._validate_submission(code, "claude", task)
    assert ok is False, "extra manifest key must be rejected"
    rules = {v.rule for v in violations}
    assert any("manifest" in r for r in rules), (
        "expected a manifest-discipline violation, got %r" % (rules,)
    )


def test_extra_key_on_single_declared_config_task_rejected():
    # The real driving scenario: a config-only task whose worker re-adds a test.
    code = _manifest_code({
        "harness/config.yaml": "workers:\n  agy_pool:\n    enabled: true\n",
        "tests/test_config_agy_pool.py": _PY,   # stray
    })
    task = {
        "task_id": "config_only_task",
        "files_touched": ["harness/config.yaml"],
        "meta_task_type": "harness_self_fix",
    }
    ok, violations = orchestrator._validate_submission(code, "claude", task)
    assert ok is False
    assert any("manifest" in v.rule for v in violations)


def test_compliant_manifest_exact_keys_accepted():
    # REGRESSION: manifest keys EXACTLY equal declared files_touched -> accepted.
    code = _manifest_code({
        "harness/foo.py": _PY,
        "harness/bar.py": _PY,
    })
    task = {
        "task_id": "compliant_task",
        "files_touched": ["harness/foo.py", "harness/bar.py"],
        "meta_task_type": "harness_self_fix",
    }
    ok, violations = orchestrator._validate_submission(code, "claude", task)
    assert ok is True, [(v.rule, v.message) for v in violations]


def test_compliant_manifest_normalized_paths_accepted():
    # REGRESSION: a leading ./ in a declared path normalizes to the same key.
    code = _manifest_code({"harness/foo.py": _PY})
    task = {
        "task_id": "compliant_norm_task",
        "files_touched": ["./harness/foo.py"],
        "meta_task_type": "harness_self_fix",
    }
    ok, violations = orchestrator._validate_submission(code, "claude", task)
    assert ok is True, [(v.rule, v.message) for v in violations]
