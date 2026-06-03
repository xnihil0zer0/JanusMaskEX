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
