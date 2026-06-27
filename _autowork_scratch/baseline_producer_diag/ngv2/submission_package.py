"""Submission report template loader and field renderer.

This module provides the template-loading and field-rendering substrate used
by the submission package builder. The canonical template lives in the legacy
orchestrator tree; when it is unavailable a built-in default keeps the package
complete and well-formed.

The default template and the section ordering below are kept in lock-step with
the nine required section headers expected by the builder:

    Title, CWE, Severity, Vulnerable Code References, Attack Scenario,
    PoC Reference, Live-Test Evidence, Impact, Suggested Fix

Standard library only -- no third-party imports.
"""
from __future__ import annotations
import re
from typing import Mapping
from typing import Optional
LEGACY_TEMPLATE_PATH = '/home/xnihil0zer0/AI-Data/NobleGreed-legacy/orchestrator/templates/submission_report_template.md'
NOT_PROVIDED_MARKER = '_Not provided_'
SECTION_LAYOUT = (('Title', 'title'), ('CWE', 'cwe'), ('Severity', 'severity'), ('Vulnerable Code References', 'vulnerable_code_references'), ('Attack Scenario', 'attack_scenario'), ('PoC Reference', 'poc_reference'), ('Live-Test Evidence', 'live_test_evidence'), ('Impact', 'impact'), ('Suggested Fix', 'suggested_fix'))

def _build_default_template() -> str:
    """Construct the built-in fallback template from the section layout."""
    lines = ['# Submission Report', '']
    for heading, field_name in SECTION_LAYOUT:
        lines.append('## ' + heading)
        lines.append('{{' + field_name + '}}')
        lines.append('')
    return '\n'.join(lines)
DEFAULT_TEMPLATE = _build_default_template()
_PLACEHOLDER_RE = re.compile('\\{\\{\\s*([A-Za-z0-9_]+)\\s*\\}\\}')

def load_submission_template(path: Optional[str]=None) -> str:
    """Return the submission report template's contents.

    Reads the Markdown template from ``path`` (defaulting to the legacy
    template path). If the resolved path does not exist or cannot be read,
    the built-in default template -- which still contains all nine required
    section headers in order -- is returned instead.
    """
    resolved = LEGACY_TEMPLATE_PATH if path is None else path
    try:
        with open(resolved, 'r', encoding='utf-8') as handle:
            return handle.read()
    except OSError:
        return DEFAULT_TEMPLATE
from typing import Any

def render_template(template: str, context: Mapping[str, Any]) -> str:
    """Fill placeholders in ``template`` from ``context``.

    Supports BOTH committed placeholder styles:

    * ``{{token}}`` (template-loader contract): each placeholder is replaced
      with ``str(context[token])``; missing keys, ``None`` and blank values
      render as :data:`NOT_PROVIDED_MARKER`; context keys not referenced by
      any placeholder are ignored (never appended to the output).
    * ``{token}`` (builder contract): rendered via :meth:`str.format_map`
      over a safe mapping; empty or ``None`` values collapse to
      :data:`PLACEHOLDER`.  Substituted values are inserted verbatim (they
      are not re-parsed for braces).
    """
    mapping = context or {}
    if _PLACEHOLDER_RE.search(template):

        def _substitute(match: 're.Match[str]') -> str:
            field_name = match.group(1)
            value = mapping.get(field_name)
            if value is None:
                return NOT_PROVIDED_MARKER
            text = value if isinstance(value, str) else str(value)
            if text.strip() == '':
                return NOT_PROVIDED_MARKER
            return text
        return _PLACEHOLDER_RE.sub(_substitute, template)
    safe = _SafeContext()
    for field_name, value in mapping.items():
        if value is None or value == '':
            safe[field_name] = PLACEHOLDER
        else:
            safe[field_name] = value
    return template.format_map(safe)
from typing import Sequence
from typing import Tuple
PLACEHOLDER = '_Not provided_'
SECTION_HEADERS: Tuple[str, ...] = ('Title', 'CWE', 'Severity', 'Vulnerable Code References', 'Attack Scenario', 'PoC Reference', 'Live-Test Evidence', 'Impact', 'Suggested Fix')
DEFAULT_SUBMISSION_TEMPLATE = '## Title\n\n{title}\n\n## CWE\n\n{cwe}\n\n## Severity\n\n{severity}\n\n## Vulnerable Code References\n\n{code_refs}\n\n## Attack Scenario\n\n{attack_scenario}\n\n## PoC Reference\n\n{poc_reference}\n\n## Live-Test Evidence\n\n{live_test_evidence}\n\n## Impact\n\n{impact}\n\n## Suggested Fix\n\n{suggested_fix}\n'
__all__ = ['PLACEHOLDER', 'SECTION_HEADERS', 'DEFAULT_SUBMISSION_TEMPLATE', 'load_submission_template', 'render_template', 'build_submission_package']

class _SafeContext(dict):
    """Mapping for :meth:`str.format_map` that never raises on a missing token."""

    def __missing__(self, name: str) -> str:
        return PLACEHOLDER

def _text(value: Any) -> str:
    """Coerce a scalar value to clean Markdown text or a placeholder."""
    if value is None:
        return PLACEHOLDER
    text = str(value).strip()
    return text if text else PLACEHOLDER

def _fenced(body: Any) -> str:
    """Wrap (possibly multiline) ``body`` in a Markdown code fence."""
    return '```\n' + str(body).rstrip('\n') + '\n```'

def _render_cwe(cwe: Any) -> str:
    if cwe is None or cwe == '':
        return PLACEHOLDER
    if isinstance(cwe, Mapping):
        ident = cwe.get('id') or cwe.get('cwe') or cwe.get('name')
        description = cwe.get('description') or cwe.get('title')
        if ident and description:
            return f'{ident}: {description}'
        return _text(ident or description or cwe)
    if isinstance(cwe, int):
        return f'CWE-{cwe}'
    return _text(cwe)

def _render_severity(severity: Any) -> str:
    """Render either a CVSS-style dict or a plain label string."""
    if severity is None or severity == '':
        return PLACEHOLDER
    if isinstance(severity, Mapping):
        lines = []
        for field_name, value in severity.items():
            lines.append(f'- **{field_name}**: {value}')
        return '\n'.join(lines) if lines else PLACEHOLDER
    return _text(severity)

def _render_one_ref(ref: Any) -> str:
    if isinstance(ref, Mapping):
        location = ref.get('file') or ref.get('path') or ref.get('location') or ''
        line_no = ref.get('line')
        if line_no is None:
            line_no = ref.get('lineno')
        snippet = ref.get('snippet') or ref.get('code')
        header = f'{location}:{line_no}' if line_no is not None else str(location)
        header = header.strip(':') or PLACEHOLDER
        if snippet:
            return f'- `{header}`\n\n{_fenced(snippet)}'
        return f'- `{header}`'
    return f'- `{ref}`'

def _render_code_refs(refs: Any) -> str:
    """Render vulnerable code references provided as a list or a single value."""
    if refs is None or refs == '':
        return PLACEHOLDER
    if isinstance(refs, (str, bytes)) or isinstance(refs, Mapping):
        items: Sequence[Any] = [refs]
    elif isinstance(refs, Sequence):
        items = [r for r in refs if r is not None and str(r).strip() != '']
    else:
        items = [refs]
    if not items:
        return PLACEHOLDER
    return '\n'.join((_render_one_ref(ref) for ref in items))

def _render_poc(poc: Mapping[str, Any]) -> str:
    if not poc:
        return PLACEHOLDER
    lines = []
    script = poc.get('script') or poc.get('script_path') or poc.get('path')
    command = poc.get('command') or poc.get('cmd')
    expected = poc.get('expected_output') or poc.get('output') or poc.get('expected')
    artifact = poc.get('artifact') or poc.get('artifact_reference') or poc.get('reference')
    if script:
        lines.append(f'- **Script**: `{script}`')
    if command:
        lines.append(f'- **Command**:\n\n{_fenced(command)}')
    if expected:
        lines.append(f'- **Expected output**:\n\n{_fenced(expected)}')
    if artifact:
        lines.append(f'- **Artifact**: {artifact}')
    return '\n'.join(lines) if lines else PLACEHOLDER

def _render_live_report(live_report: Mapping[str, Any]) -> str:
    if not live_report:
        return PLACEHOLDER
    lines = []
    status = live_report.get('status')
    observed = live_report.get('observed') or live_report.get('observed_result') or live_report.get('result')
    output = live_report.get('output') or live_report.get('captured_output') or live_report.get('captured')
    if status is not None and status != '':
        lines.append(f'- **Status**: {status}')
    if observed:
        lines.append(f'- **Observed result**: {observed}')
    if output:
        lines.append(f'- **Captured output**:\n\n{_fenced(output)}')
    return '\n'.join(lines) if lines else PLACEHOLDER

def build_submission_package(finding: dict, poc: dict, live_report: dict, template: Optional[str]=None) -> str:
    """Render a Markdown submission package from a finding, PoC and live report.

    The finding feeds the title/CWE/severity/code-reference/attack-scenario/
    impact/fix sections; the PoC dict feeds ONLY the PoC Reference section and
    the live report feeds ONLY the Live-Test Evidence section.  Missing values
    degrade to :data:`PLACEHOLDER` via :func:`render_template` rather than
    raising.  When no ``template`` is supplied the in-module
    :data:`DEFAULT_SUBMISSION_TEMPLATE` is used (the on-disk legacy template is
    never read here -- that would be unhermetic).
    """
    finding = finding or {}
    poc = poc or {}
    live_report = live_report or {}
    if template is None:
        template = DEFAULT_SUBMISSION_TEMPLATE
    severity = finding.get('severity')
    if isinstance(severity, dict):
        severity = ' '.join(str(part) for part in severity.values())
    code_refs = finding.get('code_refs')
    if isinstance(code_refs, (list, tuple)):
        code_refs = '\n'.join(str(ref) for ref in code_refs)
    poc_lines = []
    if poc.get('script'):
        poc_lines.append('Script: ' + str(poc.get('script')))
    if poc.get('command'):
        poc_lines.append('Command:\n```\n' + str(poc.get('command')) + '\n```')
    if poc.get('expected_output'):
        poc_lines.append('Expected output:\n```\n' + str(poc.get('expected_output')) + '\n```')
    poc_reference = '\n'.join(poc_lines) if poc_lines else None
    live_lines = []
    if live_report.get('status'):
        live_lines.append('Status: ' + str(live_report.get('status')))
    if live_report.get('observed'):
        live_lines.append('Observed: ' + str(live_report.get('observed')))
    if live_report.get('output'):
        live_lines.append('Output:\n```\n' + str(live_report.get('output')) + '\n```')
    live_test_evidence = '\n'.join(live_lines) if live_lines else None
    context = {
        'title': finding.get('title'),
        'cwe': finding.get('cwe'),
        'severity': severity,
        'code_refs': code_refs,
        'attack_scenario': finding.get('attack_scenario'),
        'poc_reference': poc_reference,
        'live_test_evidence': live_test_evidence,
        'impact': finding.get('impact'),
        'suggested_fix': finding.get('fix'),
    }
    return render_template(template, context)
'Assemble a platform-shaped Markdown submission package.\n\nThis module maps an already-produced ``finding``, ``poc`` and ``live_report``\nonto the canonical submission report template and renders the full Markdown\ndocument.  It performs no network I/O, no live testing and no PoC execution --\nit only consumes the dicts that earlier stages produced.\n\nAll rendering is deterministic: the same inputs always produce the same output.\nOnly the Python standard library is used.\n'