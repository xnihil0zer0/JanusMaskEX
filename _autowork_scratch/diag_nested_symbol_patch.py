#!/usr/bin/env python3
"""Analytic repro + fix-PoC for the nested-symbol patch-apply gap.

Run from repo root:  cd /home/xnihil0zer0/JanusMaskJR && PYTHONPATH=. python _autowork_scratch/diag_nested_symbol_patch.py

READ-ONLY against all production files. This script:
  (1) drives the REAL harness.git_integration._parse_patches +
      _apply_symbol_patch against the live claude submission and live
      conductor_seams.py to capture the exact rejection (root-cause proof);
  (2) implements a STANDALONE proof-of-concept of the nested-symbol splice
      (no harness file is modified), produces a merged conductor_seams.py, and
      verifies it via importlib (NOT exec) -- imports clean, nested defs intact,
      new build_evidence body matches the patch;
  (3) runs regression + edge-case checks.
"""
import ast
import importlib.util
import json
import os
import sys
import tempfile
import textwrap

REPO = '/home/xnihil0zer0/JanusMaskJR'
NGV2_ROOT = '/home/xnihil0zer0/NobleGreedv2'
SUBMISSION = os.path.join(REPO, 'state/sessions/claude_round1_p11-build-evidence-structural-keys_submission.json')
TARGET = os.path.join(NGV2_ROOT, 'ngv2/conductor_seams.py')

sys.path.insert(0, REPO)
# NGv2 root on path so the merged conductor_seams.py can resolve its real
# `from ngv2 import ...` sibling modules during the importlib load check.
sys.path.insert(0, NGV2_ROOT)
from harness import git_integration as gi  # noqa: E402


def banner(t):
    print('\n' + '=' * 72 + '\n' + t + '\n' + '=' * 72)


def load_inputs():
    sub = json.load(open(SUBMISSION))
    code = sub['code']
    patches = gi._parse_patches(code)
    src = open(TARGET).read()
    return code, patches, src


# ---------------------------------------------------------------------------
# (1) REPRODUCE against live code
# ---------------------------------------------------------------------------
def repro(patches, src):
    banner('(1) REPRO: drive REAL _parse_patches + _apply_symbol_patch')
    print('parsed patches =', json.dumps(
        [{k: (v if k != 'code' else f'<{len(v)} chars>') for k, v in p.items()} for p in patches], indent=2))
    assert patches and len(patches) == 1, 'expected exactly one patch'
    p = patches[0]
    assert p['kind'] == 'symbol' and p['name'] == 'build_evidence'
    try:
        gi._apply_symbol_patch(src, p['name'], p['code'])
        print('!!! UNEXPECTED: patch applied with no error (bug already fixed?)')
        return None
    except Exception as exc:  # noqa: BLE001
        print(f'\nREJECTED with {type(exc).__name__}:')
        print(' ', str(exc))
        return exc


# ---------------------------------------------------------------------------
# (2)+(3) FIX PROOF-OF-CONCEPT  (standalone; mirrors the harness branch)
# ---------------------------------------------------------------------------
def _is_def(n):
    return isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))


def _find_nested_chains(name, root, start):
    """All dotted enclosing chains of every def/class named *name* nested
    inside another def/class within *root* (mirror of harness helper)."""
    found = []

    def _walk(node, enclosers):
        for child in ast.iter_child_nodes(node):
            if _is_def(child):
                if enclosers and child.name == name:
                    found.append('.'.join(enclosers))
                _walk(child, enclosers + [child.name])
            else:
                _walk(child, enclosers)

    _walk(root, list(start))
    return found


def splice_nested_symbol(source, leaf_name, new_block):
    """PoC: splice the parsed *new_block* def into its enclosing top-level
    symbol's AST, returning (enclosing_top_name, enclosing_new_block_text).

    The caller then feeds (enclosing_top_name, enclosing_new_block_text) into
    the EXISTING top-level _apply_symbol_patch path -- so reindent / line-slice
    / byte-preservation are 100% reused; only the *target* changes.

    Raises ValueError on ambiguity (same name nested in >1 distinct enclosing
    top-level symbol) or a malformed new_block.
    """
    new_block = textwrap.dedent(new_block)
    nb_tree = ast.parse(new_block)
    # new_block must be exactly one def/class with the leaf name (EDGE b/c/d/e)
    primaries = [n for n in nb_tree.body if _is_def(n) and n.name == leaf_name]
    if len(nb_tree.body) != 1 or len(primaries) != 1:
        raise ValueError(
            f'nested-symbol new_block must be exactly one def/class named '
            f'{leaf_name!r}, found body={len(nb_tree.body)} matches={len(primaries)}')
    new_def = primaries[0]

    tree = ast.parse(source)
    chains = sorted(set(_find_nested_chains(leaf_name, tree, [])))
    if not chains:
        raise KeyError(leaf_name)  # not nested anywhere -> unchanged behavior
    # AMBIGUITY (EDGE a): distinct enclosing TOP-LEVEL symbols
    top_levels = sorted({c.split('.')[0] for c in chains})
    if len(top_levels) > 1:
        raise ValueError(
            f'ambiguous nested target {leaf_name!r}: nested inside multiple '
            f'top-level symbols {top_levels}; a dotted qualname is required')
    # Also reject same-top but >1 distinct nesting path (deep ambiguity)
    if len(chains) > 1:
        raise ValueError(
            f'ambiguous nested target {leaf_name!r}: multiple nestings {chains}; '
            f'a dotted qualname is required')
    top_name = top_levels[0]

    # Locate the enclosing top-level node, replace the matching nested def
    # in-place (deepest match along the single unambiguous chain).
    top_node = next(n for n in tree.body if _is_def(n) and n.name == top_name)

    replaced = {'n': 0}

    def _replace_in_body(body):
        for i, stmt in enumerate(body):
            if _is_def(stmt) and stmt.name == leaf_name and stmt is not top_node:
                body[i] = new_def
                replaced['n'] += 1
            # recurse into nested bodies (skip the just-replaced node's old body)
            for fld in ('body', 'orelse', 'finalbody'):
                sub = getattr(stmt, fld, None)
                if isinstance(sub, list) and body[i] is stmt:
                    _replace_in_body(sub)
            # handlers (try/except)
            for h in getattr(stmt, 'handlers', []) or []:
                _replace_in_body(h.body)

    _replace_in_body(top_node.body)
    if replaced['n'] != 1:
        raise ValueError(f'expected exactly 1 in-scope replacement, made {replaced["n"]}')

    ast.fix_missing_locations(top_node)
    enclosing_text = ast.unparse(top_node)
    return top_name, enclosing_text


def splice_nested_symbol_textpreserving(source, leaf_name, new_block):
    """Higher-fidelity variant: byte-preserving line-slice of ONLY the nested
    def's range inside *source*, returning (top_name, rebuilt_enclosing_text).

    Unlike the ast.unparse() variant this preserves comments/blank-lines/exact
    formatting of the SIBLING nested defs (load_state/persist/advance) AND of
    everything else in the enclosing symbol -- only the target def's lines are
    replaced. The new_block is re-indented to the nested def's col_offset.
    The rebuilt enclosing text is then fed to the EXISTING top-level
    _apply_symbol_patch path exactly as in the unparse variant.
    """
    new_block = textwrap.dedent(new_block)
    nb_tree = ast.parse(new_block)
    primaries = [n for n in nb_tree.body if _is_def(n) and n.name == leaf_name]
    if len(nb_tree.body) != 1 or len(primaries) != 1:
        raise ValueError(
            f'nested-symbol new_block must be exactly one def/class named '
            f'{leaf_name!r}, found body={len(nb_tree.body)} matches={len(primaries)}')
    tree = ast.parse(source)
    chains = sorted(set(_find_nested_chains(leaf_name, tree, [])))
    if not chains:
        raise KeyError(leaf_name)
    top_levels = sorted({c.split('.')[0] for c in chains})
    if len(top_levels) > 1 or len(chains) > 1:
        raise ValueError(f'ambiguous nested target {leaf_name!r}: {chains}')
    top_name = top_levels[0]
    top_node = next(n for n in tree.body if _is_def(n) and n.name == top_name)

    # locate the unique nested target node (the single unambiguous chain)
    target = None
    for node in ast.walk(top_node):
        if node is top_node:
            continue
        if _is_def(node) and node.name == leaf_name:
            target = node
            break
    assert target is not None
    col = target.col_offset or 0
    t_start = target.lineno
    if getattr(target, 'decorator_list', None):
        t_start = min(d.lineno for d in target.decorator_list)
    t_end = target.end_lineno
    src_lines = source.splitlines(keepends=True)
    indent = ' ' * col
    reindented = ''.join(indent + ln if ln.strip() else ln
                         for ln in new_block.splitlines(keepends=True))
    if not reindented.endswith('\n'):
        reindented += '\n'
    rebuilt = ''.join(src_lines[:t_start - 1]) + reindented + ''.join(src_lines[t_end:])
    # rebuilt spans the WHOLE file; slice out just the enclosing top-level block
    rt = ast.parse(rebuilt)
    new_top = next(n for n in rt.body if _is_def(n) and n.name == top_name)
    ts = new_top.lineno
    if getattr(new_top, 'decorator_list', None):
        ts = min(d.lineno for d in new_top.decorator_list)
    rb_lines = rebuilt.splitlines(keepends=True)
    enclosing_text = ''.join(rb_lines[ts - 1:new_top.end_lineno])
    return top_name, enclosing_text


def importlib_check(path, modname):
    spec = importlib.util.spec_from_file_location(modname, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # NOT exec()/eval() -- real loader
    return mod


def prove_fix(patches, src):
    banner('(2)+(3) FIX PoC: splice nested build_evidence -> apply via top-level path')
    p = patches[0]
    leaf, new_block = p['name'], p['code']

    top_name, enclosing_text = splice_nested_symbol(src, leaf, new_block)
    print(f'resolved nested {leaf!r} -> enclosing top-level symbol {top_name!r}')

    # Feed the rebuilt enclosing symbol back through the EXISTING harness path.
    merged = gi._apply_symbol_patch(src, top_name, enclosing_text)
    print(f'merged file produced via _apply_symbol_patch(src, {top_name!r}, <rebuilt>): '
          f'{len(merged)} bytes (orig {len(src)})')

    tmpdir = tempfile.mkdtemp(prefix='nested_patch_poc_')
    merged_path = os.path.join(tmpdir, 'conductor_seams.py')
    with open(merged_path, 'w') as fh:
        fh.write(merged)

    # (a) imports without NameError (importlib, real loader)
    mod = importlib_check(merged_path, 'merged_conductor_seams')
    print('(a) importlib load: OK (no NameError) ->', mod.__name__)

    # (b) build_default_seams still contains load_state, persist, advance + NEW build_evidence
    mtree = ast.parse(merged)
    bds = next(n for n in mtree.body if _is_def(n) and n.name == 'build_default_seams')
    nested_names = [c.name for c in ast.iter_child_nodes(bds) if _is_def(c)]
    print('(b) nested defs under build_default_seams:', nested_names)
    for need in ('load_state', 'persist', 'advance', 'build_evidence'):
        assert need in nested_names, f'missing nested {need}'
    assert 'build_evidence' not in {n.name for n in mtree.body if _is_def(n)}, \
        'build_evidence must NOT have leaked to top-level'

    # (c) new build_evidence body matches the patch
    patch_def = next(n for n in ast.parse(textwrap.dedent(new_block)).body
                     if _is_def(n) and n.name == 'build_evidence')
    merged_be = next(c for c in ast.iter_child_nodes(bds)
                     if _is_def(c) and c.name == 'build_evidence')
    assert ast.unparse(merged_be) == ast.unparse(patch_def), 'build_evidence body mismatch'
    print('(c) merged build_evidence body == patch body: OK')

    # functional smoke: call the spliced (NEW) closure via the seam dict.
    # The patched build_evidence emits the new structural keys, proving the
    # NEW body (not the old one) is what runs after the splice.
    seams = mod.build_default_seams('sess1', None, None, {})
    ev = seams['build_evidence']({'prior_findings': [{'sink_name': 's'}]})
    print('    functional call build_evidence(...) ->', ev)
    assert ev.get('source_ready') is True, 'new build_evidence structural keys absent'
    assert 'findings' in ev and 'triage_result' in ev, 'new structural keys absent'
    print('FIX PROVEN (new structural-keys body is live).')

    # --- higher-fidelity TEXT-PRESERVING variant -----------------------------
    banner('(2b) FIX PoC variant B: byte-preserving line-slice (keeps sibling comments)')
    top2, enc2 = splice_nested_symbol_textpreserving(src, leaf, new_block)
    merged2 = gi._apply_symbol_patch(src, top2, enc2)
    mp2 = os.path.join(tmpdir, 'cs_textpreserve.py')
    with open(mp2, 'w') as fh:
        fh.write(merged2)
    mod2 = importlib_check(mp2, 'merged_cs_textpreserve')
    m2tree = ast.parse(merged2)
    bds2 = next(n for n in m2tree.body if _is_def(n) and n.name == 'build_default_seams')
    nn2 = [c.name for c in ast.iter_child_nodes(bds2) if _is_def(c)]
    assert set(nn2) >= {'load_state', 'persist', 'advance', 'build_evidence'}, nn2
    # sibling persist text PRESERVED byte-for-byte (its source segment unchanged)
    orig_persist = ast.get_source_segment(src, next(
        c for c in ast.iter_child_nodes(bds) if _is_def(c) and c.name == 'persist'))
    new_persist = ast.get_source_segment(merged2, next(
        c for c in ast.iter_child_nodes(bds2) if _is_def(c) and c.name == 'persist'))
    print('variant B nested defs:', nn2)
    print('variant B sibling persist byte-identical:', orig_persist == new_persist)
    assert orig_persist == new_persist, 'text-preserving variant must keep siblings byte-identical'
    seams2 = mod2.build_default_seams('s', None, None, {})
    assert seams2['build_evidence']({'prior_findings': [{}]}).get('source_ready') is True
    print('variant B imports + nested-call OK; siblings byte-preserved.')
    return merged


# ---------------------------------------------------------------------------
# (3-regression) Non-nested top-level symbol patch is UNAFFECTED
# ---------------------------------------------------------------------------
def prove_regression(src):
    banner('(3-regression) ordinary TOP-LEVEL symbol patch unaffected')
    # _count_real is a genuine top-level def in conductor_seams.py
    top_patch = 'def _count_real(arts):\n    return 999\n'
    # The fix branch only fires when the name is NOT top-level; _count_real IS
    # top-level, so splice_nested_symbol must refuse (KeyError) -> caller stays
    # on the existing top-level path.
    try:
        splice_nested_symbol(src, '_count_real', top_patch)
        print('!!! UNEXPECTED: splice fired on a top-level symbol')
    except KeyError:
        print('splice_nested_symbol(_count_real) -> KeyError (correctly declines a top-level name)')
    # And the existing top-level apply still works byte-for-byte:
    out = gi._apply_symbol_patch(src, '_count_real', top_patch)
    t = ast.parse(out)
    cr = next(n for n in t.body if _is_def(n) and n.name == '_count_real')
    assert 'return 999' in ast.unparse(cr)
    print('existing top-level _apply_symbol_patch(_count_real) still applies: OK')


# ---------------------------------------------------------------------------
# (4) EDGE CASES
# ---------------------------------------------------------------------------
def prove_edges(src):
    banner('(4) EDGE CASES')

    # (a) ambiguity: same nested name in two distinct top-level enclosers
    amb = textwrap.dedent('''
        def outer_a():
            def dup():
                return 1
            return dup
        def outer_b():
            def dup():
                return 2
            return dup
    ''')
    try:
        splice_nested_symbol(amb, 'dup', 'def dup():\n    return 9\n')
        print('(a) !!! ambiguity NOT detected')
    except ValueError as e:
        print('(a) ambiguous same-name across enclosers -> ValueError:', str(e)[:80])

    # (b) new_block not a single def/class
    try:
        splice_nested_symbol(src, 'build_evidence', 'x = 1\ndef build_evidence(state):\n    return {}\n')
        print('(b) !!! multi-statement new_block NOT rejected')
    except ValueError as e:
        print('(b) new_block with extra top-level stmt -> ValueError:', str(e)[:80])

    # (c) async def nested target
    asy = textwrap.dedent('''
        def outer():
            async def job():
                return 0
            return job
    ''')
    top, txt = splice_nested_symbol(asy, 'job', 'async def job():\n    return 42\n')
    nt = ast.parse(txt)
    job = next(c for c in ast.walk(nt) if isinstance(c, ast.AsyncFunctionDef) and c.name == 'job')
    assert 'return 42' in ast.unparse(job)
    print(f'(c) async def nested target spliced into {top!r}: OK')

    # (d) decorators on the nested def (and in the patch)
    dec = textwrap.dedent('''
        import functools
        def outer():
            @functools.cache
            def memo(x):
                return x
            return memo
    ''')
    top, txt = splice_nested_symbol(dec, 'memo', '@functools.lru_cache\ndef memo(x):\n    return x * 2\n')
    nt = ast.parse(txt)
    memo = next(c for c in ast.walk(nt) if isinstance(c, ast.FunctionDef) and c.name == 'memo')
    decs = [ast.unparse(d) for d in memo.decorator_list]
    assert 'return x * 2' in ast.unparse(memo) and any('lru_cache' in d for d in decs), decs
    print(f'(d) decorated nested def spliced, decorator from PATCH used: {decs}')

    # (e) name that is BOTH a top-level symbol and a nested def -> top-level wins
    both = textwrap.dedent('''
        def thing():
            return 'top'
        def host():
            def thing():
                return 'nested'
            return thing
    ''')
    # The harness top-level branch finds the top-level `thing` FIRST and never
    # consults the nested resolver, so splice must NOT be invoked for it.
    # Demonstrate the existing apply targets the top-level one:
    out = gi._apply_symbol_patch(both, 'thing', "def thing():\n    return 'patched-top'\n")
    t = ast.parse(out)
    top_thing = next(n for n in t.body if _is_def(n) and n.name == 'thing')
    assert "return 'patched-top'" in ast.unparse(top_thing)
    host = next(n for n in t.body if _is_def(n) and n.name == 'host')
    nested_thing = next(c for c in ast.iter_child_nodes(host) if _is_def(c) and c.name == 'thing')
    assert "return 'nested'" in ast.unparse(nested_thing), 'nested thing must be untouched'
    print('(e) top-level name wins; nested same-name untouched: OK')


def main():
    code, patches, src = load_inputs()
    repro(patches, src)
    prove_fix(patches, src)
    prove_regression(src)
    prove_edges(src)
    banner('ALL CHECKS PASSED')


if __name__ == '__main__':
    main()
