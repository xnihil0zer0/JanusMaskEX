"""RED oracle suite for nested-symbol handling in harness.git_integration.

This suite verifies the *desired* (patched) behaviour of
``_apply_symbol_patch`` / ``_commit_accepted_output_patches``:

  * A 1-part symbol name that is actually NESTED inside a top-level
    def/class must raise a clear, typed error (ValueError or KeyError)
    whose message names the leaf, the enclosing symbol, and contains the
    keyword 'nested' -- instead of the opaque bare ``KeyError(qualname)``
    that today's code raises (so these tests are RED on HEAD).
  * A truly-absent name (neither top-level nor nested) must STILL raise a
    bare ``KeyError(qualname)`` (distinct from the nested-symbol error).
  * Normal top-level def / class / async-def and supported ``Outer.inner``
    symbol patches must STILL apply cleanly (no regression).
  * A patch failure routed through ``_commit_accepted_output_patches``
    must surface an actionable diagnostic to the
    ``state/impl_progress.jsonl`` ledger under event
    ``auto_commit_patch_failed`` carrying a ``stderr_tail`` field.

The tests drive the REAL functions; all filesystem state (worktree,
state dir, sidecar, ledger) is redirected under pytest's ``tmp_path`` so
nothing touches the live repository, and the failing-patch paths return
before any git operation runs, so no real git repository is required.
"""
import json
import pathlib
import textwrap
import pytest
from harness.git_integration import _apply_symbol_patch, _commit_accepted_output_patches
TASK_ID = 'ORACLE-NESTED-PATCH'
REL = 'mod_under_edit.py'

def _make_patch_commit(tmp_path, target_src, symbol_name, new_code, task_id=TASK_ID):
    """Drive ``_commit_accepted_output_patches`` with a single symbol patch.

    Lays out a tmp worktree containing ``REL`` and a patches sidecar that
    targets ``symbol_name``; returns ``(result_dict, state_dir)``. When the
    symbol cannot be applied the function fails BEFORE any git call, so the
    tmp dir need not be a git repo.
    """
    wt = pathlib.Path(tmp_path).resolve()
    state_dir = wt / 'state'
    out_dir = state_dir / 'output'
    out_dir.mkdir(parents=True, exist_ok=True)
    target_file = wt / REL
    target_file.write_text(target_src, encoding='utf-8')
    sidecar = out_dir / f'{task_id}.patches.json'
    sidecar.write_text(json.dumps([{'file': REL, 'kind': 'symbol', 'name': symbol_name, 'code': new_code}]), encoding='utf-8')
    result = {'committed': False, 'sha': None, 'error': None, 'target': REL}
    out = _commit_accepted_output_patches(task_id, sidecar, state_dir, wt, result, allowed_files=None, meta_task_type=None, approval_ok=False, working_dir=None)
    return (out, state_dir)

def _journal_rows(state_dir):
    """Parse every JSON line of ``state_dir/impl_progress.jsonl``."""
    jpath = pathlib.Path(state_dir) / 'impl_progress.jsonl'
    if not jpath.exists():
        return []
    rows = []
    for line in jpath.read_text(encoding='utf-8').splitlines():
        line = line.strip()
        if line:
            rows.append(json.loads(line))
    return rows

def test_nested_symbol_patch_raises_valueerror_or_keyerror():
    """A bare name nested inside a top-level def -> typed 'nested' error."""
    source = textwrap.dedent('\n        def wrapper_fn():\n            def leaf_fn():\n                return 1\n            return leaf_fn\n        ')
    new_block = 'def leaf_fn():\n    return 2\n'
    with pytest.raises((ValueError, KeyError)) as exc_info:
        _apply_symbol_patch(source, 'leaf_fn', new_block)
    msg = str(exc_info.value).lower()
    assert 'nested' in msg
    assert 'leaf_fn' in msg
    assert 'wrapper_fn' in msg

def test_nested_class_in_function_raises_typed_error():
    """A class nested inside a top-level function -> typed 'nested' error."""
    source = textwrap.dedent('\n        def factory():\n            class Widget:\n                value = 1\n            return Widget\n        ')
    new_block = 'class Widget:\n    value = 2\n'
    with pytest.raises((ValueError, KeyError)) as exc_info:
        _apply_symbol_patch(source, 'Widget', new_block)
    msg = str(exc_info.value)
    low = msg.lower()
    assert 'nested' in low
    assert 'Widget' in msg
    assert 'factory' in msg

def test_nested_async_function_raises_typed_error():
    """An async def nested inside a top-level function -> typed 'nested' error."""
    source = textwrap.dedent('\n        def host_fn():\n            async def buried_coro():\n                return 1\n            return buried_coro\n        ')
    new_block = 'async def buried_coro():\n    return 2\n'
    with pytest.raises((ValueError, KeyError)) as exc_info:
        _apply_symbol_patch(source, 'buried_coro', new_block)
    low = str(exc_info.value).lower()
    assert 'nested' in low
    assert 'buried_coro' in low
    assert 'host_fn' in low

def test_toplevel_symbol_patch_still_applies():
    """A normal top-level def patch is spliced in with no error."""
    source = 'def alpha():\n    return 1\n'
    new_block = 'def alpha():\n    return 2\n'
    result = _apply_symbol_patch(source, 'alpha', new_block)
    assert 'return 2' in result
    assert 'return 1' not in result

def test_toplevel_class_symbol_patch_still_applies():
    """A normal top-level class patch is spliced in with no error."""
    source = 'class Foo:\n    x = 1\n'
    new_block = 'class Foo:\n    x = 2\n'
    result = _apply_symbol_patch(source, 'Foo', new_block)
    assert 'x = 2' in result
    assert 'x = 1' not in result

def test_async_toplevel_symbol_patch_still_applies():
    """A normal top-level async def patch is spliced in with no error."""
    source = 'async def beta():\n    return 1\n'
    new_block = 'async def beta():\n    return 2\n'
    result = _apply_symbol_patch(source, 'beta', new_block)
    assert 'return 2' in result
    assert 'return 1' not in result

def test_two_part_qualname_symbol_patch_still_applies():
    """A supported ``Outer.inner`` member patch still applies (no regression)."""
    source = textwrap.dedent('\n        class Outer:\n            def inner(self):\n                return 1\n        ')
    new_block = 'def inner(self):\n    return 2\n'
    result = _apply_symbol_patch(source, 'Outer.inner', new_block)
    assert 'return 2' in result
    assert 'return 1' not in result
    assert '    def inner(self):' in result

def test_truly_absent_symbol_still_keyerrors_distinctly():
    """A name that is neither top-level nor nested -> bare KeyError(qualname)."""
    source = 'def gamma():\n    return 1\n'
    new_block = 'def ghost():\n    return 9\n'
    with pytest.raises(KeyError) as exc_info:
        _apply_symbol_patch(source, 'ghost', new_block)
    msg = str(exc_info.value).lower()
    assert 'nested' not in msg
    assert 'ghost' in msg

def test_commit_accepted_output_patches_nested_symbol_returns_error(tmp_path):
    """Nested-symbol patch via the commit driver -> committed False + 'nested' error."""
    target_src = textwrap.dedent('\n        def wrapper_fn():\n            def leaf_fn():\n                return 1\n            return leaf_fn\n        ')
    out, _state_dir = _make_patch_commit(tmp_path, target_src, 'leaf_fn', 'def leaf_fn():\n    return 2\n')
    assert out['committed'] is False
    assert out['sha'] is None
    assert out['error'] is not None
    assert 'nested' in out['error'].lower()

def test_commit_accepted_output_patches_truly_absent_logs_event(tmp_path):
    """A failing patch writes an auto_commit_patch_failed ledger row (no regression)."""
    target_src = 'def keep_fn():\n    return 0\n'
    out, state_dir = _make_patch_commit(tmp_path, target_src, 'no_such_symbol', 'def no_such_symbol():\n    return 1\n')
    assert out['committed'] is False
    rows = _journal_rows(state_dir)
    failed = [r for r in rows if r.get('event') == 'auto_commit_patch_failed']
    assert failed, 'expected an auto_commit_patch_failed ledger row'
    row = failed[-1]
    assert row.get('task_id') == TASK_ID
    assert row.get('file') == REL
    assert row.get('phase') == 'rejected'

def test_actionable_error_surfaced_in_stderr_tail(tmp_path):
    """The auto_commit_patch_failed ledger row must carry a 'stderr_tail' field."""
    target_src = 'def existing_fn():\n    return 0\n'
    out, state_dir = _make_patch_commit(tmp_path, target_src, 'totally_absent', 'def totally_absent():\n    return 1\n')
    assert out['committed'] is False
    rows = _journal_rows(state_dir)
    failed = [r for r in rows if r.get('event') == 'auto_commit_patch_failed']
    assert failed, 'expected an auto_commit_patch_failed ledger row'
    row = failed[-1]
    assert 'stderr_tail' in row
    assert row['stderr_tail']