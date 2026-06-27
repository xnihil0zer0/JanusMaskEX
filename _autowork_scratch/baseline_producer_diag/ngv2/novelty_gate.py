"""Pure novelty and duplication classifier for ngv2.

Ports the legacy ``novelty_checker.py`` logic into a single deterministic,
stdlib-only function that decides whether a finding is ``NOVEL``, a
``POSSIBLE_DUP``, or a ``CONFIRMED_DUP`` relative to a corpus of prior
submissions.

The module performs no I/O, database, network, LLM, wall-clock, randomness,
or subprocess access. It depends only on the Python standard library.
"""
from typing import Any, List
__all__ = ['classify_novelty', 'normalize_title']
NOVEL = 'NOVEL'
POSSIBLE_DUP = 'POSSIBLE_DUP'
CONFIRMED_DUP = 'CONFIRMED_DUP'

def normalize_title(value: Any) -> str:
    """Normalize a title for comparison.

    Lowercases, strips leading/trailing whitespace, and collapses every
    internal run of whitespace (spaces, tabs, newlines, ...) into a single
    space. Non-string and ``None`` inputs are treated as the empty string so
    the function never raises.
    """
    if not isinstance(value, str):
        return ''
    return ' '.join(value.split()).lower()

def _get_field(entry: Any, field_name: str) -> Any:
    """Safely fetch a field from a mapping-like entry.

    Returns ``None`` when the entry is not a dict or the field is absent,
    guaranteeing exception-safety for malformed inputs.
    """
    if isinstance(entry, dict):
        return entry.get(field_name)
    return None

def _same_locus(finding_cwe: Any, finding_file: Any, entry_cwe: Any, entry_file: Any) -> bool:
    """Return True when cwe and file match exactly (case-sensitive)."""
    return finding_cwe == entry_cwe and finding_file == entry_file

def classify_novelty(finding: dict, known_corpus: list) -> str:
    """Classify ``finding`` against ``known_corpus``.

    Returns one of ``'NOVEL'``, ``'POSSIBLE_DUP'``, or ``'CONFIRMED_DUP'``.

    Rules:
      * ``CONFIRMED_DUP`` iff some corpus entry has the same cwe AND same file
        AND an equal normalized title (strongest match wins).
      * Otherwise ``POSSIBLE_DUP`` iff some corpus entry has a similar title
        (normalized substring match in either direction) OR shares the same
        cwe AND file.
      * Otherwise ``NOVEL``. An empty corpus is always ``NOVEL``.
    """
    if not known_corpus:
        return NOVEL
    finding_title = normalize_title(_get_field(finding, 'title'))
    finding_cwe = _get_field(finding, 'cwe')
    finding_file = _get_field(finding, 'file')
    possible = False
    for entry in known_corpus:
        entry_title = normalize_title(_get_field(entry, 'title'))
        entry_cwe = _get_field(entry, 'cwe')
        entry_file = _get_field(entry, 'file')
        locus_match = _same_locus(finding_cwe, finding_file, entry_cwe, entry_file)
        if locus_match and finding_title == entry_title:
            return CONFIRMED_DUP
        if not possible:
            title_similar = bool(finding_title) and bool(entry_title) and (finding_title in entry_title or entry_title in finding_title)
            if title_similar or locus_match:
                possible = True
    return POSSIBLE_DUP if possible else NOVEL