"""Deterministic, stdlib-only false-positive (FP) patterns knowledge base.

Findings are plain dicts; patterns are plain dicts persisted as JSON. The one
source of non-determinism in the legacy implementation (``datetime.now()``) is
replaced by an injected ``now`` string seam so ``added_at`` can be pinned by
callers and tests. No network, clock, or randomness is exercised here.

Pure standard library only -- no third-party imports, no sibling Epic-4
imports, and no live clock calls.
"""
from __future__ import annotations
import fnmatch
import json
from pathlib import Path
from typing import Optional, Union
__all__ = ['FP_PATTERN_FIELDS', 'load_fp_patterns', 'save_fp_patterns', 'is_known_fp', 'add_fp_pattern', 'format_fp_context']
FP_PATTERN_FIELDS = ('id', 'added_at', 'vuln_pattern_id', 'cwe', 'file_pattern', 'code_signature', 'context', 'reason', 'source', 'confidence')
DEFAULT_FP_FILE = Path(__file__).resolve().parent / 'fp_patterns.json'
DEFAULT_CONFIDENCE = 0.9
_CODE_SIGNATURE_LIMIT = 100
_DB_DESCRIPTION = 'Deterministic false-positive pattern knowledge base for NobleGreed v2.'
PathLike = Union[Path, str]

def _resolve_path(fp_file: Optional[PathLike]) -> Path:
    """Normalise an optional file argument into a concrete ``Path``."""
    if fp_file is None:
        return DEFAULT_FP_FILE
    return Path(fp_file)

def _finding_identifier(finding: dict) -> str:
    """Extract the rule identifier from a finding dict.

    Findings may carry the rule under any of several historical keys; the first
    non-empty one wins.
    """
    for field_name in ('id', 'rule_id', 'rule_short'):
        value = finding.get(field_name)
        if value:
            return value
    return ''

def load_fp_patterns(fp_file: Optional[PathLike]=None) -> list:
    """Load FP patterns from a JSON file.

    Returns an empty list when the file is absent or cannot be parsed.
    """
    path = _resolve_path(fp_file)
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding='utf-8'))
    except (ValueError, OSError):
        return []
    if isinstance(data, dict):
        patterns = data.get('patterns', [])
        return patterns if isinstance(patterns, list) else []
    if isinstance(data, list):
        return data
    return []

def save_fp_patterns(patterns: list, fp_file: Optional[PathLike]=None) -> None:
    """Persist ``patterns`` to JSON, bumping (or initialising) the version.

    The first write initialises ``version`` to 1; each subsequent write
    increments the stored version by one. Output is 2-space indented JSON.
    """
    path = _resolve_path(fp_file)
    version = 1
    if path.exists():
        try:
            existing = json.loads(path.read_text(encoding='utf-8'))
            if isinstance(existing, dict):
                version = int(existing.get('version', 0)) + 1
        except (ValueError, OSError, TypeError):
            version = 1
    payload = {'version': version, 'description': _DB_DESCRIPTION, 'patterns': patterns}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2), encoding='utf-8')

def _next_pattern_id(patterns: list) -> str:
    """Compute the next padded ``fp_NNN`` identifier."""
    highest = 0
    for pattern in patterns:
        ident = str(pattern.get('id', ''))
        if ident.startswith('fp_'):
            suffix = ident[3:]
            if suffix.isdigit():
                highest = max(highest, int(suffix))
    return 'fp_%03d' % (highest + 1)

def add_fp_pattern(finding: dict, reason: str, source: str='auto', context: str='', fp_file: Optional[PathLike]=None, now: Optional[str]=None) -> dict:
    """Append a new FP pattern derived from ``finding`` and persist it.

    The ``now`` parameter is the injected timestamp seam used for ``added_at``;
    no live clock is ever consulted.
    """
    patterns = load_fp_patterns(fp_file)
    code = str(finding.get('code', '')).strip()[:_CODE_SIGNATURE_LIMIT]
    entry = {'id': _next_pattern_id(patterns), 'added_at': now if now is not None else '', 'vuln_pattern_id': _finding_identifier(finding), 'cwe': finding.get('cwe', ''), 'file_pattern': finding.get('file_pattern', ''), 'code_signature': code, 'context': context or reason, 'reason': reason, 'source': source, 'confidence': DEFAULT_CONFIDENCE}
    patterns.append(entry)
    save_fp_patterns(patterns, fp_file)
    return entry

def _secondary_match(finding: dict, pattern: dict) -> bool:
    """Return True when a finding satisfies at least one secondary criterion."""
    file_pattern = pattern.get('file_pattern', '')
    if file_pattern and fnmatch.fnmatch(finding.get('file', ''), file_pattern):
        return True
    code_signature = pattern.get('code_signature', '')
    if code_signature and code_signature in finding.get('code', ''):
        return True
    cwe = pattern.get('cwe', '')
    if cwe and cwe == finding.get('cwe', ''):
        return True
    return False

def is_known_fp(finding: dict, patterns: Optional[list]=None):
    """Match a finding against known FP patterns.

    A match requires the rule identifier to equal a pattern's
    ``vuln_pattern_id`` AND at least one secondary criterion (file glob, code
    signature substring, or CWE equality). Returns ``(True, reason)`` on a
    match, otherwise ``(False, None)``.
    """
    if patterns is None:
        patterns = []
    ident = _finding_identifier(finding)
    if not ident:
        return (False, None)
    for pattern in patterns:
        if pattern.get('vuln_pattern_id', '') != ident:
            continue
        if _secondary_match(finding, pattern):
            label = '[%s] %s: %s' % (pattern.get('id', ''), pattern.get('reason', ''), pattern.get('context', ''))
            return (True, label)
    return (False, None)

def _escape_cell(value: str) -> str:
    """Make a value safe for a markdown table cell."""
    return str(value).replace('|', '\\|').replace('\n', ' ')

def format_fp_context(patterns: Optional[list]=None, target_cwes: Optional[list]=None) -> str:
    """Render known FP patterns as a markdown table, optionally CWE-filtered.

    Returns a placeholder message instead of a table when no patterns remain.
    """
    if patterns is None:
        patterns = []
    if target_cwes:
        selected = [p for p in patterns if p.get('cwe', '') in target_cwes]
    else:
        selected = list(patterns)
    header = '## Known False Positive Patterns'
    if not selected:
        return header + '\n\nNo known FP patterns for this target.\n'
    lines = [header, '', '| Pattern ID | CWE | Reason | Context |', '| --- | --- | --- | --- |']
    for pattern in selected:
        lines.append('| %s | %s | %s | %s |' % (_escape_cell(pattern.get('id', '')), _escape_cell(pattern.get('cwe', '')), _escape_cell(pattern.get('reason', '')), _escape_cell(pattern.get('context', ''))))
    return '\n'.join(lines) + '\n'