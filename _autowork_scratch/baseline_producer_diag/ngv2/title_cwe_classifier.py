"""Deterministic title->CWE keyword classifier.

Maps a finding/submission title to a single CWE id string using a fixed,
case-insensitive keyword ruleset. Pure and stdlib-only: no file reads, no
network calls, no clock/randomness, and no global mutable state.

Precedence
----------
Rules are evaluated against ``title.lower()`` in the fixed order below. The
first rule whose keyword set matches the title determines the result, so
multi-keyword titles resolve deterministically and the output is stable
across runs:

    1. CWE-502  -- insecure deserialization
    2. CWE-918  -- server-side request forgery (SSRF)
    3. CWE-22   -- path / directory traversal
    4. CWE-78   -- OS / command injection

When no rule matches (including the empty string), ``''`` is returned.
"""
from typing import List, Tuple
_RULES: List[Tuple[str, Tuple[str, ...]]] = [('CWE-502', ('deserialization', 'deserialisation', 'deserialize', 'deserialise')), ('CWE-918', ('server-side request forgery', 'ssrf')), ('CWE-22', ('path traversal', 'directory traversal')), ('CWE-78', ('os command', 'command injection', 'command-injection'))]

def classify_title(title: str) -> str:
    """Classify a title to a single CWE id, or '' when no keyword matches.

    Matching is case-insensitive. The first matching rule in the documented
    precedence order wins, making the result deterministic for titles that
    contain multiple distinct keywords.
    """
    if not title:
        return ''
    haystack = title.lower()
    for cwe_id, keywords in _RULES:
        for keyword in keywords:
            if keyword in haystack:
                return cwe_id
    return ''