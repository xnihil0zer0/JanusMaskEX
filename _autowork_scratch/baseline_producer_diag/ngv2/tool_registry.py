"""Deterministic tool-registry capability for ngv2.

Distilled from the legacy ``services/tool_forge.py``: parse a ``TOOL_META``
header out of a tool script, validate the script, register it into a JSON
catalog with stable usage statistics, and append reflection / usage log lines.

All impurity is pushed behind injected seams: the compiler is an injected
``compile_check`` callable (see :func:`make_mock_compiler`) and every clock is
an injected ``now`` callable, so the module is fully deterministic and depends
only on the Python standard library.
"""
from __future__ import annotations
import json
import os
import re
from typing import Any, Callable, Dict, List, Optional, Tuple
REQUIRED_META_FIELDS: Tuple[str, ...] = ('name', 'description', 'inputs', 'outputs')
CATALOG_TOOL_FIELDS: Tuple[str, ...] = ('path', 'name', 'description', 'inputs', 'outputs', 'tags', 'cwe_relevant', 'created_by', 'created_cycle', 'created_at', 'usage_count', 'success_rate', 'avg_time_saved_s', 'compute')
_META_FIELD_RE = re.compile('^\\s+([A-Za-z_]\\w*):\\s*(.*?)\\s*$')

def _parse_meta_value(raw: str) -> Any:
    """Coerce a raw ``key: value`` string into a list / int / float / str."""
    raw = raw.strip()
    if raw.startswith('[') and raw.endswith(']'):
        inner = raw[1:-1].strip()
        if not inner:
            return []
        return [item.strip() for item in inner.split(',')]
    try:
        return int(raw)
    except ValueError:
        pass
    try:
        return float(raw)
    except ValueError:
        pass
    return raw

def extract_tool_meta(file_path: str) -> Optional[Dict[str, Any]]:
    """Return the parsed ``TOOL_META`` mapping for a tool script.

    Returns ``None`` when the file is missing or contains no ``TOOL_META``
    block.
    """
    if not os.path.isfile(file_path):
        return None
    with open(file_path, 'r') as handle:
        lines = handle.read().splitlines()
    start = None
    for index, line in enumerate(lines):
        if line.strip() == 'TOOL_META:':
            start = index
            break
    if start is None:
        return None
    meta: Dict[str, Any] = {}
    for line in lines[start + 1:]:
        if not line.strip():
            break
        match = _META_FIELD_RE.match(line)
        if not match:
            break
        field_name = match.group(1)
        meta[field_name] = _parse_meta_value(match.group(2))
    return meta if meta else None

def make_mock_compiler(rc: int=0, stderr: str='') -> Callable[[str], Tuple[int, str]]:
    """Return a test-double compiler callable.

    The returned callable accepts a file path and yields a ``(returncode,
    stderr)`` tuple, mirroring the real ``py_compile`` subprocess seam without
    ever touching a real interpreter.
    """

    def compiler(file_path: str) -> Tuple[int, str]:
        return (rc, stderr)
    return compiler

def validate_tool(file_path: str, compile_check: Callable[[str], Tuple[int, str]]) -> Tuple[bool, List[str]]:
    """Validate a tool script, returning ``(ok, errors)``.

    A missing file short-circuits to a single ``File not found`` error.
    Otherwise the injected ``compile_check`` provides syntax results and the
    ``TOOL_META`` block is checked for the required fields.
    """
    if not os.path.isfile(file_path):
        return (False, ['File not found: ' + file_path])
    errors: List[str] = []
    returncode, stderr = compile_check(file_path)
    if returncode != 0:
        errors.append('Syntax error: ' + (stderr or '').strip())
    meta = extract_tool_meta(file_path)
    if meta is None:
        errors.append('Missing TOOL_META block')
    else:
        for field_name in REQUIRED_META_FIELDS:
            if field_name not in meta:
                errors.append('TOOL_META missing required field: ' + field_name)
    return (len(errors) == 0, errors)

def test_tool(file_path: str, compile_check: Callable[[str], Tuple[int, str]]) -> bool:
    """Validate-and-boolean entry point (the registry's pass/fail check)."""
    ok, _errors = validate_tool(file_path, compile_check=compile_check)
    return ok
test_tool.__test__ = False

def load_catalog(catalog_path: str) -> Dict[str, Any]:
    """Load the JSON catalog, defaulting to an empty catalog when absent."""
    if not os.path.isfile(catalog_path):
        return {'tools': {}, 'updated_at': None}
    with open(catalog_path, 'r') as handle:
        return json.load(handle)

def save_catalog(catalog: Dict[str, Any], catalog_path: str, now: Callable[[], Any]) -> None:
    """Stamp ``updated_at`` from the injected clock and persist the catalog."""
    catalog['updated_at'] = now()
    with open(catalog_path, 'w') as handle:
        json.dump(catalog, handle)

def register_tool(file_path: str, catalog_path: str, compile_check: Callable[[str], Tuple[int, str]], now: Callable[[], Any]=lambda: None) -> bool:
    """Validate a tool and, if valid, write a catalog record for it.

    Returns ``True`` on success. A validation failure performs no write.
    """
    ok, _errors = validate_tool(file_path, compile_check=compile_check)
    if not ok:
        return False
    meta = extract_tool_meta(file_path) or {}
    record: Dict[str, Any] = {'path': file_path, 'name': meta.get('name'), 'description': meta.get('description'), 'inputs': meta.get('inputs', []), 'outputs': meta.get('outputs', []), 'tags': meta.get('tags', []), 'cwe_relevant': meta.get('cwe_relevant', []), 'created_by': meta.get('created_by'), 'created_cycle': meta.get('created_cycle'), 'created_at': now(), 'usage_count': 0, 'success_rate': 0.0, 'avg_time_saved_s': meta.get('avg_time_saved_s', 0.0), 'compute': meta.get('compute', 'cpu')}
    catalog = load_catalog(catalog_path)
    catalog.setdefault('tools', {})[record['name']] = record
    save_catalog(catalog, catalog_path, now=now)
    return True

def log_reflection(cron: str, cycle: int, actions_taken: List[Any], patterns_found: List[Any], tool_created: Optional[str]=None, path: Optional[str]=None, now: Callable[[], Any]=lambda: None) -> None:
    """Append a single reflection record as a JSONL line."""
    record = {'timestamp': now(), 'cron': cron, 'cycle': cycle, 'actions_taken': actions_taken, 'patterns_found': patterns_found, 'tool_created': tool_created}
    with open(path, 'a') as handle:
        handle.write(json.dumps(record) + '\n')

def log_tool_usage(tool: str, task_context: str, outcome: str, time_saved_s: float=0.0, usage_path: Optional[str]=None, catalog_path: Optional[str]=None, now: Callable[[], Any]=lambda: None) -> None:
    """Append a usage record and refresh the tool's catalog statistics.

    The usage line is always written. If the tool is present in the catalog,
    its ``usage_count`` and ``success_rate`` are updated and the catalog is
    re-saved; an unknown tool only emits the usage line.
    """
    record = {'timestamp': now(), 'tool': tool, 'task_context': task_context, 'outcome': outcome, 'time_saved_s': time_saved_s}
    with open(usage_path, 'a') as handle:
        handle.write(json.dumps(record) + '\n')
    catalog = load_catalog(catalog_path)
    tools = catalog.get('tools', {})
    if tool in tools:
        entry = tools[tool]
        prior_count = entry.get('usage_count', 0)
        prior_rate = entry.get('success_rate', 0.0)
        successes = int(round(prior_rate * prior_count))
        if outcome == 'success':
            successes += 1
        new_count = prior_count + 1
        entry['usage_count'] = new_count
        entry['success_rate'] = round(successes / new_count, 3)
        save_catalog(catalog, catalog_path, now=now)