"""A FAITHFUL implementation of the Phase-1 primitive exactly as the brief specs it.

Brief text (verbatim, paraphrased to the load-bearing rules):
  observe_symbol_execution(qualnames): context manager. On __enter__ save
  sys.gettrace(); install a trace fn that, on each 'call' event, checks
  frame.f_code.co_name against the watched set and (top-level: co_qualname ==
  bare name on 3.11+, else fall back to co_name) marks executed. CHAIN to the
  prior tracer. On __exit__ restore prior tracer (try/finally). Never raise from
  the callback. .executed(name)->bool, .reached set.

  "For local-frame tracing to fire on nested calls, the global trace must return
  a local-trace callable per the standard sys.settrace protocol; a top-level
  'call' match is sufficient for this primitive (we only watch top-level
  callables)."

  new_top_level_callables(parent_src, child_src) -> sorted list[str]: AST diff;
  top-level FunctionDef/AsyncFunctionDef + top-level `name = <Lambda>` (single
  Name target). Fail-soft: unparseable child -> []. None/empty/unparseable
  parent -> empty parent set. Class methods / nested defs / non-lambda
  assignments NOT in scope.

This file makes NO judgements; it is the literal primitive so the limitation
scripts exercise the real thing, not a strawman.
"""
from __future__ import annotations
import ast
import sys


def new_top_level_callables(parent_src, child_src):
    def _top_level_callables(src):
        if not src:
            return set()
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError):
            return None  # signal unparseable
        names = set()
        for node in tree.body:  # MODULE SCOPE ONLY
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign) and isinstance(node.value, ast.Lambda):
                if len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    names.add(node.targets[0].id)
        return names

    child = _top_level_callables(child_src)
    if child is None:  # unparseable child -> fail soft
        return []
    parent = _top_level_callables(parent_src)
    if parent is None:  # unparseable parent -> treat as empty set
        parent = set()
    return sorted(child - parent)


class observe_symbol_execution:
    def __init__(self, qualnames):
        self._watch = set(qualnames or [])
        self._reached = set()
        self._prior = None

    def _trace(self, frame, event, arg):
        try:
            if event == 'call':
                code = frame.f_code
                name = code.co_name
                if name in self._watch:
                    qn = getattr(code, 'co_qualname', None)
                    # top-level: co_qualname == bare name on 3.11+, else fall back
                    if qn is None or qn == name:
                        self._reached.add(name)
        except Exception:
            pass
        # CHAIN to prior tracer (return a local-trace callable per protocol)
        if self._prior is not None:
            try:
                local = self._prior(frame, event, arg)
            except Exception:
                local = None
        else:
            local = None
        # Return our trace so local-frame events keep flowing; if prior gave a
        # local tracer we'd lose its locals, but the brief says top-level 'call'
        # match is sufficient. Return self._trace so nested calls still fire 'call'.
        return self._trace if local is None else local

    def __enter__(self):
        self._prior = sys.gettrace()
        sys.settrace(self._trace)
        return self

    def __exit__(self, *exc):
        try:
            sys.settrace(self._prior)
        finally:
            self._prior = None
        return False

    def executed(self, name):
        return name in self._reached

    @property
    def reached(self):
        return set(self._reached)
