"""FAITHFUL implementation of the REVISED Phase-1 primitive, transcribed
DIRECTLY from brief_hooks_wire_up_runtime_observe_primitive.md (TASK 2 Impl
Notes 2 & 3). This is what the impl task would add to harness/wire_up.py.

Key revised properties under test:
  - observe_symbol_execution is a CLASS context manager
  - __enter__ saves prior tracer, CLOBBERS via sys.settrace(self._trace) +
    threading.settrace(self._trace) (does NOT chain)
  - __exit__ restores the EXACT prior tracer via try/finally
  - the trace callback records, on a 'call' event for a watched top-level name,
    the IMMEDIATE caller's frame.f_back.f_code.co_filename (PROVENANCE)
  - .executed(name) -> observation only
  - .reached_from(name) -> immediate caller's co_filename (FIRST observed)
  - .executed_from_live_root(name, live_root_files) -> True ONLY when the
    immediate caller's file is in the LIVE_ROOT set (rel-path seed matched
    robustly against the absolute caller filename)
  - new_top_level_callables widens into module-scope If/Try/With (one level)
"""
import ast
import os
import sys
import threading


def new_top_level_callables(parent_src, child_src):
    """AST-diff enumerator. Returns SORTED names that are top-level callables in
    child_src but not in parent_src. Top-level callable = module-scope
    def/async def, a top-level `name = lambda` assignment, AND a def/async def
    nested ONE level inside a module-scope If/Try/With body. Fail-soft: an
    unparseable child returns []."""

    def _collect(src):
        names = set()
        if not src:
            return names
        try:
            tree = ast.parse(src)
        except (SyntaxError, ValueError):
            return names

        def _direct_funcdefs(body):
            for n in body or []:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    names.add(n.name)

        for node in tree.body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                names.add(node.name)
            elif isinstance(node, ast.Assign):
                if isinstance(node.value, ast.Lambda) and len(node.targets) == 1 and isinstance(node.targets[0], ast.Name):
                    names.add(node.targets[0].id)
            elif isinstance(node, ast.If):
                _direct_funcdefs(node.body)
                _direct_funcdefs(node.orelse)
            elif isinstance(node, ast.Try):
                _direct_funcdefs(node.body)
                _direct_funcdefs(node.orelse)
                _direct_funcdefs(node.finalbody)
                for h in node.handlers:
                    _direct_funcdefs(h.body)
            elif isinstance(node, ast.With):
                _direct_funcdefs(node.body)
        return names

    try:
        child = _collect(child_src)
    except Exception:
        return []
    parent = _collect(parent_src)
    return sorted(child - parent)


class observe_symbol_execution:
    """sys.settrace + threading.settrace observer. Records which watched
    top-level functions executed AND the IMMEDIATE caller's source file."""

    def __init__(self, qualnames):
        self._watched = set(qualnames or [])
        self._executed = set()
        self._reached_from = {}
        self._prior = None
        self._prior_thread = None

    def _trace(self, frame, event, arg):
        try:
            if event == 'call':
                code = frame.f_code
                nm = code.co_name
                if nm in self._watched:
                    qn = getattr(code, 'co_qualname', nm)
                    if qn == nm:  # module-top-level (not a method / nested def)
                        self._executed.add(nm)
                        if nm not in self._reached_from:
                            back = frame.f_back
                            self._reached_from[nm] = back.f_code.co_filename if back is not None else None
        except Exception:
            pass
        return self._trace

    def __enter__(self):
        self._prior = sys.gettrace()
        try:
            self._prior_thread = threading.gettrace()
        except AttributeError:
            self._prior_thread = None
        sys.settrace(self._trace)
        threading.settrace(self._trace)
        return self

    def __exit__(self, *exc):
        try:
            sys.settrace(self._prior)
        finally:
            try:
                threading.settrace(self._prior_thread)
            except Exception:
                threading.settrace(None)
        return False

    def executed(self, name):
        """OBSERVATION ONLY -- NOT a wiring proof (a manufactured caller satisfies it)."""
        return name in self._executed

    def reached_from(self, name):
        return self._reached_from.get(name)

    @property
    def reached(self):
        return set(self._executed)

    def executed_from_live_root(self, name, live_root_files):
        if name not in self._executed:
            return False
        caller = self._reached_from.get(name)
        if not caller:
            return False
        caller_real = os.path.realpath(caller)
        caller_norm = caller_real.replace('\\', '/')
        for lr in live_root_files or []:
            lr_norm = str(lr).replace('\\', '/').lstrip('./')
            # rel-path LIVE_ROOT seed must match the absolute caller filename:
            # exact, or the caller path ends with the full rel-path on a path
            # boundary (so 'harness/orchestrator.py' matches
            # '/abs/.../harness/orchestrator.py' but NOT 'evil_orchestrator.py').
            if caller_norm == lr_norm or caller_norm.endswith('/' + lr_norm):
                return True
        return False
