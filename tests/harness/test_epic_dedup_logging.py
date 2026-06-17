"""RED oracle for the epic_child_dropped journaling contract.

Pins the DESIRED post-fix behaviour of
``harness.planner.cli._finalize_epic_children``:

* When called with the keyword ``state_dir=<dir>``, every dropped child is
  journaled as an ``epic_child_dropped`` event under ``state_dir`` with the
  four-key schema ``{event, dropped_slug, reason, kept_slug}``.
* When called with the legacy 3-positional-arg shape (no ``state_dir``), the
  behaviour is unchanged and NO journal file is written.

The journaling behaviour is absent on HEAD, so the journaling tests are
correctly RED on HEAD and turn GREEN once the impl lands. The backward-compat
tests exercise the legacy call shape that already works.
"""
import json
import pytest
from harness.planner.cli import _finalize_epic_children

def _build_merged():
    """A merged child list: a canonical duplicate and a near-synonym superset.

    * ``fix-alpha-thing``      -> kept (first seen)
    * ``fix_alpha_thing``      -> canonical duplicate of ``fix-alpha-thing``
    * ``beta-handler``         -> kept (first seen)
    * ``beta-handler-extra``   -> near-synonym superset of ``beta-handler``
    """
    return [{'slug': 'fix-alpha-thing'}, {'slug': 'fix_alpha_thing'}, {'slug': 'beta-handler'}, {'slug': 'beta-handler-extra'}]

def _slugs(finalized):
    return [c['slug'] for c in finalized]

def _parse_rows(text):
    """Parse journal rows accepting either a JSON array or JSON-per-line."""
    text = text.strip()
    if not text:
        return []
    try:
        whole = json.loads(text)
    except (ValueError, TypeError):
        whole = None
    if isinstance(whole, list):
        return [r for r in whole if isinstance(r, dict)]
    if isinstance(whole, dict):
        return [whole]
    rows = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            obj = json.loads(line)
        except (ValueError, TypeError):
            continue
        if isinstance(obj, dict):
            rows.append(obj)
    return rows

def _collect_journal_rows(state_dir):
    """Discover the journal by globbing under ``state_dir`` and parse all rows.

    The exact relative journal filename is owned by the impl, so we never
    assert on it -- we walk the whole tree and gather every parseable row.
    """
    rows = []
    for path in sorted(state_dir.rglob('*')):
        if not path.is_file():
            continue
        try:
            text = path.read_text(encoding='utf-8')
        except (OSError, UnicodeDecodeError):
            continue
        rows.extend(_parse_rows(text))
    return rows
_REQUIRED_KEYS = {'event', 'dropped_slug', 'reason', 'kept_slug'}

def _matching_rows(rows, *, reason, dropped_slug, kept_slug):
    out = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if not _REQUIRED_KEYS.issubset(r.keys()):
            continue
        if r.get('event') == 'epic_child_dropped' and r.get('reason') == reason and (r.get('dropped_slug') == dropped_slug) and (r.get('kept_slug') == kept_slug):
            out.append(r)
    return out

def test_module_authored_drives_finalize_epic_children_only():
    """The oracle imports and drives the real helper (positive control)."""
    assert callable(_finalize_epic_children)
    finalized = _finalize_epic_children(_build_merged(), '', False)
    assert _slugs(finalized) == ['fix-alpha-thing', 'beta-handler']

def test_drop_journaling_writes_canonical_duplicate_and_near_synonym_rows(tmp_path):
    """state_dir= keyword call journals both dropped children with the schema."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    finalized = _finalize_epic_children(_build_merged(), '', False, state_dir=state_dir)
    assert _slugs(finalized) == ['fix-alpha-thing', 'beta-handler']
    rows = _collect_journal_rows(state_dir)
    assert rows, 'expected a journal file with epic_child_dropped rows under state_dir'
    for r in rows:
        assert isinstance(r, dict)
        assert _REQUIRED_KEYS.issubset(r.keys())
    canonical = _matching_rows(rows, reason='canonical_duplicate', dropped_slug='fix-alpha-thing', kept_slug='fix-alpha-thing')
    assert canonical, 'expected a canonical_duplicate row for fix-alpha-thing'
    near = _matching_rows(rows, reason='near_synonym', dropped_slug='beta-handler-extra', kept_slug='beta-handler')
    assert near, 'expected a near_synonym row dropping beta-handler-extra for beta-handler'

def test_finalized_list_unchanged_with_state_dir(tmp_path):
    """Journaling must not alter the finalized survivors or their order."""
    state_dir = tmp_path / 'state'
    state_dir.mkdir()
    finalized = _finalize_epic_children(_build_merged(), '', False, state_dir=state_dir)
    assert _slugs(finalized) == ['fix-alpha-thing', 'beta-handler']

def test_no_state_dir_backward_compat_writes_nothing(tmp_path):
    """Calling without state_dir creates zero files under a fresh tmp dir."""
    fresh = tmp_path / 'fresh'
    fresh.mkdir()
    finalized = _finalize_epic_children(_build_merged(), '', False)
    assert _slugs(finalized) == ['fix-alpha-thing', 'beta-handler']
    created = [p for p in fresh.rglob('*') if p.is_file()]
    assert created == [], f'no journal expected without state_dir, found {created!r}'

def test_legacy_three_positional_arg_call_returns_same_survivors():
    """The legacy 3-arg call shape still yields the same two survivors."""
    finalized = _finalize_epic_children(_build_merged(), '', False)
    assert _slugs(finalized) == ['fix-alpha-thing', 'beta-handler']

def test_no_journal_file_created_when_state_dir_absent(tmp_path):
    """No journal file appears anywhere when state_dir is omitted."""
    fresh = tmp_path / 'isolated'
    fresh.mkdir()
    _finalize_epic_children(_build_merged(), None, False)
    rows = _collect_journal_rows(fresh)
    assert rows == [], 'no epic_child_dropped journal should exist without state_dir'
    assert [p for p in fresh.rglob('*') if p.is_file()] == []