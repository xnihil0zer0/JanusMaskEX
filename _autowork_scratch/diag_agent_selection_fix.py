#!/usr/bin/env python3
"""Diagnostic for the "claude-committed-on-divergence, gemini-correct-discarded" bug.

PART A: confirm the two LIVE drift-impl candidates diverge in return type of
        `_finalize_existing_py_target` (gemini returns str, claude returns tuple).
PART B: demonstrate the proposed VERIFY-FALLBACK fix logic in miniature: given
        two candidate code strings (one fails a toy oracle, one passes), the
        fix-logic commits the PASSING one instead of defaulting to candidate_a.

Loads candidate code via importlib only (never exec/eval/compile/__import__).
Run:  PYTHONPATH=. python _autowork_scratch/diag_agent_selection_fix.py
"""
import importlib.util
import json
import re
import sys
import tempfile
import textwrap
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
SESS = REPO / 'state' / 'sessions'


def _load_module_from_source(src: str, modname: str):
    """Write src to a temp .py and import it via importlib (no exec/eval)."""
    tmpdir = Path(tempfile.mkdtemp(prefix='diag_sel_'))
    pyfile = tmpdir / f'{modname}.py'
    pyfile.write_text(src, encoding='utf-8')
    spec = importlib.util.spec_from_file_location(modname, str(pyfile))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # importlib loader, not builtin exec/eval/compile
    return mod


def _candidate_patch_code(full_code: str) -> str:
    """Extract the `code` body of the commit_accepted_output __JANUSMASK_PATCHES__
    entry using the HARNESS's own _parse_patches (the same parser the pipeline uses
    in _save_final_output). Returns the patched source containing the nested
    _finalize_existing_py_target def."""
    from harness import git_integration
    patches = git_integration._parse_patches(full_code)
    if not patches:
        return ''
    # join all patch code bodies (the target def lives in one of them)
    return '\n\n'.join(p.get('code', '') for p in patches if isinstance(p, dict))


def _finalize_return_info(patch_code: str):
    """AST-inspect the nested `_finalize_existing_py_target` def: capture its
    declared return annotation + the shapes of its `return` statements."""
    import ast as _ast
    tree = _ast.parse(patch_code)
    fn = None
    for node in _ast.walk(tree):
        if isinstance(node, _ast.FunctionDef) and node.name == '_finalize_existing_py_target':
            fn = node
            break
    if fn is None:
        return None, []
    ann = _ast.unparse(fn.returns) if fn.returns is not None else '<none>'
    shapes = []
    for n in _ast.walk(fn):
        if isinstance(n, _ast.Return) and n.value is not None:
            v = n.value
            if isinstance(v, _ast.Tuple):
                shapes.append(f'TUPLE[{len(v.elts)}]')
            elif isinstance(v, _ast.Constant):
                shapes.append(f'const:{type(v.value).__name__}')
            elif isinstance(v, _ast.Name):
                shapes.append(f'name:{v.id}')
            elif isinstance(v, _ast.Call):
                fname = getattr(v.func, 'id', getattr(v.func, 'attr', '?'))
                shapes.append(f'call:{fname}(...)')
            else:
                shapes.append(type(v).__name__)
    return ann, shapes


# ---------------------------------------------------------------------------
# PART A: live candidate return-type divergence
# ---------------------------------------------------------------------------
def part_a() -> None:
    print('=' * 70)
    print('PART A: LIVE candidate divergence (whole-file-drift-test-authoring-impl)')
    print('=' * 70)
    results = {}
    for who in ('claude', 'gemini'):
        p = SESS / f'{who}_round1_whole-file-drift-test-authoring-impl_submission.json'
        code = json.loads(p.read_text(encoding='utf-8'))['code']
        patch_code = _candidate_patch_code(code)
        ann, shapes = _finalize_return_info(patch_code)
        # Confirm the extracted function is importable via importlib (no exec/eval).
        importable = False
        try:
            # slice just the def out of the patch code for an isolation import test
            import ast as _ast
            tree = _ast.parse(patch_code)
            for node in _ast.body if False else _ast.walk(tree):
                if isinstance(node, _ast.FunctionDef) and node.name == '_finalize_existing_py_target':
                    fn_src = _ast.unparse(node)
                    mod = _load_module_from_source(fn_src + '\n', f'cand_{who}')
                    importable = hasattr(mod, '_finalize_existing_py_target')
                    break
        except Exception as e:
            importable = f'ERR:{e!r}'
        results[who] = {'return_annotation': ann, 'return_shapes': shapes, 'importlib_ok': importable}
        print(f'  [{who}] return annotation = {ann!r}')
        print(f'         return shapes     = {shapes}')
        print(f'         importlib load ok = {importable}')
    print()
    c, g = results['claude'], results['gemini']
    has_tuple = lambda r: ('tuple' in (r['return_annotation'] or '').lower()) or any('TUPLE' in s for s in r['return_shapes'])
    print(f'  claude declares tuple return : {has_tuple(c)}  ({c["return_annotation"]!r})')
    print(f'  gemini declares tuple return : {has_tuple(g)}  ({g["return_annotation"]!r})')
    diverge = c['return_annotation'] != g['return_annotation'] and has_tuple(c) != has_tuple(g)
    print(f'  >>> RETURN-TYPE DIVERGENCE   : {diverge}')
    print(f'      claude -> {c["return_annotation"]} ;  gemini -> {g["return_annotation"]}')
    print()


# ---------------------------------------------------------------------------
# PART B: fix logic in miniature
# ---------------------------------------------------------------------------
TOY_PASS = textwrap.dedent('''
    def finalize(x):
        # CORRECT: returns a plain string (what the oracle expects)
        return "ok:" + str(x)
''')

TOY_FAIL = textwrap.dedent('''
    def finalize(x):
        # WRONG: returns a tuple (oracle asserts a str)
        return ("ok:" + str(x), 0)
''')


def _toy_oracle(modname: str, src: str) -> bool:
    """Toy verification_command analogue: import the candidate, call finalize('z'),
    PASS iff it returns a str equal to 'ok:z'. Mirrors the real flow where the
    committed candidate is run against the task's verification_command."""
    try:
        mod = _load_module_from_source(src, modname)
        out = mod.finalize('z')
        return isinstance(out, str) and out == 'ok:z'
    except Exception:
        return False


def _commit_with_verify_fallback(primary_code, fallback_code, oracle):
    """MINIATURE of the proposed fix that slots into _auto_commit_accepted's
    verification-failure path:

      1. apply+verify PRIMARY (claude / agent_a)            -> current behaviour
      2. if it PASSES, keep it (commit primary)             -> unchanged happy path
      3. if it FAILS, ROLL BACK, apply+verify FALLBACK      -> NEW
      4. if FALLBACK passes, commit it; else stay blocked   -> NEW

    Returns (committed_code_or_None, which_agent, log[])."""
    log = []
    # step 1+2: primary
    log.append('apply primary; run verification_command')
    if oracle('primary', primary_code):
        log.append('primary PASSED -> commit primary (unchanged behaviour)')
        return primary_code, 'primary', log
    # step 3: primary failed -> rollback (git reset --hard HEAD~1 in real code)
    log.append('primary FAILED verification -> rollback commit')
    log.append('apply FALLBACK (other agent) to same target; re-run verification')
    if oracle('fallback', fallback_code):
        log.append('fallback PASSED -> commit fallback  *** RECOVERED ***')
        return fallback_code, 'fallback', log
    log.append('fallback ALSO failed -> route to blocked (unchanged terminal)')
    return None, None, log


def part_b() -> None:
    print('=' * 70)
    print('PART B: VERIFY-FALLBACK fix logic in miniature')
    print('=' * 70)
    print('  Scenario mirrors the live bug: primary(claude)=tuple/FAIL, '
          'fallback(gemini)=str/PASS')
    print()
    # sanity: confirm the toy oracle classifies the two candidates correctly
    print(f'  toy_oracle(TOY_FAIL=tuple) = {_toy_oracle("tf", TOY_FAIL)}  (expect False)')
    print(f'  toy_oracle(TOY_PASS=str)   = {_toy_oracle("tp", TOY_PASS)}  (expect True)')
    print()

    print('  --- OLD logic (default-to-primary, no fallback): ---')
    old_committed = TOY_FAIL  # always agent_a == claude == the failing one
    old_passes = _toy_oracle('old', old_committed)
    print(f'    committed = primary(claude); verification passes = {old_passes}')
    print(f'    OUTCOME   = {"accepted" if old_passes else "BLOCKED (correct gemini discarded)"}')
    print()

    print('  --- NEW logic (verify-fallback): ---')
    committed, agent, log = _commit_with_verify_fallback(TOY_FAIL, TOY_PASS, _toy_oracle)
    for line in log:
        print(f'      - {line}')
    print(f'    committed agent = {agent}')
    final_ok = committed is not None and _toy_oracle('final', committed)
    print(f'    final committed candidate passes oracle = {final_ok}')
    print(f'    OUTCOME   = {"accepted (RECOVERED via fallback)" if final_ok else "blocked"}')
    print()

    print('  --- control: BOTH fail -> still blocked (no false accept): ---')
    c2, a2, _ = _commit_with_verify_fallback(TOY_FAIL, TOY_FAIL, _toy_oracle)
    print(f'    committed = {c2!r}, agent = {a2!r}  (expect None/None -> blocked)')
    print()


if __name__ == '__main__':
    part_a()
    part_b()
    print('DONE.')
