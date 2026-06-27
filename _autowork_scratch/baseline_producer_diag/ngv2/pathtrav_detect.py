"""ngv2.pathtrav_detect -- deterministic CWE-22 (Path Traversal) scanner.

A PURE filesystem recon tool, modelled exactly on ``ngv2.deser_detect``: it
walks a caller-supplied repository root, scans ``*.py`` files for path/archive
*sinks* that can be steered outside an intended directory, and returns a
fixed-shape report dict whose ``findings`` carry the SAME finding keys
``ngv2.pattern_scanner`` emits (``id`` / ``file`` / ``line`` / ``code`` /
``severity`` / ``cwe`` / ``owasp`` / ``description``) so they flow unchanged
through ``ngv2.confidence_signals.resolve_signals``.

Two sink tiers:

* INTRINSIC sinks -- archive extraction (``.extractall`` / ``tarfile.open`` /
  ``zipfile.ZipFile``) and Flask file serving (``send_file`` /
  ``send_from_directory``). These are the classic ML "Zip/Tar Slip" and
  download-endpoint CWE-22 vectors; flagged whenever present (an extracted
  archive member or a served path is attacker-controlled by definition).
* TAINTED sinks -- ``open(...)`` and ``os.path.join(...)`` -- flagged ONLY when
  the line carries a traversal / user-input marker (``..`` , ``filename`` ,
  ``path`` , ``request`` , ...) AND is not a pure hardcoded-literal path.

Determinism / purity contract: no network, clock, randomness, subprocess, or
MCP; sorted traversal; regexes compiled once at import.

False-positive control (the CWE-22 analog of ``_e2e_run/sink_quality.py``):

* ``is_excluded_path`` drops vendored / test / docs / examples / tooling files.
* A tainted sink whose path is a single hardcoded literal with no traversal
  marker (e.g. ``open("README.md")``) is NOT a finding.
* A line that sanitizes via ``secure_filename(`` is NOT a finding.
* Pure comment / docstring lines never match.
"""
from __future__ import annotations
import os
import re
from typing import Any, Dict, List
__all__ = ['detect_path_traversal', 'PATHTRAV_RULES', 'SKIP_DIRS', 'is_excluded_path']
PATHTRAV_RULES: Dict[str, Dict[str, Any]] = {'pathtrav_extractall': {'pattern': '\\.extractall\\s*\\(', 'taint': False, 'severity': 'critical', 'cwe': 'CWE-22', 'owasp': 'A01:2021-Broken Access Control', 'description': 'Archive extractall can write outside the target dir (Zip/Tar Slip).'}, 'pathtrav_tarfile': {'pattern': '\\btarfile\\.open\\s*\\(', 'taint': False, 'severity': 'high', 'cwe': 'CWE-22', 'owasp': 'A01:2021-Broken Access Control', 'description': 'tarfile.open feeds extraction sinks vulnerable to path traversal.'}, 'pathtrav_zipfile': {'pattern': '\\bzipfile\\.ZipFile\\s*\\(', 'taint': False, 'severity': 'high', 'cwe': 'CWE-22', 'owasp': 'A01:2021-Broken Access Control', 'description': 'zipfile.ZipFile feeds extraction sinks vulnerable to path traversal.'}, 'pathtrav_send_file': {'pattern': '\\b(?:send_file|send_from_directory)\\s*\\(', 'taint': False, 'severity': 'high', 'cwe': 'CWE-22', 'owasp': 'A01:2021-Broken Access Control', 'description': 'Flask file-serving sink can leak files via a traversal path.'}, 'pathtrav_open': {'pattern': '\\bopen\\s*\\(', 'taint': True, 'severity': 'medium', 'cwe': 'CWE-22', 'owasp': 'A01:2021-Broken Access Control', 'description': 'open() on a user-influenced path (possible path traversal).'}, 'pathtrav_join': {'pattern': '\\bos\\.path\\.join\\s*\\(', 'taint': True, 'severity': 'medium', 'cwe': 'CWE-22', 'owasp': 'A01:2021-Broken Access Control', 'description': 'os.path.join with a user-influenced component (possible traversal).'}}
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox', '.eggs', '.mypy_cache', 'dist', 'build', '.pytest_cache', '.idea', '.hg', '.svn', 'site-packages', '.cache'}
_MAX_CONTEXT = 150
_HIGH_RISK_COUNT = 5
_EXCLUDE_PATH = re.compile('(?:^|/)(?:_vendor/|vendor/|third[_-]?party/|node_modules/|tests?/|testing/|fixtures?/|examples?/|samples?/|demo/|benchmark|docs?/|scripts?/|_scripts/|ci/|\\.github/|tools?/|setup\\.py)', re.IGNORECASE)
_PURE_STR_ARG = re.compile('\\(\\s*[rbfu]*([\'"]).*?\\1\\s*(?:,|\\))')
_STR_LITERAL = re.compile('([rbuRBU]*)([\'"]).*?\\2')
_FSTRING = re.compile('\\b[rbuRBU]*[fF][rbuRBU]*[\'"]')
_DYN_STRUCT = re.compile('\\.\\.|%|\\.format\\b|\\+')
_TAINT_WORDS = re.compile('\\b\\w*(?:user|request|filename|fname|filepath|file_?path|file_?name|upload|param|input|member|arcname|entry|path|url|uri)\\w*\\b', re.IGNORECASE)
_SANITIZED = re.compile('\\bsecure_filename\\s*\\(')
_COMPILED: List[tuple] = [(rid, re.compile(meta['pattern']), bool(meta['taint'])) for rid, meta in PATHTRAV_RULES.items()]

def is_excluded_path(relpath: str) -> bool:
    """True if ``relpath`` is vendored/test/docs/tooling -- not a shipped sink."""
    return bool(_EXCLUDE_PATH.search(relpath.replace('\\', '/')))

def _blank_literals(s: str) -> str:
    """Blank string-literal bodies so a marker inside a hardcoded path string
    does not make the argument look tainted."""
    return _STR_LITERAL.sub(lambda m: m.group(1) + m.group(2) * 2, s)

def _arg_is_tainted(code: str, match_end: int) -> bool:
    """True if the tainted-sink argument is plausibly user-influenced: an
    f-string, a structural marker (``..``/``+``/``%``/``.format``), or a
    user-input name -- evaluated on the arguments with literal bodies blanked.
    A pure hardcoded-literal path (e.g. ``open("README.md")``) is NOT tainted."""
    tail = code[match_end - 1:]
    blanked = _blank_literals(tail)
    return bool(_FSTRING.search(tail) or _DYN_STRUCT.search(blanked) or _TAINT_WORDS.search(blanked))

def _risk_level(count: int) -> str:
    if count == 0:
        return 'none'
    if count >= _HIGH_RISK_COUNT:
        return 'high'
    if count >= 2:
        return 'medium'
    return 'low'

def detect_path_traversal(repo_path: str) -> Dict[str, Any]:
    """Scan ``repo_path`` for CWE-22 path-traversal sinks.

    Returns a deterministic, fixed-shape dict. A non-directory ``repo_path``
    yields the same shape with an ``error`` key and no findings.
    """
    if not os.path.isdir(repo_path):
        return {'repo_path': repo_path, 'files_checked': 0, 'has_path_traversal': False, 'risk_level': 'none', 'total_findings': 0, 'findings': [], 'error': f'Not a directory: {repo_path}'}
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
                if _SANITIZED.search(raw):
                    continue
                for rid, regex, taint in _COMPILED:
                    m = regex.search(raw)
                    if not m:
                        continue
                    if taint and (not _arg_is_tainted(raw, m.end())):
                        continue
                    meta = PATHTRAV_RULES[rid]
                    findings.append({'id': rid, 'file': relpath, 'line': lineno, 'code': stripped[:_MAX_CONTEXT], 'severity': meta['severity'], 'cwe': meta['cwe'], 'owasp': meta['owasp'], 'description': meta['description']})
    findings.sort(key=lambda f: (f['file'], f['line'], f['id']))
    return {'repo_path': repo_path, 'files_checked': files_checked, 'has_path_traversal': len(findings) > 0, 'risk_level': _risk_level(len(findings)), 'total_findings': len(findings), 'findings': findings}