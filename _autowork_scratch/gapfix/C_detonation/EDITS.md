# Gap C — exact edits to `ngv2/workers/detonate.py` (apply to HEAD)

Makes the detonate worker's `_classify` SEMANTIC + fail-closed. Two edits, one
file. Preserves explicit-flag precedence (the live `_runner.py` seam path is
unchanged); only the crash/exit-code fallback tail is replaced so that a
genuine FS-signature reproduction confirms and a bare crash does NOT.

## Edit C.1 — add module constants after the `_SIGNAL_FIELDS` block (~line 42)

Insert after the existing `_SIGNAL_FIELDS = (...)` line:
```python
_FS_DIFF_FIELDS = ('fs_snapshot_diff', 'fs_diff', 'fs_snapshot', 'snapshot_diff')
_DEFAULT_MARKER = 'VULNERABLE'
_DEFAULT_FS_SIGNATURE = 'pwned_marker'
```

## Edit C.2 — replace the crash/exit-code tail of `_classify` (~lines 231-241)

OLD:
```python
    crashed = bool(_lookup(normalized, _CRASHED_FIELDS, False))
    exit_code = _lookup(normalized, _EXIT_CODE_FIELDS)
    if crashed:
        return (_OUTCOME_SUCCESS, error_message)
    if exit_code is not None:
        try:
            triggered = int(exit_code) != 0
        except (TypeError, ValueError):
            triggered = bool(exit_code)
        return (_OUTCOME_SUCCESS if triggered else _OUTCOME_FAILURE, error_message)
    return (_OUTCOME_FAILURE, error_message)
```
NEW:
```python
    exit_code = _lookup(normalized, _EXIT_CODE_FIELDS)
    fs_diff = _lookup(normalized, _FS_DIFF_FIELDS)
    stdout = _lookup(normalized, _STDOUT_FIELDS, '') or ''
    stderr = _lookup(normalized, _STDERR_FIELDS, '') or ''
    marker = _lookup(normalized, ('success_marker', 'marker'), _DEFAULT_MARKER)
    fs_sig = _lookup(normalized, ('expected_fs_signature', 'fs_signature'), _DEFAULT_FS_SIGNATURE)
    has_semantic_evidence = fs_diff is not None or (marker and (marker in stdout or marker in stderr))
    if has_semantic_evidence:
        try:
            from ngv2.detonation import semantic_verdict
        except Exception:
            semantic_verdict = None
        if semantic_verdict is not None:
            try:
                ec = int(exit_code) if exit_code is not None else None
            except (TypeError, ValueError):
                ec = None if exit_code is None else 1
            verdict = semantic_verdict(ec, str(stdout), str(stderr), str(fs_diff or ''), success_marker=str(marker), expected_fs_signature=str(fs_sig))
            return (_OUTCOME_SUCCESS if verdict == 'confirmed' else _OUTCOME_FAILURE, error_message)
    crashed = bool(_lookup(normalized, _CRASHED_FIELDS, False))
    if crashed:
        return (_OUTCOME_FAILURE, error_message)
    return (_OUTCOME_FAILURE, error_message)
```

NOTE: verify the exact field names `_STDOUT_FIELDS`, `_STDERR_FIELDS`, `_EXIT_CODE_FIELDS`,
`_CRASHED_FIELDS`, `_lookup`, `_OUTCOME_SUCCESS`, `_OUTCOME_FAILURE`, `error_message`,
`normalized`, and the `_SIGNAL_FIELDS` anchor exist in HEAD before applying; adapt the
anchor line numbers if HEAD drifted.

Oracle (already in scratch): `test_detonation_semantic_verdict.py`. Verified by agent C:
RED on HEAD (4 fail = the false-neg + false-pos cases), GREEN after (8/8 new; existing
test_detonate + test_detonation + test_detonation_evidence_gate_wired = 32 passed).

## CONTRACT a reproducing PoC must satisfy (used by B's payloads)
exit code 0 AND marker `VULNERABLE` on stdout/stderr AND substring `pwned_marker`
in the work_dir-relative fs-diff (canonical: write a CWD file whose name contains
`pwned_marker`). Success oracle is exactly `ngv2.detonation.semantic_verdict(...) == 'confirmed'`.
