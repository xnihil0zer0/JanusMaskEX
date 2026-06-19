"""RED-on-HEAD oracle for harness.git_integration._commit_accepted_output_patches.

Pins two contracts for a kind=symbol patch naming a not-yet-existing top-level
symbol (``no_such_symbol_zzz``):

1. The pre-existing patch-apply failure contract -- ``committed`` is ``False``
   and the failing symbol name is surfaced into ``error`` (a regression witness
   that holds both on HEAD and after the implementation).
2. The NEW telemetry contract -- the authoritative ``state/impl_progress.jsonl``
   ledger gains an ``auto_commit_patch_failed`` row whose ``reason`` embeds the
   failing symbol name and whose ``task_id`` is ``t-telemetry`` (RED on HEAD,
   where no such ledger row is written today, GREEN after the impl).

No real git repository is created: the ``KeyError`` raised by
``_apply_symbol_patch`` for the missing top-level symbol fires at the patch-apply
step BEFORE any git command is invoked, so a plain tmp worktree suffices.
"""
import json
import pathlib
from harness.git_integration import _commit_accepted_output_patches

def _drive(tmp_path):
    """Build a plain (non-git) worktree + state dir + symbol sidecar and drive the commit fn.

    Creates ``worktree/pkg/foo.py`` (a trivial non-sensitive module with a single
    ``existing_fn``), a ``state`` directory, and a ``patches.json`` sidecar listing
    exactly one kind=symbol entry that names the NON-EXISTENT top-level symbol
    ``no_such_symbol_zzz``. Calls ``_commit_accepted_output_patches`` directly and
    returns ``(out, state_dir)``.
    """
    worktree = tmp_path / 'worktree'
    pkg = worktree / 'pkg'
    pkg.mkdir(parents=True)
    (pkg / 'foo.py').write_text('def existing_fn():\n    return 1\n', encoding='utf-8')
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    sidecar = state_dir / 'patches.json'
    sidecar.write_text(json.dumps([{'file': 'pkg/foo.py', 'kind': 'symbol', 'name': 'no_such_symbol_zzz', 'code': 'def no_such_symbol_zzz():\n    return 2\n'}]), encoding='utf-8')
    result = {'committed': None, 'sha': None, 'error': None, 'target': None}
    out = _commit_accepted_output_patches('t-telemetry', sidecar, state_dir, worktree, result, allowed_files={'pkg/foo.py'}, meta_task_type='harness_self_fix', approval_ok=True)
    return (out, state_dir)

def _ledger_rows(state_dir):
    """Parse state/impl_progress.jsonl line-by-line, tolerating blank lines."""
    ledger = state_dir / 'impl_progress.jsonl'
    rows = []
    for line in ledger.read_text(encoding='utf-8').splitlines():
        if not line.strip():
            continue
        rows.append(json.loads(line))
    return rows

def test_patch_apply_failure_sets_committed_false_with_symbol_in_error(tmp_path):
    """A symbol patch for a missing top-level def fails closed and names the symbol."""
    out, _state_dir = _drive(tmp_path)
    assert out['committed'] is False
    assert out['sha'] is None
    assert 'no_such_symbol_zzz' in out['error']

def test_patch_apply_failure_emits_telemetry_row_with_symbol(tmp_path):
    """The failing symbol name is surfaced into the impl_progress.jsonl ledger.

    RED on HEAD (no ledger row is written today, so ``ledger.is_file()`` is
    False); GREEN once the implementation emits the ``auto_commit_patch_failed``
    telemetry row.
    """
    _out, state_dir = _drive(tmp_path)
    ledger = state_dir / 'impl_progress.jsonl'
    assert ledger.is_file()
    matching = [row for row in _ledger_rows(state_dir) if row.get('event') == 'auto_commit_patch_failed' and 'no_such_symbol_zzz' in str(row.get('reason', ''))]
    assert matching, "expected an auto_commit_patch_failed row embedding 'no_such_symbol_zzz'"
    assert matching[0].get('task_id') == 't-telemetry'

def test_committed_false_contract_unchanged_on_symbol_apply_failure(tmp_path):
    """Regression witness: the failure path leaves committed=False and no sha."""
    out, _state_dir = _drive(tmp_path)
    assert out['committed'] is False
    assert out['sha'] is None

def test_error_string_embeds_failing_symbol_name(tmp_path):
    """Regression witness: the opaque error is replaced by one naming the symbol."""
    out, _state_dir = _drive(tmp_path)
    assert out['error'] is not None
    assert 'no_such_symbol_zzz' in out['error']