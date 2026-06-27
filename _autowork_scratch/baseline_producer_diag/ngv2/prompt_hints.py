"""Deterministic, stdlib-only manager for the append-only "Operational Hints"
section embedded in prompt Markdown files.

The module is pure with respect to clocks, networks, and randomness: the only
side effects are reads/writes of the caller-supplied file/directory paths, and
those are routed through injected ``read``/``write``/``listdir`` callable seams
with deterministic defaults. Identical inputs always yield identical outputs.

Public API (frozen by tests/test_prompt_hints.py):
    get_hints_section, add_hint, list_hints, prune_hint, init_hints,
    review_all_hints, HINTS_HEADER, HINTS_MARKER, MAX_HINTS, MIN_HINT_LEN
"""
import os
from typing import Callable, Dict, List, Optional, Tuple
__all__ = ['get_hints_section', 'add_hint', 'list_hints', 'prune_hint', 'init_hints', 'review_all_hints', 'HINTS_HEADER', 'HINTS_MARKER', 'MAX_HINTS', 'MIN_HINT_LEN']
MAX_HINTS = 20
MIN_HINT_LEN = 10
HINTS_MARKER = '## Operational Hints'
HINTS_HEADER = '\n\n' + HINTS_MARKER + '\n'

def _default_read(path: str) -> Optional[str]:
    """Return the text of ``path`` or ``None`` when it does not exist."""
    if not os.path.isfile(path):
        return None
    with open(path, 'r') as handle:
        return handle.read()

def _default_write(path: str, text: str) -> None:
    """Write ``text`` to ``path``, replacing any existing content."""
    with open(path, 'w') as handle:
        handle.write(text)

def _default_listdir(dirpath: str) -> List[str]:
    """Return the entries of ``dirpath`` (unordered)."""
    return os.listdir(dirpath)

def _parse_hints(after_marker: str) -> List[str]:
    """Extract the hint texts from the section body following the marker."""
    hints: List[str] = []
    for line in after_marker.splitlines():
        stripped = line.strip()
        if stripped.startswith('- '):
            hints.append(stripped[2:].strip())
    return hints

def _render(base: str, hints: List[str]) -> str:
    """Rebuild the file text from the pre-section body and the hint list.

    ``base`` is normalised by trimming trailing newlines so that repeated
    edits remain byte-stable (idempotent) rather than accreting blank lines.
    """
    lines = ''.join(('- %s\n' % hint for hint in hints))
    return base.rstrip('\n') + HINTS_HEADER + lines

def get_hints_section(path: str, *, read: Callable[[str], Optional[str]]=_default_read) -> Tuple[str, List[str]]:
    """Return ``(before, hints)`` for the prompt file at ``path``.

    ``before`` is the text preceding the hints section (the full file text when
    no section exists, or ``""`` when the file is missing). ``hints`` is the
    ordered list of hint texts, empty when there is no section.
    """
    text = read(path)
    if text is None:
        return ('', [])
    if HINTS_MARKER not in text:
        return (text, [])
    before, after = text.split(HINTS_MARKER, 1)
    return (before, _parse_hints(after))

def list_hints(path: str, *, read: Callable[[str], Optional[str]]=_default_read) -> List[str]:
    """Return the ordered hint texts for ``path`` (empty when none)."""
    return get_hints_section(path, read=read)[1]

def init_hints(path: str, *, read: Callable[[str], Optional[str]]=_default_read, write: Callable[[str, str], None]=_default_write) -> bool:
    """Append an empty hints section to ``path``.

    Returns ``True`` when a section was added, and ``False`` when the file is
    missing or already contains a section.
    """
    text = read(path)
    if text is None:
        return False
    if HINTS_MARKER in text:
        return False
    write(path, _render(text, []))
    return True

def add_hint(path: str, hint: str, source: str, *, read: Callable[[str], Optional[str]]=_default_read, write: Callable[[str, str], None]=_default_write) -> bool:
    """Append ``hint`` (attributed to ``source``) to the section in ``path``.

    The hint is rejected (returning ``False``) when it is shorter than
    ``MIN_HINT_LEN`` after stripping, when it is a case-insensitive substring
    match of an existing hint (in either direction), when the section is
    already at ``MAX_HINTS``, or when the file is missing. On success the
    section is created if necessary and ``True`` is returned.
    """
    cleaned = hint.strip()
    if len(cleaned) < MIN_HINT_LEN:
        return False
    text = read(path)
    if text is None:
        return False
    if HINTS_MARKER in text:
        base, after = text.split(HINTS_MARKER, 1)
        hints = _parse_hints(after)
    else:
        base, hints = (text, [])
    candidate = cleaned.lower()
    for existing in hints:
        existing_lower = existing.lower()
        if candidate in existing_lower or existing_lower in candidate:
            return False
    if len(hints) >= MAX_HINTS:
        return False
    hints.append(cleaned)
    write(path, _render(base, hints))
    return True

def prune_hint(path: str, number: int, *, read: Callable[[str], Optional[str]]=_default_read, write: Callable[[str, str], None]=_default_write) -> bool:
    """Remove the hint at one-based position ``number`` from ``path``.

    Returns ``False`` without mutating the file when ``number`` is out of range
    or the file/section is missing; otherwise removes the hint and returns
    ``True``.
    """
    text = read(path)
    if text is None or HINTS_MARKER not in text:
        return False
    base, after = text.split(HINTS_MARKER, 1)
    hints = _parse_hints(after)
    if number < 1 or number > len(hints):
        return False
    del hints[number - 1]
    write(path, _render(base, hints))
    return True

def review_all_hints(dirpath: str, *, listdir: Callable[[str], List[str]]=_default_listdir, read: Callable[[str], Optional[str]]=_default_read) -> Dict[str, List[str]]:
    """Scan ``dirpath`` for ``.md`` files and collect their hints.

    Files are visited in sorted order and those with no hints are skipped. The
    result maps each file name to its ordered list of hints.
    """
    result: Dict[str, List[str]] = {}
    for name in sorted(listdir(dirpath)):
        if not name.endswith('.md'):
            continue
        hints = list_hints(os.path.join(dirpath, name), read=read)
        if hints:
            result[name] = hints
    return result