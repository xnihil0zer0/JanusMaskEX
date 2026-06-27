#!/usr/bin/env python3
"""Fast FP-rate: replicate the floor's reachability EXACTLY but cache the graph
per (source_root) so we don't rebuild it per symbol-call. Verified to match
symbol_reachable_from_live_root on spot checks.

Measures would_be_orphan% over NGv2-engine symbols under root regimes:
  (a) JM LIVE_ROOTS
  (b) NGv2 declared roots (run_hunt + engine __main__ guards)
  (c) discover_live_roots auto-discovery (scoped to this source_root)

Two source-root scopings:
  - NGV2-PKG  : source_root = NobleGreedv2/ngv2  (per-project source root, sane)
  - PRUNED    : source_root = NobleGreedv2 but excluding tmp/ targets/ research/
                _e2e_run/ _autowork_scratch/ (what a per-project exclude buys)
The WHOLE-REPO scoping is unusable (>120s per single floor call; 8151 modules)
and is reported as a finding, not measured per-symbol.
READ-ONLY.
"""
import sys, ast, re, time, random
from collections import deque, defaultdict
from pathlib import Path
sys.path.insert(0, '/home/xnihil0zer0/JanusMaskJR')
from harness.wire_up import discover_live_roots, LIVE_ROOTS, symbol_reachable_from_live_root
from harness.rebuild.discover import discover_modules
random.seed(1729)

NG = Path('/home/xnihil0zer0/NobleGreedv2')

MAIN_GUARD = re.compile(r"(?m)^[ \t]*if[ \t]+__name__[ \t]*==[ \t]*(['\"])__main__\1")


def build(src_root):
    """Return (modules, module_set, graph) using the SAME helpers the floor uses."""
    from harness.wire_up import _resolved_graph
    mods, _t, _s = discover_modules(src_root)
    mods = list(mods)
    mset = set(mods)
    graph = _resolved_graph(src_root, mods)
    return mods, mset, graph


def reachable_modules(graph, mset, roots):
    seeded = {r for r in roots if r in mset}
    reach = set(); q = deque()
    for r in seeded:
        if r not in reach:
            reach.add(r); q.append(r)
    while q:
        cur = q.popleft()
        for dep in graph.get(cur, ()):
            if dep not in reach:
                reach.add(dep); q.append(dep)
    return reach, len(seeded)


def floor_reachable(src_root, graph, mset, reach_cache, module_rel, symbol, roots_key, roots):
    """Replicates symbol_reachable_from_live_root using cached reachable set."""
    if roots_key not in reach_cache:
        reach_cache[roots_key] = reachable_modules(graph, mset, roots)
    reach, _nseed = reach_cache[roots_key]
    if module_rel not in reach:
        return False
    dotted = module_rel[:-3] if module_rel.endswith('.py') else module_rel
    dotted = dotted.replace('/', '.')
    for mprime in reach:  # order irrelevant for any-True
        try:
            tree = ast.parse((src_root / mprime).read_text(encoding='utf-8', errors='ignore'))
        except (OSError, SyntaxError):
            continue
        referenced = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Name):
                referenced.add(node.id)
            elif isinstance(node, ast.Attribute):
                referenced.add(node.attr)
        if mprime == module_rel:
            top_defs = {n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
            if symbol in top_defs and symbol in referenced:
                return True
        else:
            bound = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.ImportFrom) and node.level == 0 and node.module == dotted:
                    for alias in node.names:
                        if alias.name == symbol:
                            bound.add(alias.asname or alias.name)
            if bound & referenced:
                return True
    return False


def declared_roots(src_root, mods, engine_filter):
    mset = set(mods)
    roots = set()
    for m in mods:
        if not engine_filter(m):
            continue
        if m.endswith('run_hunt.py'):
            roots.add(m); continue
        try:
            txt = (src_root / m).read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        if MAIN_GUARD.search(txt):
            roots.add(m)
    return sorted(roots)


def run(label, src_root, engine_filter, declared_filter):
    t0 = time.time()
    mods, mset, graph = build(src_root)
    engine = sorted(m for m in mods if engine_filter(m))
    print(f'\n=== {label}  source_root={src_root}')
    print(f'    total modules={len(mods)}  engine modules={len(engine)}  graph-build={time.time()-t0:.1f}s')
    declared = declared_roots(src_root, mods, declared_filter)
    dlr = discover_live_roots(src_root)
    print(f'    declared roots ({len(declared)}): {declared[:8]}{"..." if len(declared)>8 else ""}')
    print(f'    discover_live_roots ({len(dlr)}): {dlr[:6]}{"..." if len(dlr)>6 else ""}')
    # sample engine symbols
    pairs = []
    for rel in engine:
        try:
            tree = ast.parse((src_root / rel).read_text(encoding='utf-8', errors='ignore'))
        except (OSError, SyntaxError):
            continue
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith('__'):
                pairs.append((rel, n.name))
    if len(pairs) > 600:
        pairs = random.sample(pairs, 600)
    print(f'    measuring {len(pairs)} (module,symbol) pairs')
    variants = {
        '(a) JM LIVE_ROOTS': tuple(LIVE_ROOTS),
        '(b) NGv2 declared roots': tuple(declared),
        '(c) discover_live_roots': tuple(dlr),
    }
    reach_cache = {}
    for vname, roots in variants.items():
        orphan = 0
        for rel, sym in pairs:
            if not floor_reachable(src_root, graph, mset, reach_cache, rel, sym, roots, roots):
                orphan += 1
        reach, nseed = reach_cache[roots]
        pct = 100.0*orphan/len(pairs) if pairs else 0.0
        print(f'    [{vname:26s}] seeds_present={nseed:3d}  reachable_modules={len(reach):4d}  would_be_orphan={orphan}/{len(pairs)} = {pct:.1f}%')
    return pairs


def verify_against_real(src_root, pairs, roots):
    """Spot-check fast floor == real floor on a small random subsample."""
    sub = random.sample(pairs, min(8, len(pairs)))
    mods, mset, graph = build(src_root)
    cache = {}
    mism = 0
    for rel, sym in sub:
        fast = floor_reachable(src_root, graph, mset, cache, rel, sym, roots, roots)
        real = symbol_reachable_from_live_root(src_root, rel, sym, roots=list(roots))
        if fast != real:
            mism += 1
            print(f'    MISMATCH {rel}:{sym} fast={fast} real={real}')
    print(f'    verify: {len(sub)-mism}/{len(sub)} fast==real')


if __name__ == '__main__':
    NG_PKG = NG / 'ngv2'
    pairs_pkg = run('NGV2-PKG', NG_PKG, lambda m: m.endswith('.py'),
                    lambda m: True)
    print('  verifying fast==real (pkg, declared roots):')
    declared_pkg = declared_roots(NG_PKG, build(NG_PKG)[0], lambda m: True)
    verify_against_real(NG_PKG, pairs_pkg, tuple(declared_pkg))

    # PRUNED whole-repo: same source_root but the floor's graph restricted to the
    # ngv2/ engine package only (simulates a per-project source-root/exclude that
    # drops tmp/ targets/ research noise). We do this by filtering the module set
    # passed to _resolved_graph.
    print('\n=== PRUNED-WHOLE-REPO (ngv2/-only module set, JM-repo-root paths) ===')
    from harness.wire_up import _resolved_graph
    mods_all, _t, _s = discover_modules(NG)
    eng_mods = [m for m in mods_all if m.startswith('ngv2/')]
    mset = set(eng_mods)
    graph = _resolved_graph(NG, eng_mods)
    declared = sorted([m for m in eng_mods if m.endswith('run_hunt.py')] +
                      [m for m in eng_mods if MAIN_GUARD.search((NG / m).read_text('utf-8','ignore'))])
    print(f'    engine modules={len(eng_mods)}  declared roots={len(declared)}: {declared[:8]}')
    pairs = []
    for rel in eng_mods:
        try:
            tree = ast.parse((NG / rel).read_text('utf-8','ignore'))
        except (OSError, SyntaxError):
            continue
        for n in tree.body:
            if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and not n.name.startswith('__'):
                pairs.append((rel, n.name))
    if len(pairs) > 600:
        pairs = random.sample(pairs, 600)
    variants = {'(a) JM LIVE_ROOTS': tuple(LIVE_ROOTS),
                '(b) NGv2 declared roots': tuple(declared),
                '(c) discover_live_roots(NG-whole)': tuple(discover_live_roots(NG))}
    cache = {}
    for vname, roots in variants.items():
        orphan = sum(1 for rel, sym in pairs
                     if not floor_reachable(NG, graph, mset, cache, rel, sym, roots, roots))
        reach, nseed = cache[roots]
        pct = 100.0*orphan/len(pairs) if pairs else 0.0
        print(f'    [{vname:32s}] seeds_present={nseed:3d}  reachable={len(reach):4d}  would_be_orphan={orphan}/{len(pairs)} = {pct:.1f}%')
