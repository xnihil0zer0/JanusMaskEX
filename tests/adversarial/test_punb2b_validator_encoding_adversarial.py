"""P-UNB2(b) RED oracle: _validate_submission accepts mismatched encodings.

Reproduces the second multi-file-nondeterminism root cause in
``harness/orchestrator._validate_submission``.

For a ``partial_edit`` task (or one whose ``meta_task_type`` is in
``BYPASS_FUZZER_TYPES``), a submission that contains a ``__JANUSMASK_PATCHES__``
block is validated as patches; but a submission that does NOT contain that block
silently falls through to WHOLE-FILE AST validation and is accepted. So the two
competing agents can diverge on encoding -- one emits ``__JANUSMASK_PATCHES__``,
the other emits whole-file source -- and BOTH ``_validate_submission`` calls
return ``valid=True``. Downstream the committer encodes them differently
(patches.json vs files.json), producing nondeterministic / divergent commits
(the prior hand-land).

DETERMINISTIC OUTCOME (must hold after fix): on a ``partial_edit`` task, a
whole-file submission (no parseable ``__JANUSMASK_PATCHES__``) must be REJECTED
with an error-severity violation so the AST-retry loop forces both agents onto
the patches encoding. These tests FAIL on HEAD (the whole-file submission is
accepted) and would pass after the fix.
"""
import pytest

from harness.orchestrator import _validate_submission


WHOLE_FILE = 'def foo(x):\n    return x + 1\n'

PATCHES = (
    '__JANUSMASK_PATCHES__ = [\n'
    '    {\n'
    '        "file": "harness/git_integration.py",\n'
    '        "kind": "symbol",\n'
    '        "name": "foo",\n'
    '        "code": "def foo(x):\\n    return x + 1\\n",\n'
    '    },\n'
    ']\n'
)


def _task():
    return {
        'task_id': 'rev26_punb2b_demo',
        'partial_edit': True,
        'meta_task_type': 'harness_self_fix',
        'files_touched': ['harness/git_integration.py'],
    }


_SINGLE_FILE = 'def alpha() -> int:\n    return 1\n'


def test_partial_edit_rejects_whole_file_encoding():
    """A partial_edit submission lacking __JANUSMASK_PATCHES__ must be rejected."""
    valid, violations = _validate_submission(WHOLE_FILE, 'claude', _task())
    assert not valid, (
        'whole-file submission on a partial_edit task was ACCEPTED -- it must be '
        'rejected so the AST-retry loop forces the patches encoding; got '
        f'violations={[(v.rule, v.severity) for v in violations]}'
    )
    assert any(v.severity == 'error' for v in violations), (
        'expected an error-severity encoding-mismatch violation, got '
        f'{[(v.rule, v.severity) for v in violations]}'
    )


def test_partial_edit_two_agents_cannot_both_validate_on_divergent_encodings():
    """The encoding-divergence the bug enables: both agents validate True."""
    task = _task()
    v_whole, _ = _validate_submission(WHOLE_FILE, 'claude', task)
    v_patch, _ = _validate_submission(PATCHES, 'gemini', task)
    # The patches encoding must stay valid (positive control).
    assert v_patch, 'patches-encoded submission unexpectedly rejected'
    # The whole-file encoding must NOT also validate -- otherwise the two agents
    # diverge on encoding yet both pass. On HEAD v_whole is True (RED).
    assert not v_whole, (
        'BOTH the whole-file and patches encodings validate on the same '
        'partial_edit task -> nondeterministic divergent commit. The validator '
        'must reject the whole-file encoding.'
    )


# --- SCOPE-BOUNDARY guards (GREEN on HEAD and after the fix) -----------------
# These encode the exact line the fix must NOT cross: the new patches_required
# rejection is gated on task.get('partial_edit') ONLY, never on the broader
# 'partial_edit OR mtt in BYPASS_FUZZER_TYPES'. They mirror the contracts in
# tests/adversarial/test_orchestrator_manifest_required.py so the two suites
# cannot drift into conflict (the prior pipeline attempt was rejected for
# over-broadening into exactly these branches).


def test_bypass_non_partial_edit_single_file_stays_accepted():
    """harness_self_fix (in BYPASS_FUZZER_TYPES) but NOT partial_edit + a
    single-file whole-file body must stay ACCEPTED via the single-file
    fallback -- it must NOT be rejected as patches_required."""
    task = {
        'task_id': 'rev26_punb2b_bypass_single',
        'meta_task_type': 'harness_self_fix',
        'files_touched': ['a.py'],
    }
    valid, violations = _validate_submission(_SINGLE_FILE, 'claude', task)
    assert valid, (
        'a BYPASS-type but non-partial_edit single-file whole-file submission '
        'must stay valid (patches_required must be gated on partial_edit only); '
        f'got violations={[(v.rule, v.severity) for v in violations]}'
    )
    assert not any(v.rule == 'patches_required' for v in violations)


def test_bypass_non_partial_edit_multifile_stays_manifest_missing():
    """harness_self_fix (in BYPASS_FUZZER_TYPES) but NOT partial_edit + a
    multi-file whole-file body must reject with rule='manifest_missing'
    (NOT 'patches_required')."""
    task = {
        'task_id': 'rev26_punb2b_bypass_multi',
        'meta_task_type': 'harness_self_fix',
        'files_touched': ['a.py', 'b.py'],
    }
    valid, violations = _validate_submission(_SINGLE_FILE, 'claude', task)
    assert not valid
    rules = {v.rule for v in violations if v.severity == 'error'}
    assert 'manifest_missing' in rules, (
        f"multi-file non-partial_edit must stay manifest_missing; got {rules!r}"
    )
    assert 'patches_required' not in rules, (
        'the fix must NOT emit patches_required on a non-partial_edit multi-file '
        f'task; got {rules!r}'
    )
