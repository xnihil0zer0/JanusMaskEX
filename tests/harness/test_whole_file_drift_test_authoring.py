"""RED oracle: tests/harness/test_whole_file_drift_test_authoring.py

Pre-committed verification oracle for
``harness.git_integration._finalize_existing_py_target``.

The helper does NOT modify git / the filesystem here -- it is driven purely with
synthesized Python source strings, so each test pins one slice of its contract:

  * ``test_authoring`` meta_task_type -> wholesale replace, NO whole-file
    drift check (target-only symbols are dropped, every edited symbol wins).
  * any other meta_task_type          -> still REJECTS a whole-file submission
    that mutates >1 existing top-level symbol, naming the changed symbols.
  * ``out_code == tgt_code``          -> the target is returned UNCHANGED
    (byte-identical).
  * a single-symbol change            -> clean ``_ast_merge`` (sibling top-level
    symbols survive, no drift rejection).

Reachability is asserted by collection itself: the helper is imported by name at
module scope, so an absent / unwired symbol fails the whole module.

No banned dynamic execution primitives (exec / eval / compile / __import__) are
used; signature discovery is via ``inspect`` only.
"""
import ast
import inspect
from harness.git_integration import _finalize_existing_py_target
_UNRESOLVED = object()

def _value_for(name, out_code, tgt_code, meta, task_id):
    """Map a parameter name of the helper to the value this oracle wants to pass.

    Kept name-tolerant (exact match first, then a substring heuristic) so the
    oracle binds to the real, not-yet-written implementation regardless of the
    exact parameter spelling, without resorting to positional guessing.
    """
    n = name.lower()
    if n in ('out_code', 'output_code', 'out', 'output', 'new_code', 'new', 'src', 'source', 'candidate', 'submission'):
        return out_code
    if n in ('tgt_code', 'target_code', 'tgt', 'target', 'existing_code', 'existing', 'old_code', 'old', 'current_code', 'current', 'base', 'base_code'):
        return tgt_code
    if n in ('meta_task_type', 'meta', 'task_type', 'mtt'):
        return meta
    if n in ('task_id', 'task', 'tid'):
        return task_id
    if 'meta' in n or 'type' in n:
        return meta
    if 'output' in n or 'out' in n or 'new' in n or ('candidate' in n) or ('submission' in n):
        return out_code
    if 'tgt' in n or 'target' in n or 'exist' in n or ('current' in n) or ('old' in n) or ('base' in n):
        return tgt_code
    if 'task' in n or n == 'id':
        return task_id
    return _UNRESOLVED

def _invoke_finalize(out_code, tgt_code, meta_task_type, task_id='ORACLE-FINALIZE-TASK'):
    """Call the helper, adapting to whatever parameter names / kinds it declares."""
    fn = _finalize_existing_py_target
    sig = inspect.signature(fn)
    pos_args = []
    kw_args = {}
    for name, p in sig.parameters.items():
        if p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD):
            continue
        val = _value_for(name, out_code, tgt_code, meta_task_type, task_id)
        if val is _UNRESOLVED:
            if p.default is inspect.Parameter.empty:
                val = None
            else:
                continue
        if p.kind == inspect.Parameter.POSITIONAL_ONLY:
            pos_args.append(val)
        else:
            kw_args[name] = val
    return fn(*pos_args, **kw_args)

def _drift_signal(out_code, tgt_code, meta_task_type):
    """Capture HOW the helper signals a drift rejection.

    Returns ``('raised', text)`` when the helper raises, or ``('returned',
    text)`` when it returns. ``text`` is what an assertion can inspect for the
    ``whole_file_drift`` token and the changed-symbol names -- this stays robust
    whether the contract rejects via a raised exception or a returned error
    string, while still going negative (no drift token present) on a mutant that
    silently drops the check.
    """
    try:
        ret = _invoke_finalize(out_code, tgt_code, meta_task_type)
    except Exception as exc:
        return ('raised', '%s: %s' % (type(exc).__name__, exc))
    return ('returned', '' if ret is None else str(ret))

def _module_src(funcs):
    """Build top-level module source from an ordered {name: return_value} map."""
    return '\n'.join(('def %s():\n    return %r\n' % (name, val) for name, val in funcs.items()))

def _def_names(code):
    return {n.name for n in ast.parse(code).body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))}

def test_wiring_reachability():
    assert callable(_finalize_existing_py_target)
    sig = inspect.signature(_finalize_existing_py_target)
    real = [p for p in sig.parameters.values() if p.kind not in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)]
    assert len(real) >= 2

def test_test_authoring_wholesale_replace_no_drift_check():
    tgt = _module_src({'alpha': 'OLD_ALPHA', 'beta': 'OLD_BETA', 'gamma': 'OLD_GAMMA'})
    out = _module_src({'alpha': 'NEW_ALPHA', 'beta': 'NEW_BETA'})
    result = _invoke_finalize(out, tgt, 'test_authoring')
    assert isinstance(result, str)
    assert _def_names(result) == {'alpha', 'beta'}
    assert 'NEW_ALPHA' in result and 'NEW_BETA' in result
    assert 'OLD_ALPHA' not in result
    assert 'OLD_BETA' not in result
    assert 'OLD_GAMMA' not in result

def test_non_test_authoring_multi_symbol_still_drift_rejected():
    tgt = _module_src({'alpha': 'OLD_ALPHA', 'beta': 'OLD_BETA', 'gamma': 'KEEP_GAMMA'})
    out = _module_src({'alpha': 'NEW_ALPHA', 'beta': 'NEW_BETA'})
    mode, msg = _drift_signal(out, tgt, 'production')
    assert 'drift' in msg.lower(), 'expected a whole-file drift rejection, got %s: %r' % (mode, msg)
    assert 'alpha' in msg and 'beta' in msg

def test_equal_code_returns_target_unchanged():
    code = _module_src({'alpha': 'SAME', 'beta': 'SAME_TWO'})
    result = _invoke_finalize(code, code, 'production')
    assert result == code

def test_single_symbol_change_merges_cleanly():
    tgt = _module_src({'alpha': 'OLD_ALPHA', 'beta': 'KEEP_BETA'})
    out = _module_src({'alpha': 'NEW_ALPHA'})
    result = _invoke_finalize(out, tgt, 'production')
    assert isinstance(result, str)
    assert _def_names(result) == {'alpha', 'beta'}
    assert 'NEW_ALPHA' in result
    assert 'KEEP_BETA' in result
    assert 'OLD_ALPHA' not in result

def test_test_authoring_drops_target_only_symbols():
    tgt = _module_src({'alpha': 'OLD_ALPHA', 'beta': 'KEEP_BETA'})
    out = _module_src({'alpha': 'NEW_ALPHA'})
    result = _invoke_finalize(out, tgt, 'test_authoring')
    assert _def_names(result) == {'alpha'}
    assert 'NEW_ALPHA' in result
    assert 'KEEP_BETA' not in result

def test_non_test_authoring_single_symbol_no_drift_signal():
    tgt = _module_src({'alpha': 'OLD', 'beta': 'KEEP'})
    out = _module_src({'alpha': 'NEW'})
    mode, msg = _drift_signal(out, tgt, 'production')
    assert mode == 'returned', 'single-symbol change must merge, not reject; got %s: %r' % (mode, msg)
    assert 'drift' not in msg.lower()

def test_non_test_authoring_new_symbol_merges_without_drift():
    tgt = _module_src({'alpha': 'ALPHA_BODY'})
    out = _module_src({'alpha': 'ALPHA_BODY', 'delta': 'DELTA_BODY'})
    result = _invoke_finalize(out, tgt, 'production')
    assert isinstance(result, str)
    assert _def_names(result) == {'alpha', 'delta'}
    assert 'DELTA_BODY' in result

def test_non_test_authoring_identical_resubmission_no_drift():
    tgt = _module_src({'alpha': 'A_BODY', 'beta': 'B_BODY'})
    out = _module_src({'alpha': 'A_BODY'})
    result = _invoke_finalize(out, tgt, 'production')
    assert isinstance(result, str)
    assert _def_names(result) == {'alpha', 'beta'}
    assert 'B_BODY' in result

def test_non_test_authoring_triple_symbol_drift_lists_all_names():
    tgt = _module_src({'alpha': 'O1', 'beta': 'O2', 'gamma': 'O3'})
    out = _module_src({'alpha': 'N1', 'beta': 'N2', 'gamma': 'N3'})
    mode, msg = _drift_signal(out, tgt, 'production')
    assert 'drift' in msg.lower(), 'expected a whole-file drift rejection, got %s: %r' % (mode, msg)
    for name in ('alpha', 'beta', 'gamma'):
        assert name in msg

def test_non_test_authoring_none_meta_type_still_drift_rejected():
    tgt = _module_src({'alpha': 'O1', 'beta': 'O2'})
    out = _module_src({'alpha': 'N1', 'beta': 'N2'})
    mode, msg = _drift_signal(out, tgt, None)
    assert 'drift' in msg.lower(), 'expected a whole-file drift rejection, got %s: %r' % (mode, msg)
    assert 'alpha' in msg and 'beta' in msg