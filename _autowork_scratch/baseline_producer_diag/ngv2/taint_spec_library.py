"""Deterministic, stdlib-only loader/validator for NobleGreedv2's bundled
CodeQL taint-spec library.

The library is a directory that holds a ``manifest.json`` (a JSON list of
taint-spec entries) plus one ``.ql`` CodeQL query file per entry.  This module
NEVER runs CodeQL/semgrep; it only parses JSON and the leading ``/** ... */``
metadata docblock of each query file.  All behaviour is deterministic and
depends solely on the explicit ``library_dir`` argument -- no wall-clock,
network, or randomness is ever consulted.
"""
from __future__ import annotations
import json
import os
import re
from typing import Dict, List
__all__ = ['CONFIDENCE_LEVELS', 'PATH_PROBLEM_KIND', 'QL_METADATA_FIELDS', 'SPEC_ENTRY_FIELDS', 'load_taint_spec_manifest', 'parse_ql_metadata', 'validate_spec_entry']
SPEC_ENTRY_FIELDS = ('cwe', 'name', 'file', 'description', 'sinks', 'sources', 'language', 'confidence')
QL_METADATA_FIELDS = ('name', 'kind', 'id', 'problem.severity', 'tags')
PATH_PROBLEM_KIND = 'path-problem'
CONFIDENCE_LEVELS = ('low', 'medium', 'high')
_MANIFEST_FILENAME = 'manifest.json'
_DOCBLOCK_RE = re.compile('/\\*\\*(.*?)\\*/', re.DOTALL)
_CWE_RE = re.compile('^CWE-\\d+$')

def parse_ql_metadata(text: str) -> Dict[str, str]:
    """Parse the leading ``/** ... */`` docblock of a CodeQL query.

    Returns a mapping of ``@field`` names to their (whitespace-collapsed)
    values.  Continuation lines that do not start a new ``@field`` are appended
    to the most recent field's value.  If the text contains no docblock an empty
    dict is returned.
    """
    match = _DOCBLOCK_RE.search(text)
    if match is None:
        return {}
    metadata: Dict[str, str] = {}
    current = None
    for raw_line in match.group(1).splitlines():
        line = raw_line.strip()
        if line.startswith('*'):
            line = line[1:].strip()
        if not line:
            continue
        if line.startswith('@'):
            rest = line[1:]
            parts = rest.split(None, 1)
            field_name = parts[0]
            value = parts[1].strip() if len(parts) > 1 else ''
            metadata[field_name] = value
            current = field_name
        elif current is not None:
            joined = (metadata[current] + ' ' + line).strip()
            metadata[current] = joined
    return metadata

def _validate_entry_shape(entry: Dict) -> None:
    """Validate the structural shape of a single manifest entry."""
    if not isinstance(entry, dict):
        raise ValueError('spec entry must be a mapping')
    missing = [field_name for field_name in SPEC_ENTRY_FIELDS if field_name not in entry]
    if missing:
        raise ValueError('spec entry missing required fields: %s' % ', '.join(missing))
    extra = [field_name for field_name in entry if field_name not in SPEC_ENTRY_FIELDS]
    if extra:
        raise ValueError('spec entry has unexpected fields: %s' % ', '.join(extra))
    if not isinstance(entry['cwe'], str) or not _CWE_RE.match(entry['cwe']):
        raise ValueError('invalid CWE identifier: %r' % (entry['cwe'],))
    if entry['confidence'] not in CONFIDENCE_LEVELS:
        raise ValueError('invalid confidence level: %r' % (entry['confidence'],))
    for collection in ('sinks', 'sources'):
        value = entry[collection]
        if not isinstance(value, list) or not value:
            raise ValueError('%s must be a non-empty list' % collection)
    for field_name in ('name', 'file', 'description', 'language'):
        if not isinstance(entry[field_name], str) or not entry[field_name]:
            raise ValueError('%s must be a non-empty string' % field_name)

def validate_spec_entry(entry: Dict, library_dir: str) -> None:
    """Validate a single spec entry against its on-disk ``.ql`` query.

    Returns ``None`` when the entry is well-formed and its referenced query file
    exists with the required, consistent metadata.  Raises ``ValueError``
    otherwise.
    """
    _validate_entry_shape(entry)
    ql_path = os.path.join(library_dir, entry['file'])
    if not os.path.isfile(ql_path):
        raise ValueError('referenced query file not found: %s' % entry['file'])
    with open(ql_path, 'r', encoding='utf-8') as handle:
        text = handle.read()
    metadata = parse_ql_metadata(text)
    missing = [field_name for field_name in QL_METADATA_FIELDS if field_name not in metadata]
    if missing:
        raise ValueError('query %s missing metadata fields: %s' % (entry['file'], ', '.join(missing)))
    if metadata['kind'] != PATH_PROBLEM_KIND:
        raise ValueError('query %s has unexpected @kind %r (expected %r)' % (entry['file'], metadata['kind'], PATH_PROBLEM_KIND))
    return None

def load_taint_spec_manifest(library_dir: str) -> List[Dict]:
    """Load and validate the taint-spec ``manifest.json`` in ``library_dir``.

    Returns the list of entries in the exact order they appear in the manifest.
    Raises ``FileNotFoundError`` if the manifest is absent, and ``ValueError``
    if the manifest is malformed or any entry fails validation.
    """
    manifest_path = os.path.join(library_dir, _MANIFEST_FILENAME)
    with open(manifest_path, 'r', encoding='utf-8') as handle:
        try:
            entries = json.load(handle)
        except json.JSONDecodeError as exc:
            raise ValueError('manifest.json is not valid JSON: %s' % exc)
    if not isinstance(entries, list):
        raise ValueError('manifest.json must contain a JSON list of entries')
    for entry in entries:
        validate_spec_entry(entry, library_dir)
    return entries