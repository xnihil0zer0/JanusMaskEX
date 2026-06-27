"""Render the legacy huntr submission document for a finding.

This module maps the body produced by
:func:`ngv2.submission_package.build_submission_package` onto the ten
canonical huntr web-form fields and emits a ``{ID}_submission.md`` Markdown
document that references a companion ``{ID}_poc.js`` Node.js proof-of-concept
file.

The renderer is pure and deterministic: it performs no network access, no
subprocess invocation, no LLM call, and consults neither the wall clock nor
any source of randomness.  Missing, ``None`` or empty values degrade to the
``PLACEHOLDER`` marker rather than raising.
"""
from __future__ import annotations
from collections.abc import Mapping
from typing import Any, Iterable, Optional, Tuple
from ngv2.submission_package import build_submission_package
__all__ = ['build_huntr_submission', 'render_huntr_fields', 'poc_js_filename', 'HUNTR_FIELDS', 'PLACEHOLDER']
PLACEHOLDER = '_Not provided_'
HUNTR_FIELDS: Tuple[Tuple[str, str], ...] = (('Repository', 'repository'), ('Package Manager', 'package_manager'), ('Version Affected', 'version_affected'), ('Vulnerability Type / CWE', 'vuln_type_cwe'), ('CVSS', 'cvss'), ('Title', 'title'), ('Description', 'description'), ('Impact', 'impact'), ('Occurrences', 'occurrences'), ('References', 'references'))

def poc_js_filename(submission_id: str) -> str:
    """Return the companion Node.js PoC filename for ``submission_id``."""
    return f'{submission_id}_poc.js'

def _text(value: Any) -> str:
    """Coerce ``value`` to a display string (decoding ``bytes`` as UTF-8)."""
    if isinstance(value, bytes):
        return value.decode('utf-8', 'replace')
    return str(value)

def _is_empty(value: Any) -> bool:
    """True for ``None`` or the empty string (the placeholder triggers)."""
    return value is None or value == ''

def _join_slash(parts: Iterable[Any]) -> Optional[str]:
    """Join non-empty parts with ' / '; return ``None`` when nothing remains."""
    items = [_text(part) for part in parts if not _is_empty(part)]
    return ' / '.join(items) if items else None

def _render_cvss(value: Any) -> str:
    """Render a CVSS value (mapping with vector/score, scalar, or empty)."""
    if isinstance(value, Mapping):
        lines = []
        vector = value.get('vector')
        score = value.get('score')
        if not _is_empty(vector):
            lines.append(f'- Vector: {_text(vector)}')
        if not _is_empty(score):
            lines.append(f'- **Score: {_text(score)}**')
        return '\n'.join(lines) if lines else PLACEHOLDER
    if _is_empty(value):
        return PLACEHOLDER
    return _text(value)

def _render_bullets(value: Any) -> str:
    """Render a list (bulleted, dropping blanks), a single string, or scalar."""
    if _is_empty(value):
        return PLACEHOLDER
    if isinstance(value, (str, bytes)):
        text = _text(value)
        return f'- {text}' if text.strip() else PLACEHOLDER
    if isinstance(value, (list, tuple, set, frozenset)):
        items = []
        for entry in value:
            if entry is None:
                continue
            text = _text(entry)
            if text.strip():
                items.append(f'- {text}')
        return '\n'.join(items) if items else PLACEHOLDER
    text = _text(value)
    return text if text.strip() else PLACEHOLDER

def _render_occurrences(finding: Mapping) -> str:
    """Render occurrences, falling back from 'occurrences' to 'permalinks'."""
    value = finding.get('occurrences')
    if _is_empty(value):
        value = finding.get('permalinks')
    return _render_bullets(value)

def _render_references(finding: Mapping) -> str:
    """Render the references field as bullets."""
    return _render_bullets(finding.get('references'))

def _render_description(submission_id: str, finding: Mapping, poc: Mapping, live_report: Mapping) -> str:
    """Embed the submission-package body plus a PoC file reference."""
    body = build_submission_package(finding, poc, live_report)
    reference = f'\n\n### Proof of Concept\n\nSee companion file `{poc_js_filename(submission_id)}` (Node.js) for the runnable PoC.'
    return f'{body}{reference}'

def render_huntr_fields(context: Optional[Mapping]) -> str:
    """Render the ten huntr fields as numbered Markdown sections.

    Each field becomes a ``### {idx}. {heading}`` block.  Values that are
    ``None`` or empty strings are replaced with :data:`PLACEHOLDER`.  The
    output terminates with exactly one trailing newline.
    """
    context = context or {}
    blocks = []
    for idx, (heading, lookup) in enumerate(HUNTR_FIELDS, start=1):
        value = context.get(lookup)
        if _is_empty(value):
            value = PLACEHOLDER
        blocks.append(f'### {idx}. {heading}\n\n{value}')
    return '\n\n'.join(blocks) + '\n'

def build_huntr_submission(submission_id: str, finding: Optional[Mapping], poc: Optional[Mapping], live_report: Optional[Mapping], bounty: Optional[Mapping]=None) -> str:
    """Build the ``{ID}_submission.md`` huntr document.

    Maps ``finding`` / ``poc`` / ``live_report`` / ``bounty`` onto the ten
    canonical huntr form fields and returns a ``# {submission_id}: {title}``
    header followed by the rendered field sections.
    """
    finding = finding or {}
    poc = poc or {}
    live_report = live_report or {}
    bounty = bounty or {}
    title = finding.get('title')
    vuln_type = finding.get('vuln_type') or finding.get('category')
    cwe = finding.get('cwe') or finding.get('category')
    repository = bounty.get('repo_url') or finding.get('repo_url')
    package_manager = bounty.get('package_manager') or finding.get('package_manager')
    version_affected = bounty.get('version_affected') or finding.get('version_affected')
    context = {'repository': repository, 'package_manager': package_manager, 'version_affected': version_affected, 'vuln_type_cwe': _join_slash((vuln_type, cwe)), 'cvss': _render_cvss(finding.get('cvss')), 'title': title, 'description': _render_description(submission_id, finding, poc, live_report), 'impact': finding.get('impact'), 'occurrences': _render_occurrences(finding), 'references': _render_references(finding)}
    header_title = title if not _is_empty(title) else PLACEHOLDER
    return f'# {submission_id}: {header_title}\n\n' + render_huntr_fields(context)