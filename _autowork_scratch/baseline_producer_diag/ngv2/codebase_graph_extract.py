"""Deterministic codebase-to-graph extraction for ngv2.

Turns a Python/shell codebase into MASFactory-compatible "vibe graph" JSON via
pure programmatic AST + regex extraction. There is no AI, no network, and no
live execution involved -- the module only reads source text and emits plain
dict / JSON structures.

All behaviour is deterministic: the same inputs always produce the same output.
The only timestamp-style field (``metadata['generated_at']``) is produced by an
explicit, fixed deterministic helper rather than a wall clock, so repeated runs
are byte-identical.
"""
from __future__ import annotations
import ast
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
GENERATOR_VERSION: str = 'codebase_graph_extract/1.0'
EXCLUDE_DIRS: tuple = ('__pycache__', '.git', '.venv', 'venv', 'node_modules', '.mypy_cache', '.pytest_cache', '.tox', '.eggs', 'build', 'dist')
ITEM_FIELDS: tuple = ('name', 'type', 'source', 'lineno', 'calls', 'imports', 'parent')
NODE_FIELDS: tuple = ('name', 'type', 'instructions', 'prompt_template')
ENTRY_SENTINEL: str = 'ENTRY'
EXIT_SENTINEL: str = 'EXIT'
DEFAULT_GENERATED_AT: str = '1970-01-01T00:00:00Z'
_SHELL_KEYWORDS: frozenset = frozenset({'if', 'then', 'else', 'elif', 'fi', 'for', 'while', 'until', 'do', 'done', 'case', 'esac', 'function', 'return', 'in', 'select', 'time', '{', '}', '[[', ']]', '[', ']', '!'})
_IDENT_RE = re.compile('^[A-Za-z_][A-Za-z0-9_]*$')

def _timestamp() -> str:
    """Return a deterministic ``generated_at`` value (no wall clock)."""
    return DEFAULT_GENERATED_AT

def _dedupe(seq: List[str]) -> List[str]:
    """Order-preserving de-duplication of a list of strings."""
    seen: set = set()
    out: List[str] = []
    for item in seq:
        if item not in seen:
            seen.add(item)
            out.append(item)
    return out

def _make_node(label: str, instructions: str='', prompt_template: str='') -> Dict[str, str]:
    """Build a graph node carrying exactly the canonical ``NODE_FIELDS``."""
    return {'name': label, 'type': 'action', 'instructions': instructions, 'prompt_template': prompt_template}

def _boundary_edges(node_names: List[str], edges: List[List[str]]) -> List[List[str]]:
    """Add ENTRY/EXIT sentinel edges around the given node set.

    Nodes with no incoming edge get an ``ENTRY -> node`` edge; nodes with no
    outgoing edge get a ``node -> EXIT`` edge. If there are no nodes/edges at
    all a single ``ENTRY -> EXIT`` edge is produced.
    """
    incoming = {dst for _, dst in edges}
    for name in node_names:
        if name not in incoming:
            edges.append([ENTRY_SENTINEL, name])
    outgoing = {src for src, _ in edges if src != ENTRY_SENTINEL}
    for name in node_names:
        if name not in outgoing:
            edges.append([name, EXIT_SENTINEL])
    if not edges:
        edges.append([ENTRY_SENTINEL, EXIT_SENTINEL])
    return edges

def _dotted_name(node: ast.AST) -> Optional[str]:
    """Render a call target node as a dotted string (or None)."""
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        base = _dotted_name(node.value)
        if base is None:
            return node.attr
        return base + '.' + node.attr
    return None

def _collect_calls(node: ast.AST) -> List[str]:
    """Collect dotted call targets within an AST node, de-duplicated."""
    calls: List[str] = []
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            rendered = _dotted_name(sub.func)
            if rendered:
                calls.append(rendered)
    return _dedupe(calls)

def _collect_imports(tree: ast.AST) -> List[str]:
    """Collect module-level imported names (asname when present)."""
    names: List[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                names.append(alias.asname or alias.name.split('.')[0])
        elif isinstance(node, ast.ImportFrom):
            for alias in node.names:
                names.append(alias.asname or alias.name)
    return _dedupe(names)

def _make_item(label: str, item_type: str, node: ast.AST, source: str, imports: List[str], parent: str) -> Dict[str, Any]:
    """Build an item dict carrying exactly the canonical ``ITEM_FIELDS``."""
    if item_type == 'class':
        calls: List[str] = []
    else:
        calls = _collect_calls(node)
    try:
        segment = ast.get_source_segment(source, node) or ''
    except (TypeError, ValueError):
        segment = ''
    return {'name': label, 'type': item_type, 'source': segment, 'lineno': getattr(node, 'lineno', 1), 'calls': calls, 'imports': list(imports), 'parent': parent}

def parse_python_file(path: str) -> List[Dict[str, Any]]:
    """Extract functions, classes and methods from a Python source file.

    Returns a list of item dicts (see ``ITEM_FIELDS``). A missing file or a
    syntax error yields an empty list rather than raising.
    """
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            source = handle.read()
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []
    imports = _collect_imports(tree)
    items: List[Dict[str, Any]] = []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            items.append(_make_item(node.name, 'function', node, source, imports, ''))
        elif isinstance(node, ast.ClassDef):
            items.append(_make_item(node.name, 'class', node, source, imports, ''))
            for sub in node.body:
                if isinstance(sub, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    qualified = node.name + '.' + sub.name
                    items.append(_make_item(qualified, 'method', sub, source, imports, node.name))
    return items

def build_call_graph(modules: Dict[str, List[Dict[str, Any]]]) -> Dict[str, List[str]]:
    """Resolve raw call strings against known item names.

    ``modules`` maps module name -> list of item dicts. The result maps an item
    name to the de-duplicated, order-preserving list of item names it calls.
    ``self.foo`` calls resolve to ``Parent.foo`` when that method exists.
    """
    all_items: List[Dict[str, Any]] = []
    for items in modules.values():
        all_items.extend(items)
    known = {item['name'] for item in all_items}
    graph: Dict[str, List[str]] = {}
    for item in all_items:
        resolved: List[str] = []
        for call in item['calls']:
            target: Optional[str] = None
            if call.startswith('self.') and item['parent']:
                candidate = item['parent'] + '.' + call[len('self.'):]
                if candidate in known:
                    target = candidate
            elif call in known:
                target = call
            if target is not None and target not in resolved:
                resolved.append(target)
        graph[item['name']] = resolved
    return graph

def emit_module_graph(source_file: str, items: List[Dict[str, Any]], graph: Dict[str, List[str]]) -> Dict[str, Any]:
    """Emit a module-level graph design + metadata for one source file."""
    nodes = [_make_node(item['name'], '%s %s' % (item['type'], item['name'])) for item in items]
    node_names = [item['name'] for item in items]
    node_set = set(node_names)
    edges: List[List[str]] = []
    for src in node_names:
        for dst in graph.get(src, []):
            if dst in node_set:
                edges.append([src, dst])
    edges = _boundary_edges(node_names, edges)
    base = Path(source_file).stem
    graph_design = {'name': 'module_' + base, 'description': 'Module graph for ' + source_file, 'nodes': nodes, 'edges': edges}
    metadata = {'source_file': source_file, 'generator': GENERATOR_VERSION, 'node_count': len(nodes), 'edge_count': len(edges), 'generated_at': _timestamp()}
    return {'graph_design': graph_design, 'metadata': metadata}

def emit_package_graph(pkg_name: str, modules: Dict[str, List[Dict[str, Any]]]) -> Dict[str, Any]:
    """Emit a package-level graph whose nodes are the contained modules."""
    module_names = list(modules.keys())
    nodes = [_make_node(modname, 'module ' + modname) for modname in module_names]
    edges: List[List[str]] = []
    for modname in module_names:
        edges.append([ENTRY_SENTINEL, modname])
        edges.append([modname, EXIT_SENTINEL])
    if not edges:
        edges.append([ENTRY_SENTINEL, EXIT_SENTINEL])
    graph_design = {'name': 'package_' + pkg_name, 'description': 'Package graph for ' + pkg_name, 'nodes': nodes, 'edges': edges}
    metadata = {'source_dir': pkg_name, 'generator': GENERATOR_VERSION, 'node_count': len(nodes), 'edge_count': len(edges), 'generated_at': _timestamp()}
    return {'graph_design': graph_design, 'metadata': metadata}

def emit_callchain_graph(entry: str, graph: Dict[str, List[str]], lookup: Dict[str, Dict[str, Any]], max_depth: int=10) -> Dict[str, Any]:
    """Emit a call-chain graph reachable from ``entry`` up to ``max_depth``."""
    order: List[str] = []
    seen: set = set()
    queue: List[tuple] = [(entry, 0)]
    while queue:
        name, depth = queue.pop(0)
        if name in seen:
            continue
        seen.add(name)
        order.append(name)
        if depth >= max_depth:
            continue
        for callee in graph.get(name, []):
            if callee not in seen:
                queue.append((callee, depth + 1))
    nodes = [_make_node(name, 'call ' + name) for name in order]
    edges: List[List[str]] = []
    for name in order:
        for callee in graph.get(name, []):
            if callee in seen:
                edges.append([name, callee])
    edges = _boundary_edges(order, edges)
    graph_design = {'name': 'callgraph_' + entry, 'description': 'Call-chain graph from ' + entry, 'nodes': nodes, 'edges': edges}
    metadata = {'entry_point': entry, 'generator': GENERATOR_VERSION, 'node_count': len(nodes), 'edge_count': len(edges), 'generated_at': _timestamp()}
    return {'graph_design': graph_design, 'metadata': metadata}

def emit_full_graph(packages: Dict[str, List[str]]) -> Dict[str, Any]:
    """Emit a top-level graph describing every package and its modules."""
    nodes: List[Dict[str, str]] = []
    edges: List[List[str]] = []
    for pkg, mods in packages.items():
        nodes.append(_make_node(pkg, 'package ' + pkg))
        edges.append([ENTRY_SENTINEL, pkg])
        for mod in mods:
            nodes.append(_make_node(mod, 'module ' + mod))
            edges.append([pkg, mod])
            edges.append([mod, EXIT_SENTINEL])
    if not edges:
        edges.append([ENTRY_SENTINEL, EXIT_SENTINEL])
    graph_design = {'name': 'full_codebase', 'description': 'Full codebase graph', 'nodes': nodes, 'edges': edges}
    metadata = {'generator': GENERATOR_VERSION, 'node_count': len(nodes), 'edge_count': len(edges), 'generated_at': _timestamp()}
    return {'graph_design': graph_design, 'metadata': metadata}
_FUNC_RE = re.compile('^\\s*(?:function\\s+)?([A-Za-z_][A-Za-z0-9_]*)\\s*\\(\\)\\s*\\{?\\s*$')
_VAR_RE = re.compile('^\\s*(?:export\\s+)?([A-Za-z_][A-Za-z0-9_]*)=')

def _command_tokens(line: str) -> List[str]:
    """Return the leading token of each command segment on a shell line."""
    tokens: List[str] = []
    for segment in re.split('[;&|]+', line):
        segment = segment.strip()
        if not segment:
            continue
        first = segment.split()[0]
        tokens.append(first)
    return tokens

def parse_shell_file(path: str) -> List[Dict[str, Any]]:
    """Extract functions and top-level variable assignments from a shell file.

    Functions capture the commands they invoke (control keywords filtered out).
    A missing/unreadable file yields an empty list rather than raising.
    """
    try:
        with open(path, 'r', encoding='utf-8') as handle:
            text = handle.read()
    except (OSError, UnicodeDecodeError):
        return []
    items: List[Dict[str, Any]] = []
    depth = 0
    current: Optional[Dict[str, Any]] = None
    for lineno, raw in enumerate(text.splitlines(), start=1):
        if depth == 0:
            func_match = _FUNC_RE.match(raw)
            if func_match:
                current = {'name': func_match.group(1), 'type': 'function', 'source': raw, 'lineno': lineno, 'calls': [], 'imports': [], 'parent': ''}
                items.append(current)
                depth += raw.count('{') - raw.count('}')
                if depth < 0:
                    depth = 0
                if depth == 0:
                    current = None
                continue
            var_match = _VAR_RE.match(raw)
            if var_match:
                items.append({'name': var_match.group(1), 'type': 'variable', 'source': raw, 'lineno': lineno, 'calls': [], 'imports': [], 'parent': ''})
                continue
        else:
            if current is not None:
                for token in _command_tokens(raw):
                    if token in _SHELL_KEYWORDS:
                        continue
                    if not _IDENT_RE.match(token):
                        continue
                    if token not in current['calls']:
                        current['calls'].append(token)
            depth += raw.count('{') - raw.count('}')
            if depth <= 0:
                depth = 0
                current = None
    return items

def walk_repo(root: str) -> List[Path]:
    """Walk ``root`` collecting ``.py`` / ``.sh`` files, excluding noise dirs.

    Returns a deterministically sorted list of ``Path`` objects.
    """
    excluded = set(EXCLUDE_DIRS)
    found: List[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in excluded]
        for filename in filenames:
            if filename.endswith('.py') or filename.endswith('.sh'):
                found.append(Path(dirpath) / filename)
    return sorted(found)

def write_index(out_dir: str, graph_files: List[Dict[str, Any]]) -> Path:
    """Write the ``_index.json`` manifest and return its path."""
    out_path = Path(out_dir)
    out_path.mkdir(parents=True, exist_ok=True)
    index_path = out_path / '_index.json'
    payload = {'generator': GENERATOR_VERSION, 'graphs': graph_files, 'generated_at': _timestamp()}
    index_path.write_text(json.dumps(payload, indent=2, sort_keys=False), encoding='utf-8')
    return index_path