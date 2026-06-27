"""Deterministic, stdlib-only sink extraction + category reconciliation.

This module gives the hunt/triage pipeline a REPRODUCIBLE way to derive the
canonical dangerous ``sink_name`` (a dotted call name such as
``subprocess.Popen`` or ``asyncio.create_subprocess_exec``) from a code line or
snippet, and to map that sink to the CWE ``category`` it actually implies. It
exists because hunt leads are produced by the agy LLM, whose ``sink_name`` and
``category`` are non-deterministic and frequently disagree (e.g. dbgpt: declared
CWE-22 but the real sink was ``asyncio.create_subprocess_exec`` -> CWE-78).

Pure: no I/O, no clock, no randomness. AST-first (``ast.parse``) with a regex
fallback for snippets that do not parse standalone, so identical inputs always
yield byte-identical output.
"""
from __future__ import annotations
import ast
import re
from typing import Any
from typing import Dict
from typing import List
from typing import Optional
__all__ = ['extract_sink', 'enrich_finding', 'category_for_sink', 'SINK_CATEGORY']
_SINK_RULES: List[tuple] = [('CWE-78', ('os.system', 'os.popen', 'subprocess.popen', 'subprocess.call', 'subprocess.run', 'subprocess.check_output', 'subprocess.check_call', 'asyncio.create_subprocess_exec', 'asyncio.create_subprocess_shell', 'create_subprocess_exec', 'create_subprocess_shell', 'commands.getoutput', 'popen')), ('CWE-95', ('eval', 'exec', 'execfile', 'compile')), ('CWE-502', ('pickle.load', 'pickle.loads', 'cpickle.load', 'cpickle.loads', '_pickle.load', '_pickle.loads', 'marshal.load', 'marshal.loads', 'yaml.load', 'yaml.unsafe_load', 'yaml.full_load', 'torch.load', 'joblib.load', 'dill.load', 'dill.loads')), ('CWE-918', ('requests.get', 'requests.post', 'requests.put', 'requests.delete', 'requests.head', 'requests.patch', 'requests.request', 'urllib.request.urlopen', 'urllib2.urlopen', 'urlopen', 'httpx.get', 'httpx.post', 'httpx.client', 'aiohttp.clientsession')), ('CWE-22', ('open', 'io.open', 'codecs.open', 'os.open', 'send_file', 'send_from_directory', 'shutil.copy', 'shutil.move', 'shutil.rmtree'))]
SINK_CATEGORY: Dict[str, str] = {}
for _cwe, _names in _SINK_RULES:
    for _n in _names:
        SINK_CATEGORY.setdefault(_n, _cwe)
_PRIORITY: Dict[str, int] = {}
for _idx, (_cwe, _names) in enumerate(_SINK_RULES):
    for _n in _names:
        _PRIORITY[_n] = _idx

def category_for_sink(sink_name: str) -> Optional[str]:
    """Return the CWE category implied by ``sink_name`` (dotted or tail)."""
    if not sink_name:
        return None
    low = sink_name.strip().lower()
    if low in SINK_CATEGORY:
        return SINK_CATEGORY[low]
    tail = low.split('.')[-1]
    return SINK_CATEGORY.get(tail)

def _dotted_call_names(snippet: str) -> List[str]:
    """Return dotted call names in source order, AST-first with regex fallback."""
    text = _strip_for_parse(snippet)
    if not text:
        return []
    names: List[str] = []
    parsed = None
    for candidate in (text, 'def _f():\n ' + text.replace('\n', '\n ')):
        try:
            parsed = ast.parse(candidate)
            break
        except SyntaxError:
            parsed = None
    if parsed is not None:
        for node in ast.walk(parsed):
            if isinstance(node, ast.Call):
                dotted = _call_func_name(node.func)
                if dotted:
                    names.append(dotted)
        if names:
            return names
    for match in re.finditer('([A-Za-z_][\\w]*(?:\\.[A-Za-z_][\\w]*)*)\\s*\\(', text):
        names.append(match.group(1))
    return names

def _call_func_name(func: ast.AST) -> Optional[str]:
    parts: List[str] = []
    node = func
    while isinstance(node, ast.Attribute):
        parts.append(node.attr)
        node = node.value
    if isinstance(node, ast.Name):
        parts.append(node.id)
    elif parts:
        pass
    else:
        return None
    return '.'.join(reversed(parts))

def _strip_for_parse(snippet: Any) -> str:
    if not isinstance(snippet, str):
        return ''
    return snippet.strip()

def extract_sink(snippet: str) -> Optional[Dict[str, str]]:
    """Return ``{'sink_name', 'category'}`` for the most dangerous known sink in
    ``snippet``, or ``None`` when no known sink is present. Deterministic.
    """
    names = _dotted_call_names(snippet)
    if not names:
        return None
    best_name: Optional[str] = None
    best_prio = 10 ** 9
    for raw in names:
        low = raw.lower()
        key = low if low in _PRIORITY else low.split('.')[-1]
        if key in _PRIORITY:
            prio = _PRIORITY[key]
            if prio < best_prio:
                best_prio = prio
                best_name = raw
    if best_name is None:
        return None
    category = category_for_sink(best_name)
    if category is None:
        return None
    return {'sink_name': best_name, 'category': category}

def _candidate_snippets(finding: Dict[str, Any]) -> List[str]:
    out: List[str] = []
    cs = finding.get('call_sites')
    if isinstance(cs, list):
        out.extend([s for s in cs if isinstance(s, str) and s.strip()])
    elif isinstance(cs, str) and cs.strip():
        out.append(cs)
    for key in ('code', 'snippet', 'vulnerable_line', 'expected_signature'):
        val = finding.get(key)
        if isinstance(val, str) and val.strip():
            out.append(val)
    return out

def enrich_finding(finding: Dict[str, Any]) -> Dict[str, Any]:
    """Return a COPY of ``finding`` with an accurate ``sink_name`` / ``call_sites``
    and a ``category`` reconciled to the actual sink when they disagree.

    The original mapping is never mutated. When no known sink can be derived the
    finding is returned with its fields untouched (category preserved), so an
    un-extractable finding is never corrupted.
    """
    if not isinstance(finding, dict):
        return finding
    out = dict(finding)
    extracted: Optional[Dict[str, str]] = None
    chosen_snippet: Optional[str] = None
    for snippet in _candidate_snippets(out):
        result = extract_sink(snippet)
        if result is not None:
            extracted = result
            chosen_snippet = snippet
            break
    if extracted is None:
        return out
    out['sink_name'] = extracted['sink_name']
    cs = out.get('call_sites')
    if not (isinstance(cs, list) and any((isinstance(s, str) and s.strip() for s in cs))):
        out['call_sites'] = [chosen_snippet] if chosen_snippet else []
    out['category'] = extracted['category']
    return out