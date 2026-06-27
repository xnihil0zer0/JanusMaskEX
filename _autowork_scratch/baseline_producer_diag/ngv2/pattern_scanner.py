"""Deterministic, stdlib-only regex vulnerability pattern scanner.

Pure standard library (``re``/``os``/``pathlib``). No network, no LLM, no
third-party packages and no imports of sibling Epic-4 leaves. The scanner
reads source files from disk and emits structured finding dicts by matching a
curated :data:`VULN_PATTERNS` catalog line-by-line, filtered by the file's
language (derived from :data:`LANG_EXTENSIONS`). :func:`scan_directory` walks a
repo, skips ignored/test directories, dedups, and returns an aggregate report.

All ordering is deterministic (sorted directory walks and sorted findings) so
repeated runs over identical inputs are byte-stable.
"""
from __future__ import annotations
import os
import re
from pathlib import Path
from typing import Dict
from typing import List
from typing import Union
__all__ = ['scan_file', 'scan_directory', 'VULN_PATTERNS', 'LANG_EXTENSIONS']
LANG_EXTENSIONS: Dict[str, str] = {'.py': 'python', '.js': 'javascript', '.jsx': 'javascript', '.ts': 'typescript', '.tsx': 'typescript', '.java': 'java', '.go': 'go', '.rb': 'ruby', '.php': 'php', '.c': 'c', '.h': 'c', '.cpp': 'cpp', '.cs': 'csharp'}
VULN_PATTERNS: Dict[str, Dict[str, object]] = {'sql_injection': {'pattern': '(?:execute(?:many)?|executescript)\\s*\\(.*(?:%|\\.format\\b|\\+)', 'severity': 'high', 'cwe': 'CWE-89', 'owasp': 'A03:2021-Injection', 'languages': ['python', 'javascript', 'typescript', 'java', 'php'], 'description': 'Possible SQL injection via string formatting in a query call.'}, 'command_injection': {'pattern': '(?:os\\.system|subprocess\\.(?:call|run|Popen|check_output)|popen)\\s*\\(', 'severity': 'critical', 'cwe': 'CWE-78', 'owasp': 'A03:2021-Injection', 'languages': ['python', 'ruby', 'php', 'javascript', 'typescript'], 'description': 'Possible OS command injection via a shell/process call.'}, 'eval_usage': {'pattern': '\\beval\\s*\\(', 'severity': 'high', 'cwe': 'CWE-95', 'owasp': 'A03:2021-Injection', 'languages': ['python', 'javascript', 'typescript', 'php', 'ruby'], 'description': 'Use of eval() can execute arbitrary code.'}, 'weak_crypto': {'pattern': '(?i)\\b(?:md5|sha1|des|rc4)\\b', 'severity': 'medium', 'cwe': 'CWE-327', 'owasp': 'A02:2021-Cryptographic Failures', 'languages': ['python', 'javascript', 'typescript', 'java', 'php'], 'description': 'Use of a weak or broken cryptographic algorithm.'}, 'hardcoded_secret': {'pattern': '(?i)\\b(?:password|passwd|secret|api[_-]?key|token)\\b\\s*[:=]\\s*[\'\\"][^\'\\"]+[\'\\"]', 'severity': 'high', 'cwe': 'CWE-798', 'owasp': 'A07:2021-Identification and Authentication Failures', 'languages': ['python', 'javascript', 'typescript', 'java', 'go', 'ruby', 'php', 'csharp'], 'description': 'Possible hardcoded credential assigned to a string literal.'}, 'insecure_deserialization': {'pattern': '\\b(?:pickle|cPickle|_pickle|marshal|joblib)\\.(?:loads|load)\\s*\\(|\\byaml\\.(?:unsafe_load|full_load|load)\\s*\\(|\\btorch\\.load\\s*\\(', 'severity': 'critical', 'cwe': 'CWE-502', 'owasp': 'A08:2021-Software and Data Integrity Failures', 'languages': ['python'], 'description': 'Insecure deserialization of untrusted data via pickle/marshal/yaml.load/torch.load/joblib'}, 'ssrf': {'pattern': '(?:requests\\.(?:get|post|put|patch|delete|head|request)|urllib\\.request\\.urlopen|urlopen|httpx\\.(?:get|post|put|patch|delete|request)|aiohttp\\.ClientSession)\\s*\\(', 'severity': 'high', 'cwe': 'CWE-918', 'owasp': 'A10:2021-Server-Side Request Forgery (SSRF)', 'languages': ['python'], 'description': 'Possible SSRF via an outbound HTTP request to a non-constant URL (requests/urllib/httpx/aiohttp).'}, 'path_traversal': {'pattern': '(?:open|io\\.open|codecs\\.open|os\\.open)\\s*\\([^)]*(?:os\\.path\\.join|\\.\\.[\\\\/]|request|filename|filepath|user_)|send_file\\s*\\(|send_from_directory\\s*\\(', 'severity': 'high', 'cwe': 'CWE-22', 'owasp': 'A01:2021-Broken Access Control', 'languages': ['python'], 'description': 'Possible path traversal via a file open/send with an attacker-influenced path.'}}
COMMENT_PREFIXES: Dict[str, tuple] = {'python': ('#',), 'ruby': ('#',), 'javascript': ('//',), 'typescript': ('//',), 'java': ('//',), 'go': ('//',), 'c': ('//',), 'cpp': ('//',), 'csharp': ('//',), 'php': ('//', '#')}
_IGNORED_DIRS = {'.git', '__pycache__', 'node_modules', '.venv', 'venv', '.tox'}
_TEST_DIR_NAMES = {'test', 'tests'}
_COMPILED: Dict[str, 're.Pattern'] = {ident: re.compile(meta['pattern']) for ident, meta in VULN_PATTERNS.items()}

def _is_comment_line(stripped: str, language: str) -> bool:
    """Return True if ``stripped`` is a full-line comment for ``language``."""
    for marker in COMMENT_PREFIXES.get(language, ()):
        if stripped.startswith(marker):
            return True
    return False

def scan_file(file_path: Union[str, 'os.PathLike'], language: str) -> List[Dict[str, object]]:
    """Scan a single file for vulnerability patterns applicable to ``language``.

    Returns a list of finding dicts (possibly empty). Missing, unreadable or
    non-decodable files yield ``[]`` and never raise. Findings are sorted
    deterministically by ``(line, id)``.
    """
    path = Path(file_path)
    try:
        text = path.read_text(encoding='utf-8')
    except (OSError, UnicodeError, ValueError):
        return []
    file_str = str(file_path)
    applicable = [ident for ident, meta in VULN_PATTERNS.items() if language in meta['languages']]
    findings: List[Dict[str, object]] = []
    for index, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or _is_comment_line(stripped, language):
            continue
        for ident in applicable:
            if _COMPILED[ident].search(raw_line):
                meta = VULN_PATTERNS[ident]
                findings.append({'id': ident, 'file': file_str, 'line': index, 'code': stripped, 'severity': meta['severity'], 'cwe': meta['cwe'], 'owasp': meta['owasp'], 'description': meta['description']})
    findings.sort(key=lambda f: (f['line'], f['id']))
    return findings

def scan_directory(root: Union[str, 'os.PathLike'], include_tests: bool=False) -> Dict[str, object]:
    """Recursively scan a directory tree and return an aggregate report.

    The report exposes ``files_scanned``, ``total_findings``,
    ``severity_counts`` and ``findings``. Finding ``file`` paths are relative to
    ``root``. A missing path yields a report containing an ``error`` key.
    Findings are deduplicated by ``(id, file, line)`` and sorted by
    ``(file, line, id)`` for byte-stable output.
    """
    root_path = Path(root)
    if not root_path.is_dir():
        return {'error': 'path not found or not a directory: {}'.format(str(root))}
    files_scanned = 0
    collected: List[Dict[str, object]] = []
    seen = set()
    for current_dir, dir_names, file_names in os.walk(str(root_path)):
        kept = []
        for name in sorted(dir_names):
            if name in _IGNORED_DIRS:
                continue
            if not include_tests and name.lower() in _TEST_DIR_NAMES:
                continue
            kept.append(name)
        dir_names[:] = kept
        for file_name in sorted(file_names):
            suffix = Path(file_name).suffix.lower()
            language = LANG_EXTENSIONS.get(suffix)
            if language is None:
                continue
            if not include_tests and _is_test_file(file_name):
                continue
            abs_path = Path(current_dir) / file_name
            files_scanned += 1
            rel_path = os.path.relpath(str(abs_path), str(root_path))
            for finding in scan_file(abs_path, language):
                finding['file'] = rel_path
                key = (finding['id'], finding['file'], finding['line'])
                if key in seen:
                    continue
                seen.add(key)
                collected.append(finding)
    collected.sort(key=lambda f: (f['file'], f['line'], f['id']))
    severity_counts: Dict[str, int] = {}
    for finding in collected:
        sev = finding['severity']
        severity_counts[sev] = severity_counts.get(sev, 0) + 1
    return {'files_scanned': files_scanned, 'total_findings': len(collected), 'severity_counts': severity_counts, 'findings': collected}

def _is_test_file(file_name: str) -> bool:
    """Return True for conventionally-named test files."""
    stem = Path(file_name).stem.lower()
    return stem.startswith('test_') or stem.endswith('_test') or stem == 'test'