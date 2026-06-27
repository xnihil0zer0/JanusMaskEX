"""Faithful re-implementation of the PHASE 1 primitives exactly as the brief
`brief_hooks_wire_up_runtime_observe_primitive.md` (TASK 2) describes them.

This is NOT a strawman: it follows the brief's IMPLEMENTATION NOTES verbatim:
  - new_top_level_callables(parent_src, child_src) -> sorted list[str] via AST diff
  - observe_symbol_execution(qualnames): a sys.settrace context manager that records
    which named top-level functions had their body EXECUTE inside the `with` block,
    chaining to the prior tracer, restoring on exit, never raising from the callback.

Used by the gaming demonstrations to prove the gate semantics.
"""
from __future__ import annotations
import ast
import sys


def new_top_level_callables(parent_src, child_src):
    """AST diff: names of top-level def/async-def/lambda-assignment callables
    present in child but not parent. Fail-soft: child unparseable -> []."""
    def _top_level(src):
        names = set()
        if not src:
            return names
        try:
            tree = ast.parse(src)
        except SyntaxError:
            return names
        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
                for tgt in node.targets:
                    if isinstance(tgt, ast.Name):
                        names.add(tgt.id)
        return names

    try:
        ast.parse(child_src)
    except SyntaxError:
        return []
    parent_names = _top_level(parent_src)
    child_names = _top_level(child_src)
    return sorted(child_names - parent_names)


class observe_symbol_execution:
    """sys.settrace context manager recording which watched top-level functions
    executed (a Python call frame entered) while active. Chains to the prior
    tracer; restores on exit; never raises from the callback."""

    def __init__(self, qualnames):
        self._watched = set(qualnames)
        self._executed = set()
        self._prior = None

    def _trace(self, frame, event, arg):
        try:
            if event == 'call':
                name = frame.f_code.co_name
                if name in self._watched:
                    # confirm module-top-level: qualname == bare name on 3.11+
                    qn = getattr(frame.f_code, 'co_qualname', name)
                    if qn == name:
                        self._executed.add(name)
        except Exception:
            pass
        # chain to prior tracer
        if self._prior is not None:
            try:
                return self._prior(frame, event, arg)
            except Exception:
                return self._trace
        return self._trace

    def __enter__(self):
        self._prior = sys.gettrace()
        sys.settrace(self._trace)
        return self

    def __exit__(self, *exc):
        sys.settrace(self._prior)
        return False

    def executed(self, name):
        return name in self._executed

    @property
    def reached(self):
        return set(self._executed)
