---
interfaces: "creates the NEW standalone module ngv2/gadget_auditor.py -- a deterministic, stdlib-only (ast/os/re) INTER-PROCEDURAL deserialization allowlist-gadget auditor exposing audit_allowlist_gadgets(repo_path, allowlist)->dict, the rules-as-data catalog SINK_RULES, the RECONSTRUCTION_METHODS roots tuple, SKIP_DIRS, and is_excluded_path(relpath)->bool; modelled byte-for-contract on the existing ngv2/pathtrav_detect.py and ngv2/deser_detect.py and emitting gadget findings in the SAME pattern_scanner finding-dict shape (id/file/line/code/severity/cwe/owasp/description) PLUS gadget-specific trusted_type/sink_kind/call_path keys -- making the committed oracle tests/ngv2/test_gadget_auditor_wired.py GREEN (14 tests)"
dependencies: []
working_dir: "/home/xnihil0zer0/NobleGreedv2"
---

# Title

ngv2/gadget_auditor.py -- NEW deterministic INTER-PROCEDURAL deserialization allowlist-gadget auditor (closes GAP G1: no inter-procedural gadget-chain analysis). Secure-deserialization loaders (skops, fickling-style allowlist loaders, `torch.load(weights_only=True)`) gate loading on a *type-name allowlist*; the latent LOGIC bug is a TRUSTED type whose own reconstruction path (`__reduce__`/`__setstate__`/`__init__`/`__new__`/`__getstate__`) reaches a dangerous sink while fed attacker-controlled state. A regex CWE-502 scanner cannot see this -- the sink is several calls deep behind a trusted constructor. This module statically walks each allowlisted type's reconstruction methods (bounded intra-package inter-procedural DFS) and reports candidate gadget chains `{trusted_type, sink, sink_kind, call_path}`.

# Scope

CREATE the NEW single-file module `ngv2/gadget_auditor.py` (NGv2 external-target task -- `working_dir` = /home/xnihil0zer0/NobleGreedv2). This is the inter-procedural sibling of the already-shipped pure recon scanners `ngv2/deser_detect.py` (CWE-502 regex) and `ngv2/pathtrav_detect.py` (CWE-22). The module is PURE and stdlib-only (`ast` + `os` + `re`): no network, clock, randomness, uuid, subprocess, MCP, third-party import, or import of any sibling ngv2 leaf. It walks a caller-supplied repo root, parses each `*.py` into a class->reconstruction-method map, and for each ALLOWLISTED type DFS-walks its reconstruction methods (following `self.<m>` and module-level callees up to a bounded depth) for a dangerous sink. Findings carry the SAME keys `ngv2/pattern_scanner.py` emits (`id`/`file`/`line`/`code`/`severity`/`cwe`/`owasp`/`description`) so they flow unchanged through `ngv2/confidence_signals.py`, PLUS gadget-specific `trusted_type`/`sink_kind`/`call_path` keys.

SINK CLASSES (rules-as-data `SINK_RULES`, all `cwe == 'CWE-502'`): code-exec (`eval`/`exec`/`compile`), dynamic import (`__import__`, `importlib.import_module`), command-exec (`subprocess.*`/`os.system`/`os.popen`/`os.exec*`/`os.spawnv`), write-mode file (`open(..., 'w'/'a'/'x'/'+')`), and `setattr`. A sink is reported ONLY when reachable from a reconstruction method of an ALLOWLISTED class -- a sink in a non-allowlisted class, or in a method never invoked by a reconstruction root, is NOT attacker-reachable and is NOT a finding. An EMPTY result is an honest negative (the allowlist's trusted types are reconstruction-inert), which is the secure-by-design property the library intends.

CRITICAL AST-SAFETY CONSTRAINT: `eval`/`exec`/`compile`/`__import__`/`os.system`/`subprocess.*` appear ONLY as STRING-LITERAL data inside the `SINK_RULES` catalog and in comments -- the module NEVER actually CALLS any of them (the AST enforcer bans those calls). Do NOT introduce any eval/exec/__import__/os.system/subprocess CALL, and do NOT use decorators.

DISPATCH DIRECTIVE -- PATCH FORMAT (MANDATORY -- WHOLE-FILE): this is a NEW single-file module, so emit the COMPLETE file for `ngv2/gadget_auditor.py` (whole-file emission -- NEVER a `__JANUSMASK_PATCHES__` symbol patch, never a manifest, never a dotted qualname). Reproduce it BYTE-FOR-BYTE exactly as follows:

```python
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

__all__ = [
    'audit_allowlist_gadgets',
    'RECONSTRUCTION_METHODS',
    'SINK_RULES',
    'SKIP_DIRS',
    'is_excluded_path',
]

# The dunder methods a deserializer invokes to RECONSTRUCT a trusted instance.
# These are the inter-procedural ROOTS of every candidate gadget chain.
RECONSTRUCTION_METHODS: Tuple[str, ...] = (
    '__reduce__', '__reduce_ex__', '__setstate__', '__getstate__',
    '__init__', '__new__', '__wakeup__', '__init_subclass__',
)

# Dangerous sinks, rules-as-data. Each rule maps a stable id to the metadata a
# pattern_scanner-shaped finding needs, plus a `kind` used by call_path
# reporting. `attr` rules match a dotted-attribute call (e.g. os.system);
# `name` rules match a bare-name call (e.g. eval(...)).
SINK_RULES: Dict[str, Dict[str, Any]] = {
    'gadget_eval': {
        'kind': 'eval', 'match': 'name', 'names': ('eval', 'exec', 'compile'),
        'severity': 'critical', 'cwe': 'CWE-502',
        'owasp': 'A08:2021-Software and Data Integrity Failures',
        'description': 'Reconstruction path reaches eval/exec/compile (code execution).',
    },
    'gadget_import': {
        'kind': 'import', 'match': 'name', 'names': ('__import__',),
        'severity': 'critical', 'cwe': 'CWE-502',
        'owasp': 'A08:2021-Software and Data Integrity Failures',
        'description': 'Reconstruction path reaches __import__ (dynamic import / code load).',
    },
    'gadget_importlib': {
        'kind': 'import', 'match': 'attr', 'attrs': ('importlib.import_module', 'import_module'),
        'severity': 'high', 'cwe': 'CWE-502',
        'owasp': 'A08:2021-Software and Data Integrity Failures',
        'description': 'Reconstruction path reaches importlib.import_module (dynamic code load).',
    },
    'gadget_subprocess': {
        'kind': 'subprocess', 'match': 'attr',
        'attrs': ('subprocess.run', 'subprocess.call', 'subprocess.Popen',
                  'subprocess.check_call', 'subprocess.check_output',
                  'os.system', 'os.popen', 'os.execv', 'os.execve', 'os.spawnv'),
        'severity': 'critical', 'cwe': 'CWE-502',
        'owasp': 'A08:2021-Software and Data Integrity Failures',
        'description': 'Reconstruction path reaches subprocess/os exec sink (command execution).',
    },
    'gadget_open_write': {
        'kind': 'file_write', 'match': 'open_write',
        'severity': 'high', 'cwe': 'CWE-502',
        'owasp': 'A08:2021-Software and Data Integrity Failures',
        'description': "Reconstruction path reaches open(..., 'w'/'a'/'x') (arbitrary file write).",
    },
    'gadget_setattr': {
        'kind': 'setattr', 'match': 'name', 'names': ('setattr',),
        'severity': 'medium', 'cwe': 'CWE-502',
        'owasp': 'A08:2021-Software and Data Integrity Failures',
        'description': 'Reconstruction path reaches setattr (can install an attacker callable/descriptor).',
    },
}

SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox',
             '.eggs', '.mypy_cache', 'dist', 'build', '.pytest_cache', '.idea',
             '.hg', '.svn', 'site-packages', '.cache'}

_MAX_CONTEXT = 150
_MAX_DEPTH = 6
_HIGH_RISK_COUNT = 3

_EXCLUDE_PATH = re.compile(
    r'(?:^|/)(?:_vendor/|vendor/|third[_-]?party/|node_modules/|'
    r'tests?/|testing/|fixtures?/|examples?/|samples?/|demo/|benchmark|'
    r'docs?/|\.github/|setup\.py)',
    re.IGNORECASE,
)
# write-mode literal in an open(...) call: a string arg containing w/a/x/+ but
# not (only) 'r'/'rb'. Matched on the open(...) argument text.
_OPEN_MODE = re.compile(r"""['"][rbtU]*([waxWAX+])[rbtU+]*['"]""")


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
        if match == 'name' and bare is not None and bare in meta['names']:
            return rid, meta['kind']
        if match == 'attr' and dotted is not None:
            for cand in meta['attrs']:
                if dotted == cand or dotted.endswith('.' + cand):
                    return rid, meta['kind']
        if match == 'open_write' and (bare == 'open' or (dotted or '').endswith('.open')):
            # only a WRITE-mode open is a file-write sink
            for arg in list(call.args) + [kw.value for kw in call.keywords]:
                if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                    if _OPEN_MODE.search('"' + arg.value + '"'):
                        return rid, meta['kind']
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
                methods[item.name] = item  # type: ignore[assignment]
        self.classes[node.name] = methods
        # do NOT recurse into nested classes for method maps (kept simple/bounded)

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


def _walk_for_sink(
    func: ast.FunctionDef,
    methods: Dict[str, ast.FunctionDef],
    module_funcs: Dict[str, ast.FunctionDef],
    seen: set,
    depth: int,
    path: List[str],
) -> Optional[Tuple[str, str, ast.Call, List[str]]]:
    """DFS a reconstruction method (and bounded intra-package callees) for the
    first dangerous sink. Returns ``(rule_id, sink_kind, call_node, call_path)``
    or None. Deterministic: callees are visited in source order."""
    if depth > _MAX_DEPTH:
        return None
    for call in _calls_in(func):
        hit = _classify_sink(call)
        if hit is not None:
            rid, kind = hit
            return rid, kind, call, list(path)
    # no direct sink: descend into intra-package callees (self.<m> / module funcs)
    for callee in _called_method_names(func):
        if callee in seen:
            continue
        target = methods.get(callee) or module_funcs.get(callee)
        if target is None:
            continue
        seen.add(callee)
        sub = _walk_for_sink(
            target, methods, module_funcs, seen, depth + 1, path + [callee]
        )
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
        return {'repo_path': repo_path, 'files_checked': 0, 'trusted_count': len(trusted),
                'has_gadget': False, 'risk_level': 'none', 'total_findings': 0,
                'findings': [], 'error': f'Not a directory: {repo_path}'}

    findings: List[Dict[str, Any]] = []
    files_checked = 0
    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
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
                # An empty allowlist has no trusted type to originate a gadget
                # from, so nothing is audited (honest empty result).
                if cls_name not in trusted:
                    continue
                methods = collector.classes[cls_name]
                for recon in RECONSTRUCTION_METHODS:
                    func = methods.get(recon)
                    if func is None:
                        continue
                    hit = _walk_for_sink(
                        func, methods, collector.module_funcs,
                        seen={recon}, depth=0, path=[recon],
                    )
                    if hit is None:
                        continue
                    rid, kind, call, call_path = hit
                    meta = SINK_RULES[rid]
                    lineno = getattr(call, 'lineno', getattr(func, 'lineno', 0))
                    code = lines[lineno - 1].strip()[:_MAX_CONTEXT] if 0 < lineno <= len(lines) else ''
                    findings.append({
                        'id': rid, 'file': relpath, 'line': lineno, 'code': code,
                        'severity': meta['severity'], 'cwe': meta['cwe'],
                        'owasp': meta['owasp'], 'description': meta['description'],
                        'trusted_type': cls_name, 'sink_kind': kind,
                        'call_path': '%s.%s' % (cls_name, ' -> '.join(call_path)),
                    })

    findings.sort(key=lambda f: (f['file'], f['line'], f['trusted_type'], f['id']))
    return {'repo_path': repo_path, 'files_checked': files_checked,
            'trusted_count': len(trusted), 'has_gadget': len(findings) > 0,
            'risk_level': _risk_level(len(findings)),
            'total_findings': len(findings), 'findings': findings}
```

POST-EMIT SELF-CHECK (mandatory): the emitted file defines exactly the five public names in `__all__` (`audit_allowlist_gadgets`, `RECONSTRUCTION_METHODS`, `SINK_RULES`, `SKIP_DIRS`, `is_excluded_path`); every `SINK_RULES` value has `cwe == 'CWE-502'` and a `match` in `{name, attr, open_write}`; `RECONSTRUCTION_METHODS` contains `__reduce__`/`__setstate__`/`__init__`; the module imports only `ast`/`os`/`re`/`typing`; there is NO eval/exec/__import__/os.system/subprocess CALL and NO decorator anywhere; an empty/None allowlist audits nothing (`cls_name not in trusted` skips every class).

# Required plan shape

EXACTLY ONE impl task. Use this task_id VERBATIM (the committed oracle and any operator decision file are keyed to it): `task_id`: `ngv2_gadget_auditor`. meta_task_type=`data_model` (NEW pure stdlib analysis module -- single-file whole-file emission, no production-harness edit). priority: high. dependencies: []. working_dir: "/home/xnihil0zer0/NobleGreedv2". files_touched: `["ngv2/gadget_auditor.py"]` ONLY. partial_edit semantics: WHOLE-FILE single-file emission per the DISPATCH DIRECTIVE -- the DISPATCH DIRECTIVE -- PATCH FORMAT block above (including the full pinned file content) MUST be copied VERBATIM into the task's `implementation_notes` so the blind worker sees it. verification_command: `python3 -m pytest -q tests/ngv2/test_gadget_auditor_wired.py` (CWD-relative -- NO `cd`). The committed RED oracle tests/ngv2/test_gadget_auditor_wired.py is the authoritative acceptance contract -- make it GREEN (14 tests); do NOT author new tests. `spec.functional_requirements` MUST be CONSOLIDATED to at most 5 entries, and `test_spec.unit_tests` MUST enumerate AT LEAST as many entries as `spec.functional_requirements` (validator floor: len(unit_tests) >= len(functional_requirements)); unit_tests entries are descriptors NAMING committed-oracle test cases (this does NOT authorize authoring new tests). `test_spec.regression_tests` MUST list at least two entries that NAME existing test cases from the committed oracle, e.g. `test_interprocedural_setstate_to_os_system_is_a_gadget`, `test_inert_setstate_is_honest_negative`, `test_sink_in_untrusted_class_is_not_reported`.

# Non-Goals

Do NOT touch `ngv2/pattern_scanner.py`, `ngv2/deser_detect.py`, `ngv2/pathtrav_detect.py`, `ngv2/confidence_signals.py`, `ngv2/codeql_runner.py`, or any other existing module -- this leaf ships ONLY the new `ngv2/gadget_auditor.py`. Catalog/scan-path INTEGRATION (wiring `audit_allowlist_gadgets` into the live scan catalog, selection_ranker demand terms, or sink_taxonomy weights) is OUT OF SCOPE -- a separate downstream EDIT leaf. Do NOT author or modify any test -- the oracle is committed and authoritative. Do NOT add real dataflow/SSA/symbolic execution, network, wall-clock, randomness, subprocess, or logging. Do NOT import any third-party package or any sibling `ngv2/**` leaf. The bounded intra-package DFS (depth <= 6, `self.<m>`/module-func callees, source-order) is the ONLY reachability proxy in scope. CRITICAL: do NOT introduce any eval/exec/__import__/os.system/subprocess CALL or any decorator (AST enforcer bans them); the sink names live ONLY as string-literal data in SINK_RULES.

# Inputs

The committed authoritative oracle tests/ngv2/test_gadget_auditor_wired.py (currently RED -- module does not yet exist). It pins (14 cases): (i) the rules-as-data contract -- `SINK_RULES` non-empty, every value has keys `{kind,match,severity,cwe,owasp,description}` with `cwe == 'CWE-502'` and `match in {name,attr,open_write}`, and the kinds cover `{eval, subprocess, import}`; `RECONSTRUCTION_METHODS` is a non-empty tuple superset of `{__reduce__,__setstate__,__init__}`; (ii) `SKIP_DIRS` superset; (iii) POSITIVE inter-procedural detection -- a trusted class whose `__setstate__` calls `self._apply(state)` which calls `os.system(...)` IS a `gadget_subprocess` finding whose `call_path` contains both `__setstate__` and `_apply`; a direct `eval(expr)` in `__init__` is a `gadget_eval` (severity critical); a write-mode `open(state["p"], "w")` in `__setstate__` is `gadget_open_write`; (iv) NEGATIVES -- inert `self.__dict__.update(state)` setstate is NOT a gadget (honest negative, risk_level none); a sink in a class ABSENT from the allowlist is NOT reported; a sink in a non-reconstruction method (`run`) never invoked by `__setstate__` is NOT reported; (v) excluded paths (`tests/conftest.py` skipped, `is_excluded_path('skops/io/_general.py') is False`); the non-directory `error` shape; empty/None allowlist audits nothing (`trusted_count == 0`); byte-stable determinism; and fully-qualified allowlist entries (`sklearn...TreePredictor`) match by suffix. Finding dicts carry `{id,file,line,code,severity,cwe,owasp,description}` PLUS `{trusted_type,sink_kind,call_path}`. Real-corpus grounding (skops v0.14): the newly-trusted GB/HGB sklearn internal types' reconstruction methods are inert (`__dict__.update`), so the auditor returns ZERO gadgets over that allowlist -- a tool-backed honest negative. stdlib only (`ast`, `os`, `re`, `typing`).

# Deliverables

The NEW file `ngv2/gadget_auditor.py` exactly as pinned in the DISPATCH DIRECTIVE: rules-as-data `SINK_RULES` (6 CWE-502 sink rules across name/attr/open_write match kinds), `RECONSTRUCTION_METHODS`, `SKIP_DIRS`, `is_excluded_path`, and `audit_allowlist_gadgets(repo_path, allowlist)->dict` whose gadget findings match the pattern_scanner finding shape plus trusted_type/sink_kind/call_path. Verified GREEN by `python3 -m pytest -q tests/ngv2/test_gadget_auditor_wired.py` (14 passed).
