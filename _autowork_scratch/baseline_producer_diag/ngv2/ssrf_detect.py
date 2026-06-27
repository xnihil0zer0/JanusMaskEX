"""ngv2.ssrf_detect -- deterministic CWE-918 (Server-Side Request Forgery) scanner.

A PURE filesystem recon tool, modelled exactly on ``ngv2.deser_detect``: it
walks a caller-supplied repository root, scans ``*.py`` files for HTTP-client
*sinks* whose request URL is plausibly attacker-influenced (``requests`` /
``urllib`` / ``httpx``), and returns a fixed-shape report dict whose
``findings`` carry the SAME finding keys ``ngv2.pattern_scanner`` emits
(``id`` / ``file`` / ``line`` / ``code`` / ``severity`` / ``cwe`` / ``owasp`` /
``description``) so they flow unchanged through
``ngv2.confidence_signals.resolve_signals``.

Determinism / purity contract (identical to deser_detect):

* No network, clock, randomness, uuid, subprocess, or MCP.
* Filesystem access stays within the caller-provided root.
* Sorted directory traversal -> byte-stable output for identical inputs.
* All regexes compiled once at import time.

False-positive control (the SSRF analog of ``_e2e_run/sink_quality.py``):

* ``is_excluded_path`` drops vendored / test / docs / examples / tooling files
  -- a sink there is not a shipped, attacker-reachable library sink.
* A sink whose URL argument is a single hardcoded string literal with no
  dynamic marker (e.g. ``requests.get("https://fixed.api/x")``) is NOT a
  finding; only dynamic / name / f-string / concatenated URLs are flagged.
* Pure comment / docstring lines never match.
"""
from __future__ import annotations
import os
import re
from typing import Any, Dict, List
__all__ = ['detect_ssrf', 'SSRF_RULES', 'SKIP_DIRS', 'is_excluded_path']
SSRF_RULES: Dict[str, Dict[str, str]] = {'ssrf_requests': {'pattern': '\\brequests\\.(?:get|post|put|patch|delete|head|request)\\s*\\(', 'severity': 'high', 'cwe': 'CWE-918', 'owasp': 'A10:2021-Server-Side Request Forgery', 'description': 'HTTP request via requests with a non-constant URL (possible SSRF).'}, 'ssrf_urllib': {'pattern': '\\b(?:urllib\\.request\\.urlopen|urlopen|urllib\\.request\\.Request)\\s*\\(', 'severity': 'high', 'cwe': 'CWE-918', 'owasp': 'A10:2021-Server-Side Request Forgery', 'description': 'urllib URL open with a non-constant URL (possible SSRF).'}, 'ssrf_httpx': {'pattern': '\\bhttpx\\.(?:get|post|put|patch|delete|head|request|stream)\\s*\\(', 'severity': 'high', 'cwe': 'CWE-918', 'owasp': 'A10:2021-Server-Side Request Forgery', 'description': 'HTTP request via httpx with a non-constant URL (possible SSRF).'}}
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox', '.eggs', '.mypy_cache', 'dist', 'build', '.pytest_cache', '.idea', '.hg', '.svn', 'site-packages', '.cache'}
_MAX_CONTEXT = 150
_HIGH_RISK_COUNT = 5
_EXCLUDE_PATH = re.compile('(?:^|/)(?:_vendor/|vendor/|third[_-]?party/|node_modules/|tests?/|testing/|fixtures?/|examples?/|samples?/|demo/|benchmark|docs?/|scripts?/|_scripts/|ci/|\\.github/|tools?/|setup\\.py)', re.IGNORECASE)
_PURE_STR_ARG = re.compile('\\(\\s*[rbfu]*([\'\\"]).*?\\1\\s*(?:,|\\))')
_STR_LITERAL = re.compile('([rbuRBU]*)([\'\\"]).*?\\2')
_FSTRING = re.compile('\\b[rbuRBU]*[fF][rbuRBU]*[\'\\"]')
_DYN_STRUCT = re.compile('%|\\.format\\b|\\+')
_DYN_WORDS = re.compile('\\b(?:url|uri|endpoint|host|target|link|addr|address|server|req|request|user|param|params|input|base_?url|dep)\\b', re.IGNORECASE)
_COMPILED: List[tuple] = [(rid, re.compile(meta['pattern'])) for rid, meta in SSRF_RULES.items()]

def is_excluded_path(relpath: str) -> bool:
    """True if ``relpath`` is vendored/test/docs/tooling -- not a shipped sink."""
    return bool(_EXCLUDE_PATH.search(relpath.replace('\\', '/')))

def _blank_literals(s: str) -> str:
    """Replace string-literal bodies with empty quotes so dynamic markers found
    INSIDE a literal (e.g. ``user`` in ``"https://user.example.com"``) don't
    falsely make the argument look dynamic."""
    return _STR_LITERAL.sub(lambda m: m.group(1) + m.group(2) * 2, s)

def _is_literal_url_call(code: str, match_end: int) -> bool:
    """True if the sink's URL argument is a pure hardcoded string literal with
    no dynamic marker -- e.g. ``requests.get("https://fixed.api/x")`` -- i.e.
    NOT SSRF. Dynamic markers are evaluated on the arguments with literal
    bodies blanked, so content inside the URL string never counts."""
    tail = code[match_end - 1:]
    blanked = _blank_literals(tail)
    if _FSTRING.search(tail) or _DYN_STRUCT.search(blanked) or _DYN_WORDS.search(blanked):
        return False
    return bool(_PURE_STR_ARG.match(tail))

def _risk_level(count: int) -> str:
    if count == 0:
        return 'none'
    if count >= _HIGH_RISK_COUNT:
        return 'high'
    if count >= 2:
        return 'medium'
    return 'low'

def detect_ssrf(repo_path: str) -> Dict[str, Any]:
    """Scan ``repo_path`` for CWE-918 SSRF sinks with dynamic URLs.

    Returns a deterministic, fixed-shape dict. A non-directory ``repo_path``
    yields the same shape with an ``error`` key and no findings.
    """
    if not os.path.isdir(repo_path):
        return {'repo_path': repo_path, 'files_checked': 0, 'has_ssrf': False, 'risk_level': 'none', 'total_findings': 0, 'findings': [], 'error': f'Not a directory: {repo_path}'}
    files_checked = 0
    findings: List[Dict[str, Any]] = []
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
            files_checked += 1
            for lineno, raw in enumerate(text.splitlines(), start=1):
                stripped = raw.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                for rid, regex in _COMPILED:
                    m = regex.search(raw)
                    if not m:
                        continue
                    if _is_literal_url_call(raw, m.end()):
                        continue
                    meta = SSRF_RULES[rid]
                    findings.append({'id': rid, 'file': relpath, 'line': lineno, 'code': stripped[:_MAX_CONTEXT], 'severity': meta['severity'], 'cwe': meta['cwe'], 'owasp': meta['owasp'], 'description': meta['description']})
    findings.sort(key=lambda f: (f['file'], f['line'], f['id']))
    return {'repo_path': repo_path, 'files_checked': files_checked, 'has_ssrf': len(findings) > 0, 'risk_level': _risk_level(len(findings)), 'total_findings': len(findings), 'findings': findings}