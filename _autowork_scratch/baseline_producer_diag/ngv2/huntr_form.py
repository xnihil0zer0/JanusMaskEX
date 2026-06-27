"""Build the 12 huntr submission form fields from a Finding + PoC + context.

Pure, deterministic, stdlib-only module. Imports the data shapes from
``ngv2.contracts`` and exposes the ordered form-field identifiers, the
CWE -> vulnerability-type mapping, and ``build_form``.
"""
from __future__ import annotations
import re
from typing import Any, Dict, Mapping
from ngv2.contracts import Finding, PoC
HUNTR_FORM_FIELDS = ('repository', 'package_manager', 'affected_package', 'version', 'vulnerability_type', 'severity', 'cvss_vector', 'title', 'description', 'poc', 'impact', 'occurrences')
CWE_VULN_TYPES: Dict[str, str] = {'20': 'Improper Input Validation', '22': 'Path Traversal', '78': 'OS Command Injection', '79': 'Cross-site Scripting (XSS)', '89': 'SQL Injection', '94': 'Code Injection', '200': 'Information Exposure', '287': 'Improper Authentication', '352': 'Cross-Site Request Forgery (CSRF)', '434': 'Unrestricted File Upload', '502': 'Deserialization of Untrusted Data', '601': 'Open Redirect', '611': 'XML External Entity (XXE)', '787': 'Out-of-bounds Write', '798': 'Use of Hard-coded Credentials', '862': 'Missing Authorization', '918': 'Server-Side Request Forgery (SSRF)'}
_CWE_DIGITS = re.compile('\\d+')

def _get(source: Any, key: str, default: Any=None) -> Any:
    """Read ``key`` from a mapping or object-like source, else ``default``."""
    if source is None:
        return default
    if isinstance(source, Mapping):
        return source.get(key, default)
    return getattr(source, key, default)

def _vulnerability_type(category: Any) -> Any:
    """Map a CWE-style category to a huntr vulnerability type.

    Parses the numeric digits out of ``category`` (e.g. '918' from 'CWE-918').
    If the number is known, return the mapped type; otherwise fall back to the
    raw category value.
    """
    match = _CWE_DIGITS.search(category or '')
    if match is not None:
        mapped = CWE_VULN_TYPES.get(match.group(0))
        if mapped is not None:
            return mapped
    return category

def build_form(finding: Finding, poc: PoC, context: Any) -> Dict[str, Any]:
    """Build the 12-field huntr submission form dictionary."""
    return {'repository': _get(finding, 'target'), 'package_manager': _get(context, 'package_manager'), 'affected_package': _get(context, 'affected_package'), 'version': _get(context, 'version'), 'vulnerability_type': _vulnerability_type(_get(finding, 'category')), 'severity': _get(finding, 'severity'), 'cvss_vector': _get(context, 'cvss_vector'), 'title': _get(finding, 'title'), 'description': _get(finding, 'description'), 'poc': _get(poc, 'code'), 'impact': _get(context, 'impact'), 'occurrences': _get(context, 'occurrences')}