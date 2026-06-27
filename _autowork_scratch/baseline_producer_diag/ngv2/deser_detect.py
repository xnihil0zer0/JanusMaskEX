"""ngv2.deser_detect -- deterministic CWE-502 (unsafe deserialization) scanner.

A PURE filesystem recon tool: it walks a caller-supplied repository root,
scans ``*.py`` files for known unsafe-deserialization patterns
(pickle / marshal / shelve / torch.load / yaml unsafe loaders / joblib / dill /
...), and returns a fixed-shape dict.

The module is fully deterministic and stdlib-only:

* No network, no clock, no randomness, no uuid, no subprocess, no MCP.
* Filesystem access stays within the caller-provided root (a pure seam over
  the inputted path -- no implicit global scanning).
* Directory traversal order is sorted so identical inputs always yield
  identical outputs (the pure_fuzz determinism gate contract).

All compiled regexes are built once at import time.
"""
from __future__ import annotations
import os
import re
from typing import Any
from typing import Dict
from typing import List
from typing import Tuple
__all__ = ['check_deserialization', 'DESER_PATTERNS', 'SKIP_DIRS']
DESER_PATTERNS: List[Tuple[str, str]] = [('pickle_import', '^\\s*(?:import\\s+(?:pickle|cPickle|_pickle)\\b|from\\s+(?:pickle|cPickle|_pickle)\\s+import\\b)'), ('marshal_import', '^\\s*(?:import\\s+marshal\\b|from\\s+marshal\\s+import\\b)'), ('yaml_import', '^\\s*(?:import\\s+yaml\\b|from\\s+yaml\\s+import\\b)'), ('joblib_import', '^\\s*(?:import\\s+joblib\\b|from\\s+joblib\\s+import\\b)'), ('shelve_import', '^\\s*(?:import\\s+shelve\\b|from\\s+shelve\\s+import\\b)'), ('pickle', '\\bc?_?pickle\\.loads?\\b'), ('marshal', '\\bmarshal\\.loads?\\b'), ('yaml.load', '\\byaml\\.load\\b'), ('torch.load', '\\btorch\\.load\\b'), ('joblib.load', '\\bjoblib\\.load\\b'), ('shelve.open', '\\bshelve\\.open\\b')]
_COMPILED_PATTERNS: List[Tuple[str, 're.Pattern[str]']] = [(label, re.compile(source)) for label, source in DESER_PATTERNS]
SKIP_DIRS = {'.git', 'node_modules', '__pycache__', '.venv', 'venv', '.tox', '.eggs', '.mypy_cache', 'dist', 'build', '.pytest_cache', '.idea', '.hg', '.svn', 'site-packages', '.cache'}
_MAX_CONTEXT = 150

def _scan_text(text: str, relpath: str) -> List[Dict[str, Any]]:
    """Scan a single file's *text* for deserialization signatures.

    Returns a list of pattern records, one per (line, matching-pattern).
    Lines that are pure comments are ignored so that documentation or
    commented-out code never produces a false positive.
    """
    records: List[Dict[str, Any]] = []
    for lineno, raw_line in enumerate(text.splitlines(), start=1):
        stripped = raw_line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        for label, compiled in _COMPILED_PATTERNS:
            if compiled.search(raw_line):
                records.append({'module': label, 'file': relpath, 'line': lineno, 'context': stripped[:_MAX_CONTEXT]})
    return records

def _risk_level(total_matches: int, usage_matches: int) -> str:
    """Map match counts onto a coarse risk label.

    * no matches at all                 -> ``'none'``
    * only bare imports, no usage sites  -> ``'low'``
    * a handful of usage sites           -> ``'medium'``
    * many usage sites                   -> ``'high'``
    """
    if total_matches == 0:
        return 'none'
    if usage_matches == 0:
        return 'low'
    if usage_matches >= 5:
        return 'high'
    return 'medium'

def check_deserialization(repo_path: str) -> Dict:
    """Scan ``repo_path`` for unsafe-deserialization sinks.

    Returns a deterministic, fixed-shape dict describing every match found in
    the ``*.py`` files under ``repo_path`` (excluding pruned directories). If
    ``repo_path`` is not a directory the same shape is returned with an
    ``error`` key and no findings.
    """
    if not os.path.isdir(repo_path):
        return {'repo_path': repo_path, 'files_checked': 0, 'has_deserialization': False, 'risk_level': 'none', 'modules_found': [], 'total_matches': 0, 'patterns': [], 'error': f'Not a directory: {repo_path}'}
    files_checked = 0
    records: List[Dict] = []
    for dirpath, dirnames, filenames in os.walk(repo_path):
        dirnames[:] = sorted((d for d in dirnames if d not in SKIP_DIRS))
        for fname in sorted(filenames):
            if not fname.endswith('.py'):
                continue
            fullpath = os.path.join(dirpath, fname)
            try:
                with open(fullpath, 'r', encoding='utf-8', errors='replace') as handle:
                    lines = handle.read().splitlines()
            except OSError:
                continue
            files_checked += 1
            relpath = os.path.relpath(fullpath, repo_path)
            for lineno, raw in enumerate(lines, start=1):
                stripped = raw.strip()
                if not stripped or stripped.startswith('#'):
                    continue
                for label, regex in _COMPILED:
                    if regex.search(raw):
                        records.append({'module': label, 'file': relpath, 'line': lineno, 'context': stripped[:_MAX_CONTEXT]})
    total_matches = len(records)
    modules_found = sorted({rec['module'] for rec in records})
    usage_matches = sum((1 for rec in records if not rec['module'].endswith('_import')))
    if total_matches == 0:
        risk_level = 'none'
    elif usage_matches == 0:
        risk_level = 'low'
    elif usage_matches >= _HIGH_RISK_USAGE:
        risk_level = 'high'
    else:
        risk_level = 'medium'
    return {'repo_path': repo_path, 'files_checked': files_checked, 'has_deserialization': total_matches > 0, 'risk_level': risk_level, 'modules_found': modules_found, 'total_matches': total_matches, 'patterns': records}
_COMPILED: List[Tuple[str, 're.Pattern[str]']] = [(label, re.compile(pat)) for label, pat in DESER_PATTERNS]
_HIGH_RISK_USAGE = 5
'Deterministic CWE-502 (unsafe deserialization) recon scanner.\n\nThis is a pure filesystem tool: it walks a repository, scans ``*.py`` files for\nknown deserialization sink patterns (pickle / marshal / torch.load / unsafe\nyaml loaders / joblib / ...), and returns a fixed-shape result dict.\n\nThere is no network, clock, randomness, or external process involved -- the\nscan is fully deterministic and depends only on the on-disk source text. The\nmodule imports the standard library exclusively (``os`` and ``re``) and does\nnot depend on any sibling leaf.\n'