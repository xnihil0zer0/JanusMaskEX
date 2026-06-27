"""ngv2.gadget_auditor -- deterministic inter-procedural deserialization
allowlist-gadget auditor (closes GAP G1: no inter-procedural gadget analysis).

Secure-deserialization libraries (skops, fickling-style allowlist loaders, the
``torch.load(weights_only=True)`` family) gate loading on a *type-name
allowlist*: a crafted artifact is rejected unless every type it names is
"trusted". The latent risk is a LOGIC bug -- a trusted type whose own
RECONSTRUCTION path (``__reduce__`` / ``__setstate__`` / ``__init__`` /
``__new__`` / ``__getstate__``) reaches a dangerous sink while feeding it
attacker-controlled state. A pure regex/CWE-502 scanner cannot see this: the
sink is several calls deep behind a trusted constructor, so it needs
INTER-PROCEDURAL analysis (this module).

Given a target package source tree and the loader's trusted-type allowlist,
:func:`audit_allowlist_gadgets` statically:

* parses every ``*.py`` file into a class -> reconstruction-method map,
* for each ALLOWLISTED type, walks its reconstruction methods following
  intra-package calls up to a bounded depth, and
* reports candidate GADGET CHAINS ``{trusted_type, sink, sink_kind, path}``
  whenever a reconstruction path reaches a dangerous sink
  (``eval`` / ``exec`` / ``compile`` / ``__import__`` / ``importlib.import_module``
  / ``subprocess`` / ``os.system`` / ``os.popen`` / ``open(..., 'w')`` /
  ``setattr`` to a callable).

The module is PURE and stdlib-only (``ast`` + ``os`` + ``re``): no network,
clock, randomness, uuid, subprocess, or MCP; sorted traversal; output is a
fixed-shape dict so identical inputs are byte-identical. Each gadget finding
carries the SAME finding keys ``ngv2.pattern_scanner`` emits
(``id`` / ``file`` / ``line`` / ``code`` / ``severity`` / ``cwe`` / ``owasp`` /
``description``) so they flow unchanged through ``ngv2.confidence_signals``,
plus gadget-specific ``trusted_type`` / ``sink_kind`` / ``call_path`` keys.

A NON-EMPTY result is a CANDIDATE, not a proven exploit: it names the trusted
source type, the reachable sink, and the inter-procedural call path a human (or
the detonation chamber) must then weaponize. An EMPTY result over a correctly
modelled allowlist is an honest negative -- the allowlist's trusted types are
reconstruction-inert (no audited path reaches a sink), which is exactly the
secure-by-design property the library intends.
"""
from __future__ import annotations
import ast
import os
import re
from typing import Any, Dict, List, Optional, Tuple
__all__ = ['audit_allowlist_gadgets', 'RECONSTRUCTION_METHODS', 'SINK_RULES', 'SKIP_DIRS', 'is_excluded_path']
RECONSTRUCTION_METHODS: Tuple[str, ...] = ('__reduce__', '__reduce_ex__', '__setstate__', '__getstate__', '__init__', '__new__', '__wakeup__', '__init_subclass__')
SINK_RULES: Dict[str, Dict[str, Any]] = {'gadget_eval': {'kind': 'eval', 'match': 'name', 'names': ('eval', 'exec', 'compile'), 'severity': 'critical', 'cwe': 'CWE-502', 'owasp': 'A08:2021-Software and Data Integrity Failures', 'description': 'Reconstruction path reaches eval/exec/compile (code execution).'}, 'gadget_import': {'kind': 'import', 'match': 'name', 'names': ('__import__',), 'severity': 'critical', 'cwe': 'CWE-502', 'owasp': 'A08:2021-Software and Data Integrity Failures', 'description': 'Reconstruction path reaches __import__ (dynamic import / code load).'}, 'gadget_importlib': {'kind': 'import', 'match': 'attr', 'attrs': ('importlib.import_module', 'import_module'), 'severity': 'high', 'cwe': 'CWE-502', 'owasp': 'A08:2021-Software and Data Integrity Failures', 'description': 'Reconstruction path reaches importlib.import_module (dynamic code load).'}, 'gadget_subprocess': {'kind': 'subprocess', 'match': 'attr', 'attrs': ('subprocess.run', 'subprocess.call', 'subprocess.Popen', 'subprocess.check_call', 'subprocess.check_output', 'os.system', 'os.popen', 'os.execv', 'os.execve', 'os.spawnv'), 'severity': 'critical', 'cwe': 'CWE-502', 'owasp': 'A08:2021-Software and Data Integrity Failures', 'description': 'Reconstruction path reaches subprocess/os exec sink (command execution).'}, 'gadget_open_write': {'kind': 'file_write', 'match': 'open_write', 'severity': 'high', 'cwe': 'CWE-502', 'owasp': 'A08:2021-Software and Data Integrity Failures', 'description': "Reconstruction path reaches open(..., 'w'/'a'/'x') (arbitrary file write)."}, 'gadget_setattr': {'kind': 'setattr', 'match': 'name', 'names': ('setattr',), 'severity': 'medium', 'cwe': 'CWE-502', 'owasp': 'A08:2021-Software and Data Integrity Failures', 'description': 'Reconstruction path reaches setattr (can install an attacker callable/descriptor).'}}
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox', '.eggs', '.mypy_cache', 'dist', 'build', '.pytest_cache', '.idea', '.hg', '.svn', 'site-packages', '.cache'}
_MAX_CONTEXT = 150
_MAX_DEPTH = 6
_HIGH_RISK_COUNT = 3
_EXCLUDE_PATH = re.compile('(?:^|/)(?:_vendor/|vendor/|third[_-]?party/|node_modules/|tests?/|testing/|fixtures?/|examples?/|samples?/|demo/|benchmark|docs?/|\\.github/|setup\\.py)', re.IGNORECASE)
_OPEN_MODE = re.compile('[\'\\"][rbtU]*([waxWAX+])[rbtU+]*[\'\\"]')

def is_excluded_path(relpath: str) -> bool:
    """True if ``relpath`` is vendored/test/docs/tooling -- not shipped library
    code whose reconstruction surface an attacker can reach via a loaded file."""
    return bool(_EXCLUDE_PATH.search(relpath.replace('\\', '/')))

def _normalize_allowlist(allowlist: Any) -> set:
    """Coerce the trusted-type allowlist into a set of bare class names and a
    set of fully-qualified ``module.Class`` names. We match a class by EITHER
    its bare name or any dotted suffix, so callers may pass either form."""
    names: set = set()
    if allowlist is None:
        return names
    if isinstance(allowlist, dict):
        allowlist = list(allowlist.keys())
    if isinstance(allowlist, (str, bytes)):
        allowlist = [allowlist]
    for entry in allowlist:
        if isinstance(entry, bytes):
            entry = entry.decode('utf-8', 'replace')
        entry = str(entry).strip()
        if not entry:
            continue
        names.add(entry)
        if '.' in entry:
            names.add(entry.rsplit('.', 1)[1])
    return names

def _attr_dotted(node: ast.AST) -> Optional[str]:
    """Return the dotted name of an attribute/name chain (a.b.c), else None."""
    parts: List[str] = []
    cur = node
    while isinstance(cur, ast.Attribute):
        parts.append(cur.attr)
        cur = cur.value
    if isinstance(cur, ast.Name):
        parts.append(cur.id)
        return '.'.join(reversed(parts))
    return None

def _bare_call_name(call: ast.Call) -> Optional[str]:
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    return None

def _classify_sink(call: ast.Call) -> Optional[Tuple[str, str]]:
    """Return ``(rule_id, sink_kind)`` if this Call node is a dangerous sink."""
    bare = _bare_call_name(call)
    dotted = _attr_dotted(call.func) if isinstance(call.func, ast.Attribute) else None
    for rid, meta in SINK_RULES.items():
        match = meta['match']
        if match == 'name' and bare is not None and (bare in meta['names']):
            return (rid, meta['kind'])
        if match == 'attr' and dotted is not None:
            for cand in meta['attrs']:
                if dotted == cand or dotted.endswith('.' + cand):
                    return (rid, meta['kind'])
        if match == 'open_write' and (bare == 'open' or (dotted or '').endswith('.open')):
            for arg in list(call.args) + [kw.value for kw in call.keywords]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if _OPEN_MODE.search('"' + arg.value + '"'):
                        return (rid, meta['kind'])
    return None

class _ClassCollector(ast.NodeVisitor):
    """Collect, per module, ``{class_name: {method_name: FunctionDef}}`` and a
    flat ``{func_name: FunctionDef}`` for module-level helpers."""

    def __init__(self) -> None:
        self.classes: Dict[str, Dict[str, ast.FunctionDef]] = {}
        self.module_funcs: Dict[str, ast.FunctionDef] = {}

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        methods: Dict[str, ast.FunctionDef] = {}
        for item in node.body:
            if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                methods[item.name] = item
        self.classes[node.name] = methods

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self.module_funcs[node.name] = node

def _calls_in(func: ast.AST) -> List[ast.Call]:
    return [n for n in ast.walk(func) if isinstance(n, ast.Call)]

def _called_method_names(func: ast.AST) -> List[str]:
    """Bare-name and ``self.<m>`` callees inside a function body (for the
    bounded intra-package inter-procedural walk)."""
    out: List[str] = []
    for call in _calls_in(func):
        bare = _bare_call_name(call)
        if bare is not None:
            out.append(bare)
        elif isinstance(call.func, ast.Attribute):
            inner = call.func.value
            if isinstance(inner, ast.Name) and inner.id in ('self', 'cls'):
                out.append(call.func.attr)
    return out

def _walk_for_sink(func: ast.FunctionDef, methods: Dict[str, ast.FunctionDef], module_funcs: Dict[str, ast.FunctionDef], seen: set, depth: int, path: List[str]) -> Optional[Tuple[str, str, ast.Call, List[str]]]:
    """DFS a reconstruction method (and bounded intra-package callees) for the
    first dangerous sink. Returns ``(rule_id, sink_kind, call_node, call_path)``
    or None. Deterministic: callees are visited in source order."""
    if depth > _MAX_DEPTH:
        return None
    for call in _calls_in(func):
        hit = _classify_sink(call)
        if hit is not None:
            rid, kind = hit
            return (rid, kind, call, list(path))
    for callee in _called_method_names(func):
        if callee in seen:
            continue
        target = methods.get(callee) or module_funcs.get(callee)
        if target is None:
            continue
        seen.add(callee)
        sub = _walk_for_sink(target, methods, module_funcs, seen, depth + 1, path + [callee])
        if sub is not None:
            return sub
    return None

def _risk_level(count: int) -> str:
    if count == 0:
        return 'none'
    if count >= _HIGH_RISK_COUNT:
        return 'high'
    if count >= 1:
        return 'medium'
    return 'low'

def audit_allowlist_gadgets(repo_path: str, allowlist: Any) -> Dict[str, Any]:
    """Inter-procedurally audit ``repo_path`` for allowlist-gadget chains.

    Parameters
    ----------
    repo_path : str
        Root of the target package source tree to analyze.
    allowlist : list[str] | dict | str | None
        The loader's trusted-type allowlist. Entries may be bare class names
        (``"TreePredictor"``) or fully-qualified (``"sklearn...TreePredictor"``);
        either form matches. ``None``/empty audits NOTHING (returns the empty
        shape) -- there is no trusted type to originate a gadget from.

    Returns
    -------
    dict
        Fixed-shape, deterministic report. ``findings`` are pattern_scanner-
        shaped finding dicts (with extra ``trusted_type`` / ``sink_kind`` /
        ``call_path`` keys); a non-empty list is a CANDIDATE gadget set to
        weaponize, an empty list is an honest negative (allowlist is
        reconstruction-inert).
    """
    trusted = _normalize_allowlist(allowlist)
    if not os.path.isdir(repo_path):
        return {'repo_path': repo_path, 'files_checked': 0, 'trusted_count': len(trusted), 'has_gadget': False, 'risk_level': 'none', 'total_findings': 0, 'findings': [], 'error': f'Not a directory: {repo_path}'}
    findings: List[Dict[str, Any]] = []
    files_checked = 0
    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = sorted((d for d in dirnames if d not in SKIP_DIRS))
        for fname in sorted(filenames):
            if not fname.endswith('.py'):
                continue
            fullpath = os.path.join(dirpath, fname)
            relpath = os.path.relpath(fullpath, repo_path)
            if is_excluded_path(relpath):
                continue
            try:
                with open(fullpath, 'r', encoding='utf-8', errors='replace') as handle:
                    text = handle.read()
            except OSError:
                continue
            try:
                tree = ast.parse(text)
            except SyntaxError:
                continue
            files_checked += 1
            collector = _ClassCollector()
            collector.visit(tree)
            lines = text.splitlines()
            for cls_name in sorted(collector.classes):
                if cls_name not in trusted:
                    continue
                methods = collector.classes[cls_name]
                for recon in RECONSTRUCTION_METHODS:
                    func = methods.get(recon)
                    if func is None:
                        continue
                    hit = _walk_for_sink(func, methods, collector.module_funcs, seen={recon}, depth=0, path=[recon])
                    if hit is None:
                        continue
                    rid, kind, call, call_path = hit
                    meta = SINK_RULES[rid]
                    lineno = getattr(call, 'lineno', getattr(func, 'lineno', 0))
                    code = lines[lineno - 1].strip()[:_MAX_CONTEXT] if 0 < lineno <= len(lines) else ''
                    findings.append({'id': rid, 'file': relpath, 'line': lineno, 'code': code, 'severity': meta['severity'], 'cwe': meta['cwe'], 'owasp': meta['owasp'], 'description': meta['description'], 'trusted_type': cls_name, 'sink_kind': kind, 'call_path': '%s.%s' % (cls_name, ' -> '.join(call_path))})
    findings.sort(key=lambda f: (f['file'], f['line'], f['trusted_type'], f['id']))
    return {'repo_path': repo_path, 'files_checked': files_checked, 'trusted_count': len(trusted), 'has_gadget': len(findings) > 0, 'risk_level': _risk_level(len(findings)), 'total_findings': len(findings), 'findings': findings}