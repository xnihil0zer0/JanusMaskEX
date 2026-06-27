from typing import Any, List, TYPE_CHECKING
if TYPE_CHECKING:
    from ngv2.contracts import Finding, PoC, LiveTestReport

def _get(form: Any, field: str) -> Any:
    if isinstance(form, dict):
        return form.get(field)
    try:
        return form[field]
    except (TypeError, KeyError, IndexError):
        pass
    return getattr(form, field, None)

def _text(value: Any) -> str:
    if value is None:
        return ''
    return str(value)

def _occurrences(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, (str, bytes)):
        return [_text(value)]
    try:
        return [_text(var_0) for var_0 in value]
    except TypeError:
        return [_text(value)]

def render_submission(form: dict) -> str:
    """Render a deterministic huntr submission markdown document from a form dict.

    Pure: performs no file or network I/O, reads no clock, and uses no
    randomness. Repeated calls with an equal ``form`` return byte-identical
    output. Field access is by explicit key (never by iterating ``form``), so
    output ordering is fixed and independent of dict iteration order.
    """
    def field(key: str) -> str:
        value = form.get(key, '')
        return '' if value is None else str(value)

    lines: list[str] = []
    lines.append('# huntr Submission')
    lines.append('')

    title = field('title')
    if title:
        lines.append('## ' + title)
        lines.append('')

    lines.append('## Repository')
    lines.append(field('repository'))
    lines.append('')

    lines.append('## Package')
    lines.append('- manager: ' + field('package_manager'))
    lines.append('- package: ' + field('affected_package'))
    lines.append('- version: ' + field('version'))
    lines.append('')

    lines.append('## Vulnerability Type')
    lines.append(field('vulnerability_type'))
    lines.append('')

    lines.append('## Severity')
    lines.append(field('severity'))
    lines.append('')

    lines.append('## CVSS Vector')
    lines.append(field('cvss_vector'))
    lines.append('')

    lines.append('## Description')
    lines.append(field('description'))
    lines.append('')

    lines.append('## Proof of Concept')
    lines.append(field('poc'))
    lines.append('')

    lines.append('## Impact')
    lines.append(field('impact'))
    lines.append('')

    lines.append('## Occurrences')
    occurrences = form.get('occurrences') or []
    for occurrence in occurrences:
        lines.append('- ' + str(occurrence))

    return '\n'.join(lines)

def _to_dict(obj: Any) -> Any:
    var_0 = getattr(obj, 'to_dict', None)
    if callable(var_0):
        return var_0()
    return obj

def assemble_package(finding: "Finding", poc: "PoC", live_test: "LiveTestReport") -> dict:
    """Assemble the final, JSON-serializable submission package.

    Pure and deterministic: it only projects the three inputs into a dict via
    their ``to_dict()`` accessors. The ``live_test`` report is treated strictly
    as data -- it is never called/invoked on any path (including error paths),
    so a callable passed in its place would remain uninvoked.
    """
    return {
        'finding_id': finding.id,
        'verdict': live_test.verdict,
        'finding': finding.to_dict(),
        'poc': poc.to_dict(),
        'live_test': live_test.to_dict(),
    }
