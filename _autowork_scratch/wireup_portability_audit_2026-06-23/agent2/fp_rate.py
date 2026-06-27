#!/usr/bin/env python3
"""Agent2 FP-rate measurement: run the per-symbol FLOOR
symbol_reachable_from_live_root over NGv2 symbols under three root regimes:
  (a) hardcoded JM LIVE_ROOTS (the gate's current default)
  (b) plausible NGv2 declared roots (run_hunt conductor + ngv2 __main__ guards)
  (c) discover_live_roots auto-discovery

We measure would_be_orphan% = fraction of NEW top-level callables that the floor
reports as NOT reachable (i.e. the gate would flag as orphan / FP storm).

Source-root scoping matters: the gate uses repo_root = staging worktree (the
WHOLE tree). We measure BOTH:
  - WHOLE-REPO source root (what the gate actually does today)
  - ngv2/-scoped source root (what a per-project wire_up.roots + a sane source
    root would buy)
READ-ONLY. No state mutation.
"""
import sys, ast, random
from pathlib import Path
sys.path.insert(0, '/home/xnihil0zer0/JanusMaskJR')

from harness.wire_up import symbol_reachable_from_live_root, discover_live_roots, LIVE_ROOTS
from harness.rebuild.discover import discover_modules

NG = Path('/home/xnihil0zer0/NobleGreedv2')
NG_PKG = NG / 'ngv2'

random.seed(1729)


def top_level_callables(src_root: Path, rel: str):
    try:
        tree = ast.parse((src_root / rel).read_text(encoding='utf-8', errors='ignore'))
    except (OSError, SyntaxError):
        return []
    return [n.name for n in tree.body if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]


def measure(src_root: Path, label: str, roots_variants: dict, sample_modules):
    """For each root regime, compute would_be_orphan% over (module,symbol) pairs."""
    pairs = []  # (rel, sym)
    for rel in sample_modules:
        for sym in top_level_callables(src_root, rel):
            if sym.startswith('__'):
                continue
            pairs.append((rel, sym))
    print(f'\n=== {label} (source_root={src_root}) ===')
    print(f'    sampled modules={len(sample_modules)}  symbol pairs={len(pairs)}')
    results = {}
    for rname, roots in roots_variants.items():
        present = [r for r in roots if (src_root / r).is_file()]
        orphan = 0
        for rel, sym in pairs:
            try:
                reachable = symbol_reachable_from_live_root(src_root, rel, sym, roots=roots)
            except Exception:
                reachable = False
            if not reachable:
                orphan += 1
        pct = 100.0 * orphan / len(pairs) if pairs else 0.0
        results[rname] = (orphan, len(pairs), pct, len(present))
        print(f'    [{rname:28s}] roots_present={len(present):3d}  would_be_orphan={orphan}/{len(pairs)} = {pct:.1f}%')
    return results


def ngv2_declared_roots(src_root: Path, rel_prefix=''):
    """Plausible per-project roots a human/brief would declare for NGv2:
    the run_hunt conductor + every ngv2-package module with a __main__ guard."""
    mods, _t, _s = discover_modules(src_root)
    mset = set(mods)
    roots = set()
    main_guard = __import__('re').compile(r"(?m)^[ \t]*if[ \t]+__name__[ \t]*==[ \t]*(['\"])__main__\1")
    for m in mods:
        # restrict to the engine package, not scratch/PoC noise
        if not (m == 'run_hunt.py' or m.startswith('ngv2/') or m == 'ngv2.py'):
            continue
        if m.endswith('run_hunt.py'):
            roots.add(m)
            continue
        try:
            srctext = (src_root / m).read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        if main_guard.search(srctext):
            roots.add(m)
    return sorted(roots)


def main():
    # ---- Regime 1: WHOLE-REPO source root (what the gate does on a real accept) ----
    whole_mods, _t, _s = discover_modules(NG)
    whole_set = set(whole_mods)
    ngv2_engine = sorted(m for m in whole_mods if m.startswith('ngv2/') and m.endswith('.py'))
    print(f'WHOLE-REPO modules={len(whole_mods)}  ngv2-engine modules={len(ngv2_engine)}')

    declared_whole = ngv2_declared_roots(NG)
    print(f'NGv2 declared roots (engine __main__ + run_hunt), whole-repo view: {len(declared_whole)}')
    for r in declared_whole[:15]:
        print('   ', r)

    # sample of ngv2-engine modules (cap for runtime; floor is O(modules) per call)
    sample = ngv2_engine if len(ngv2_engine) <= 40 else random.sample(ngv2_engine, 40)
    sample = sorted(sample)

    variants_whole = {
        '(a) JM LIVE_ROOTS': LIVE_ROOTS,
        '(b) NGv2 declared roots': declared_whole,
        '(c) discover_live_roots': discover_live_roots(NG),
    }
    res_whole = measure(NG, 'WHOLE-REPO source root', variants_whole, sample)

    # ---- Regime 2: ngv2/-scoped source root (per-project source root + roots) ----
    if NG_PKG.is_dir():
        pkg_mods, _t2, _s2 = discover_modules(NG_PKG)
        pkg_engine = sorted(m for m in pkg_mods if m.endswith('.py'))
        print(f'\nNGV2-PKG-SCOPED modules={len(pkg_mods)}')
        declared_pkg = ngv2_declared_roots_pkg(NG_PKG)
        print(f'NGv2 declared roots (pkg-scoped): {len(declared_pkg)}: {declared_pkg[:10]}')
        sample_pkg = pkg_engine if len(pkg_engine) <= 40 else sorted(random.sample(pkg_engine, 40))
        variants_pkg = {
            '(a) JM LIVE_ROOTS': LIVE_ROOTS,
            '(b) NGv2 declared roots': declared_pkg,
            '(c) discover_live_roots': discover_live_roots(NG_PKG),
        }
        measure(NG_PKG, 'NGV2-PKG-SCOPED source root', variants_pkg, sample_pkg)


def ngv2_declared_roots_pkg(src_root: Path):
    mods, _t, _s = discover_modules(src_root)
    roots = set()
    main_guard = __import__('re').compile(r"(?m)^[ \t]*if[ \t]+__name__[ \t]*==[ \t]*(['\"])__main__\1")
    for m in mods:
        if m == 'run_hunt.py':
            roots.add(m); continue
        try:
            srctext = (src_root / m).read_text(encoding='utf-8', errors='ignore')
        except OSError:
            continue
        if main_guard.search(srctext):
            roots.add(m)
    return sorted(roots)


if __name__ == '__main__':
    main()
