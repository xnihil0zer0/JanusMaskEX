---
dependencies:
  - "ngv2_submission_package_builder"
interfaces: "exposes `build_huntr_submission(submission_id, finding, poc, live_report, bounty=None) -> str` rendering the {ID}_submission.md huntr document with the TEN huntr form fields (in canonical order) plus a reference to the companion {ID}_poc.js file; plus `render_huntr_fields(context) -> str`, `poc_js_filename(submission_id) -> str`, and the `HUNTR_FIELDS` tuple."
working_dir: "/home/xnihil0zer0/NobleGreedv2"
verification_command: ".venv/bin/python -m pytest tests/ngv2/test_huntr_submission_wired.py tests/ngv2/test_submission_package_wired.py tests/test_submission_package.py -q"
---

# Title

P6.1 Huntr submission artifact format — render {ID}_submission.md with the 10 huntr form fields + {ID}_poc.js reference

# Scope

Build a new pure, stdlib+ngv2-only module `ngv2/huntr_submission.py` that renders the proven legacy huntr submission shape: a `{ID}_submission.md` Markdown document carrying the TEN canonical huntr form fields, in order, plus a reference to the companion `{ID}_poc.js` Node.js proof-of-concept file. It MAPS the existing internal `ngv2.submission_package.build_submission_package` body content onto the huntr field layout (the Description field embeds that rendered body plus an inline "See companion file {ID}_poc.js" PoC reference). The ten fields, in canonical order: (1) Repository, (2) Package Manager, (3) Version Affected, (4) Vulnerability Type / CWE, (5) CVSS, (6) Title, (7) Description, (8) Impact, (9) Occurrences, (10) References. Deterministic; missing values degrade to a placeholder (`_Not provided_`) rather than raising. The implementation below is VALIDATED (oracle proven green against it) — ship it VERBATIM as the whole file `ngv2/huntr_submission.py`.

# Non-Goals

Do NOT edit `ngv2/submission_package.py` or its `build_submission_package` function (this is a new standalone module that CONSUMES it — touching it would regress the sentinel-isolation oracles). No network, subprocess, LLM, wall-clock, or randomness. Do NOT do permalink SHA-pinning here (that is P6.2 `ngv2/permalink_pin.py`). Do NOT do eligibility/dedup here (that is P6.3). Do not perform any submission.

# Inputs

Consumes `ngv2.submission_package.build_submission_package(finding, poc, live_report) -> str`. Inputs to the new function: `submission_id` (e.g. "DVC-1"); a `finding` dict (keys: title, cwe, category, vuln_type, version_affected, cvss {vector, score}, description, impact, occurrences/permalinks (list), references (list)); a `poc` dict; a `live_report` dict; an optional `bounty` dict (keys: repo_url, package_manager, version_affected). The committed RED oracle is `tests/ngv2/test_huntr_submission_wired.py`.

# Deliverables

New file `ngv2/huntr_submission.py` — ship this VALIDATED implementation verbatim:

```python
"""Huntr submission artifact renderer (P6.1).

Renders the proven legacy huntr submission shape: a ``{ID}_submission.md``
document carrying the TEN huntr form fields plus a reference to the
companion ``{ID}_poc.js`` Node.js proof-of-concept file.

The ten canonical huntr form fields (in order):

    1. Repository (Repo URL)
    2. Package Manager
    3. Version Affected
    4. Vulnerability Type / CWE
    5. CVSS (vector + score)
    6. Title
    7. Description (with inline PoC)
    8. Impact
    9. Occurrences (SHA-pinned permalinks)
   10. References

This module maps the existing internal ``build_submission_package`` body
content onto the huntr field layout; it performs no network I/O and is
deterministic. Standard library + ngv2 only.
"""
from __future__ import annotations
from typing import Any, Mapping, Optional, Sequence

from ngv2.submission_package import build_submission_package

PLACEHOLDER = '_Not provided_'

# (heading, context-key) in canonical huntr order.
HUNTR_FIELDS = (
    ('Repository', 'repo_url'),
    ('Package Manager', 'package_manager'),
    ('Version Affected', 'version_affected'),
    ('Vulnerability Type / CWE', 'vuln_type_cwe'),
    ('CVSS', 'cvss'),
    ('Title', 'title'),
    ('Description', 'description'),
    ('Impact', 'impact'),
    ('Occurrences', 'occurrences'),
    ('References', 'references'),
)

__all__ = ['HUNTR_FIELDS', 'PLACEHOLDER', 'build_huntr_submission',
           'render_huntr_fields', 'poc_js_filename']


def poc_js_filename(submission_id: str) -> str:
    """Return the companion Node.js PoC filename for ``submission_id``."""
    return f'{submission_id}_poc.js'


def _text(value: Any) -> str:
    if value is None:
        return PLACEHOLDER
    text = str(value).strip()
    return text if text else PLACEHOLDER


def _render_cvss(cvss: Any) -> str:
    if cvss is None or cvss == '':
        return PLACEHOLDER
    if isinstance(cvss, Mapping):
        vector = cvss.get('vector')
        score = cvss.get('score')
        lines = []
        if vector:
            lines.append(f'- Vector: {vector}')
        if score is not None and score != '':
            lines.append(f'- **Score: {score}**')
        return '\n'.join(lines) if lines else PLACEHOLDER
    return _text(cvss)


def _render_occurrences(occurrences: Any) -> str:
    if occurrences is None or occurrences == '':
        return PLACEHOLDER
    if isinstance(occurrences, (str, bytes)):
        items: Sequence[Any] = [occurrences]
    elif isinstance(occurrences, Sequence):
        items = [o for o in occurrences if o is not None and str(o).strip()]
    else:
        items = [occurrences]
    if not items:
        return PLACEHOLDER
    return '\n'.join(f'- {o}' for o in items)


def _render_references(references: Any) -> str:
    return _render_occurrences(references)


def _render_description(finding: Mapping[str, Any], poc: Mapping[str, Any],
                        live_report: Mapping[str, Any], submission_id: str) -> str:
    """Description body with an inline reference to the {ID}_poc.js file."""
    body = build_submission_package(finding, poc, live_report)
    js = poc_js_filename(submission_id)
    inline = (f'\n\n### Proof of Concept\n\n'
              f'See companion file `{js}` (Node.js) for the runnable PoC.')
    return body + inline


def render_huntr_fields(context: Mapping[str, Any]) -> str:
    """Render the ten huntr fields as numbered Markdown sections."""
    lines = ['## Huntr Form Fields', '']
    for idx, (heading, key) in enumerate(HUNTR_FIELDS, start=1):
        lines.append(f'### {idx}. {heading}')
        value = context.get(key)
        lines.append(value if value not in (None, '') else PLACEHOLDER)
        lines.append('')
    return '\n'.join(lines).rstrip('\n') + '\n'


def build_huntr_submission(submission_id: str, finding: dict, poc: dict,
                           live_report: dict, bounty: Optional[dict] = None) -> str:
    """Render the full ``{ID}_submission.md`` huntr document.

    Maps the finding/poc/live_report/bounty inputs onto the ten huntr form
    fields and embeds a reference to the companion ``{ID}_poc.js`` file in
    the Description section. Deterministic; missing values degrade to the
    placeholder rather than raising.
    """
    finding = finding or {}
    poc = poc or {}
    live_report = live_report or {}
    bounty = bounty or {}

    cwe = finding.get('cwe') or finding.get('category')
    vuln_type = finding.get('vuln_type') or finding.get('category')
    vuln_type_cwe = ' / '.join(
        str(p) for p in (vuln_type, cwe) if p) or None

    context = {
        'repo_url': bounty.get('repo_url') or finding.get('repo_url'),
        'package_manager': bounty.get('package_manager') or finding.get('package_manager'),
        'version_affected': finding.get('version_affected') or bounty.get('version_affected'),
        'vuln_type_cwe': vuln_type_cwe,
        'cvss': _render_cvss(finding.get('cvss')),
        'title': _text(finding.get('title')),
        'description': _render_description(finding, poc, live_report, submission_id),
        'impact': _text(finding.get('impact')),
        'occurrences': _render_occurrences(finding.get('occurrences')
                                           or finding.get('permalinks')),
        'references': _render_references(finding.get('references')),
    }
    header = f'# {submission_id}: {context["title"]}\n\n'
    return header + render_huntr_fields(context)
```

Plus the already-committed RED oracle `tests/ngv2/test_huntr_submission_wired.py` (do not modify it).
