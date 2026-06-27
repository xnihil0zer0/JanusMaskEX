"""Pure, deterministic, stdlib-only AST classifier for PoC authenticity.

This module statically classifies a Proof-of-Concept's *source text* into one of
``{real_target, self_contained_mock, network_live}`` and reports whether a
``confirmed`` verdict may be emitted for it. A PoC that merely mocks or
re-implements the target (rather than exercising the real software) is gated:
``may_confirm`` is ``False`` for ``self_contained_mock``.

The module NEVER runs, imports, execs, or detonates the PoC -- it only parses
the source with :mod:`ast` and inspects the resulting tree. All sink / library
identifiers below (eval, exec, requests, socket, urllib, http.client, ...) live
strictly as string-literal data compared against AST-extracted names; none of
them is ever called.
"""
import ast
from typing import Dict
from typing import List
from typing import Optional
from typing import Set
from typing import Tuple
_NETWORK_MODULE_PREFIXES: Tuple[str, ...] = ('requests', 'socket', 'urllib', 'http.client')
_LOCAL_VULN_NAME_TOKENS: Tuple[str, ...] = ('vuln', 'mock', 'handler', 'server', 'route')
_LOCAL_SERVER_BASE_NAMES: Tuple[str, ...] = ('HTTPServer', 'ThreadingHTTPServer', 'BaseHTTPServer', 'BaseHTTPRequestHandler', 'SimpleHTTPRequestHandler', 'BaseRequestHandler', 'StreamRequestHandler')
_LOCALHOST_TOKENS: Tuple[str, ...] = ('localhost', '127.0.0.1', '0.0.0.0', '::1')
_MODE_REAL_TARGET = 'real_target'
_MODE_SELF_CONTAINED_MOCK = 'self_contained_mock'
_MODE_NETWORK_LIVE = 'network_live'

def _split_parts(dotted: str) -> List[str]:
    """Split a possibly-dotted module name into its components."""
    return [part for part in dotted.split('.') if part != '']

def _name_prefix_matches(module: str, candidate: str) -> bool:
    """True if ``module`` and ``candidate`` share a leading dotted-path prefix.

    Either may be a prefix of the other: ``pkg`` matches ``pkg.sub`` and
    ``pkg.sub`` matches ``pkg``.
    """
    mod_parts = _split_parts(module)
    cand_parts = _split_parts(candidate)
    if not mod_parts or not cand_parts:
        return False
    shared = min(len(mod_parts), len(cand_parts))
    return mod_parts[:shared] == cand_parts[:shared]

def _is_network_module(module: str) -> bool:
    """True if ``module`` is (a sub-path of) a known network library."""
    parts = _split_parts(module)
    for prefix in _NETWORK_MODULE_PREFIXES:
        pref_parts = _split_parts(prefix)
        depth = len(pref_parts)
        if parts[:depth] == pref_parts:
            return True
    return False

def _call_root_name(func: ast.AST) -> Optional[str]:
    """Return the leftmost ``Name`` identifier of a call's func expression."""
    node = func
    while isinstance(node, ast.Attribute):
        node = node.value
    if isinstance(node, ast.Name):
        return node.id
    return None

def _base_simple_name(base: ast.AST) -> Optional[str]:
    """Return the simple attribute/name of a class base expression."""
    if isinstance(base, ast.Name):
        return base.id
    if isinstance(base, ast.Attribute):
        return base.attr
    return None

def _mock_result() -> Dict[str, object]:
    """Fixed-shape result for sources that cannot be shown to exercise a target."""
    return {'mode': _MODE_SELF_CONTAINED_MOCK, 'imports_target': False, 'defines_vuln_locally': False, 'issues_network_request': False, 'may_confirm': False}

def _local_def_is_vulnish(node: ast.AST) -> bool:
    """True if a function/class definition stands in for vulnerable behavior."""
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
        lowered = node.name.lower()
        return any((token in lowered for token in _LOCAL_VULN_NAME_TOKENS))
    if isinstance(node, ast.ClassDef):
        lowered = node.name.lower()
        if any((token in lowered for token in _LOCAL_VULN_NAME_TOKENS)):
            return True
        for base in node.bases:
            simple = _base_simple_name(base)
            if simple is not None and simple in _LOCAL_SERVER_BASE_NAMES:
                return True
    return False

def classify_poc_authenticity(poc_source: str, target_import_names: List[str]) -> dict:
    """Statically classify a PoC's source text for verdict gating.

    Parameters
    ----------
    poc_source:
        The PoC's Python source TEXT. It is parsed once with :func:`ast.parse`
        and never executed. Empty/whitespace-only or unparsable source is
        treated as a self-contained mock.
    target_import_names:
        Names of the real target packages/modules. A target is matched by
        top-level package equality OR any shared dotted-path prefix.

    Returns
    -------
    dict
        A fixed-shape dict with EXACTLY the keys ``mode``, ``imports_target``,
        ``defines_vuln_locally``, ``issues_network_request`` and ``may_confirm``.
        ``mode`` is one of ``real_target``, ``self_contained_mock`` or
        ``network_live``; the other three are booleans; and
        ``may_confirm == (mode != 'self_contained_mock')``.
    """
    targets: List[str] = [str(name) for name in target_import_names or []]
    if poc_source is None or poc_source.strip() == '':
        return _mock_result()
    try:
        tree = ast.parse(poc_source)
    except SyntaxError:
        return _mock_result()
    except (ValueError, TypeError):
        return _mock_result()
    target_bound_names: Set[str] = set()
    network_bound_names: Set[str] = set()
    references: Set[str] = set()
    has_local_vuln_def = False
    targets_localhost = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                module = alias.name
                bound = alias.asname or _split_parts(module)[0]
                if any((_name_prefix_matches(module, t) for t in targets)):
                    target_bound_names.add(bound)
                if _is_network_module(module):
                    network_bound_names.add(bound)
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ''
            module_is_target = bool(module) and any((_name_prefix_matches(module, t) for t in targets))
            module_is_network = _is_network_module(module)
            for alias in node.names:
                if alias.name == '*':
                    continue
                bound = alias.asname or alias.name
                if module_is_target:
                    target_bound_names.add(bound)
                if module_is_network:
                    network_bound_names.add(bound)
        elif isinstance(node, ast.Name):
            if isinstance(node.ctx, ast.Load):
                references.add(node.id)
        elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if _local_def_is_vulnish(node):
                has_local_vuln_def = True
        elif isinstance(node, ast.Constant) and isinstance(node.value, str):
            lowered = node.value.lower()
            if any((token in lowered for token in _LOCALHOST_TOKENS)):
                targets_localhost = True
    has_target_call = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            root = _call_root_name(node.func)
            if root is not None and root in target_bound_names:
                has_target_call = True
                break
    imports_target = bool(target_bound_names) and has_target_call
    issues_network_request = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            root = _call_root_name(node.func)
            if root is not None and root in network_bound_names:
                issues_network_request = True
                break
    defines_vuln_locally = has_local_vuln_def and (not imports_target)
    if imports_target:
        mode = _MODE_REAL_TARGET
    elif issues_network_request and (not defines_vuln_locally) and (not targets_localhost):
        mode = _MODE_NETWORK_LIVE
    else:
        mode = _MODE_SELF_CONTAINED_MOCK
    may_confirm = mode != _MODE_SELF_CONTAINED_MOCK
    return {'mode': mode, 'imports_target': imports_target, 'defines_vuln_locally': defines_vuln_locally, 'issues_network_request': issues_network_request, 'may_confirm': may_confirm}