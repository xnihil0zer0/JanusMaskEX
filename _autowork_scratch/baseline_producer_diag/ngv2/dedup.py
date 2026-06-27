"""Deduplication over ngv2.contracts.Finding.

Pure, deterministic, stdlib-only guard that drops findings whose title
collides with an already-seen (e.g. previously submitted) title. A single
normalization primitive (:func:`normalize_title`) is shared by
:func:`is_duplicate` and :func:`filter_new` so duplicate detection stays
consistent across the module.
"""
from __future__ import annotations
import re
import unicodedata
from typing import Any, Iterable, List, Optional, Sequence
from ngv2.contracts import Finding
__all__ = ['normalize_title', 'is_duplicate', 'filter_new']
_WHITESPACE_RE = re.compile('\\s+', re.UNICODE)
_PUNCT_RE = re.compile('[^\\w\\s]', re.UNICODE)

def _title_text(value: Any) -> str:
    """Coerce a Finding/str/None into its raw title string."""
    if value is None:
        return ''
    if isinstance(value, Finding):
        title = getattr(value, 'title', None)
        return '' if title is None else str(title)
    return str(value)

def normalize_title(title: Any) -> str:
    """Return a canonical, deterministic normalized form of *title*.

    The result is unicode-normalized (NFKC), case-folded, has punctuation
    and formatting folded to spaces, internal whitespace collapsed, and
    leading/trailing whitespace stripped. Titles that differ only by these
    incidental variations map to the identical string. ``None`` and
    blank/punctuation-only titles normalize to the empty string.
    """
    text = _title_text(title)
    text = unicodedata.normalize('NFKC', text)
    text = text.casefold()
    text = _PUNCT_RE.sub(' ', text)
    text = _WHITESPACE_RE.sub(' ', text)
    return text.strip()

def is_duplicate(title: Any, existing_titles: Iterable[Any]) -> bool:
    """Report whether *title* duplicates any of *existing_titles*.

    Both sides are normalized before comparison. A match is reported when
    the normalized candidate equals an existing normalized title, or is a
    substring of it, or contains it (substring in either direction). An
    empty/blank candidate is never a duplicate.
    """
    candidate = normalize_title(title)
    if not candidate:
        return False
    for existing in existing_titles or ():
        norm = normalize_title(existing)
        if not norm:
            continue
        if candidate == norm or candidate in norm or norm in candidate:
            return True
    return False

def filter_new(findings: Sequence[Finding], existing_titles: Iterable[Any]) -> List[Finding]:
    """Return the subset of *findings* whose title is genuinely novel.

    A finding is dropped when it duplicates any of *existing_titles* or an
    earlier-kept finding in the same batch (intra-batch suppression: only
    the first occurrence of each newly-seen normalized title survives).
    Input order is preserved among the kept findings and the input
    sequences are not mutated.
    """
    seen: List[str] = [normalize_title(t) for t in existing_titles or ()]
    out: List[Finding] = []
    for finding in findings or ():
        if is_duplicate(finding, seen):
            continue
        out.append(finding)
        seen.append(normalize_title(finding))
    return out