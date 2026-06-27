"""Faithful implementation of the brief's `check_new_symbols_called` primitive.

Implemented STRICTLY per brief_hooks_wire_up_symbol_caller_gate.md TASK 2
"IMPLEMENTATION NOTES" (lines 364-430):

 - top-level callables = module-scope FunctionDef / AsyncFunctionDef / top-level
   `name = <lambda>` assignment.
 - NEW symbols = child top-level callables whose name is NOT a parent top-level
   callable name.
 - "A caller exists iff the bare symbol name appears as an ast.Name / ast.Attribute
   reference (NOT a def/class name, NOT an import alias target) in ANY in-scope
   source module -- OR as the imported name in `from <mod> import <symbol>`
   followed by any reference."  (brief lines 416-421)
 - exclude tuple mirrors sweep_modules + scratch.
 - A reference WITHIN the defining module by another (non-new) function counts.

The brief explicitly states (Non-Goals lines 254-264 / 419) this is the GENERAL
"is this name referenced in source" heuristic -- reference EXISTENCE, not live
reachability. This module reproduces that semantics so we can probe whether a
DEAD static caller fools it.
"""
from __future__ import annotations
import ast
from dataclasses import dataclass, field
from pathlib import Path

# mirror sweep_modules EXCLUDE plus scratch (brief line 411)
EXCLUDE = ('_archive/', '_autowork_archive/', 'samples/', 'scripts/', 'tests/',
           'venv/', '_autowork_scratch/')


@dataclass
class SymbolWireResult:
    ok: bool
    unwired: list[str] = field(default_factory=list)
    exempted: list[str] = field(default_factory=list)
    new_symbols: list[str] = field(default_factory=list)
    reason: str = ''


def _toplevel_callables(tree: ast.Module) -> set[str]:
    names: set[str] = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            names.add(node.name)
        elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
            for tgt in node.targets:
                if isinstance(tgt, ast.Name):
                    names.add(tgt.id)
    return names


def _discover_source_modules(repo_root: Path) -> list[str]:
    """Best-effort non-test/non-scratch .py module list. The brief says use
    discover_modules; here we walk and apply EXCLUDE (+ test files) so this probe
    is self-contained and matches the brief's intended scope."""
    out: list[str] = []
    for p in sorted(repo_root.rglob('*.py')):
        rel = p.relative_to(repo_root).as_posix()
        if any(rel.startswith(x) for x in EXCLUDE):
            continue
        if 'tests/' in rel or rel.startswith('tests/'):
            continue
        name = p.name
        if name.startswith('test_') or name.endswith('_test.py'):
            continue
        out.append(rel)
    return out


def _name_referenced_in_module(tree: ast.Module, symbol: str, *, is_defining: bool) -> bool:
    """The brief's caller test: bare symbol name appears as an ast.Name /
    ast.Attribute reference, NOT a def/class name, NOT an import alias target.
    Also `from <mod> import <symbol>` counts (imported name)."""
    # def/class nodes whose .name == symbol are NOT references (definition sites)
    for node in ast.walk(tree):
        # from-import of the symbol counts as a reference (wiring intent)
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == symbol:
                    return True
        if isinstance(node, ast.Import):
            continue
        if isinstance(node, ast.Name) and node.id == symbol:
            return True
        if isinstance(node, ast.Attribute) and node.attr == symbol:
            return True
    return False


def check_new_symbols_called(repo_root, module_rel, parent_src, *, exempt=()) -> SymbolWireResult:
    repo_root = Path(repo_root)
    exempt = set(exempt or ())
    child_path = repo_root / module_rel
    try:
        child_tree = ast.parse(child_path.read_text(encoding='utf-8', errors='ignore'))
    except (OSError, SyntaxError):
        return SymbolWireResult(ok=True, reason='child unparseable; symbol check skipped')
    try:
        parent_tree = ast.parse(parent_src) if parent_src else ast.parse('')
    except SyntaxError:
        parent_tree = ast.parse('')

    child_syms = _toplevel_callables(child_tree)
    parent_syms = _toplevel_callables(parent_tree)
    new_syms = sorted(child_syms - parent_syms)

    source_modules = _discover_source_modules(repo_root)

    unwired: list[str] = []
    exempted: list[str] = []
    for sym in new_syms:
        if sym in exempt:
            exempted.append(sym)
            continue
        called = False
        for rel in source_modules:
            is_defining = (rel == module_rel)
            try:
                mtree = ast.parse((repo_root / rel).read_text(encoding='utf-8', errors='ignore'))
            except (OSError, SyntaxError):
                continue
            if is_defining:
                # exclude the symbol's OWN def site: walk all bodies EXCEPT the
                # top-level def of `sym` itself. A reference by a SIBLING (incl
                # the new sibling) counts per brief lines 421/263.
                ref = False
                for node in mtree.body:
                    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == sym:
                        continue  # skip own def site
                    sub = ast.Module(body=[node], type_ignores=[])
                    if _name_referenced_in_module(sub, sym, is_defining=True):
                        ref = True
                        break
                if ref:
                    called = True
                    break
            else:
                if _name_referenced_in_module(mtree, sym, is_defining=False):
                    called = True
                    break
        if not called:
            unwired.append(sym)
    unwired.sort()
    exempted.sort()
    ok = (len(unwired) == 0)
    if unwired:
        reason = 'new uncalled top-level symbols: ' + ', '.join(unwired)
    else:
        reason = 'all new top-level callables are referenced in source (or exempt)'
    return SymbolWireResult(ok=ok, unwired=unwired, exempted=exempted,
                            new_symbols=new_syms, reason=reason)
