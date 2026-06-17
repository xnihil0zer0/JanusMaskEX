"""RED oracle for load_brief parsing of the required_child_slugs frontmatter key.

This hermetic pytest module pins the DESIRED post-fix contract: load_brief must
coerce a ``required_child_slugs`` frontmatter key into a ``tuple[str, ...]`` field
on :class:`PlanningBrief`, mirroring the existing ``required_task_ids`` parse
semantics:

* list/tuple  -> tuple of stripped, non-empty strings
* comma-string -> split on ``','`` + strip + drop empties
* absent       -> ``()`` (never ``None``)

It is RED on HEAD because neither the ``PlanningBrief.required_child_slugs`` field
nor the ``load_brief`` parse block exist yet, and turns GREEN once the impl lands.

Every fixture brief lives under the pytest ``tmp_path`` fixture; no live ``state/``
directory is ever read or written.
"""
import dataclasses
import pytest
from harness.planner.brief_loader import PlanningBrief
from harness.planner.brief_loader import load_brief
WORKING_DIR = '/home/xnihil0zer0/JanusMaskJR'
SECTIONS = '# Title\nBrief title body.\n\n# Scope\nScope body text.\n\n# Inputs\nInputs body text.\n\n# Non-Goals\nNon-goals body text.\n\n# Deliverables\nDeliverables body text.\n'

def _write_brief(tmp_path, fm_lines):
    """Write a complete, valid brief markdown file under ``tmp_path``.

    ``fm_lines`` is a list of extra frontmatter YAML lines (e.g. the under-test
    ``required_child_slugs`` key). ``working_dir`` is always injected so that
    load_brief validation passes. Returns the path to the written brief.
    """
    frontmatter = '\n'.join([f'working_dir: {WORKING_DIR}', *fm_lines])
    content = '---\n' + frontmatter + '\n---\n\n' + SECTIONS
    brief_path = tmp_path / 'brief.md'
    brief_path.write_text(content, encoding='utf-8')
    return brief_path

def test_required_child_slugs_list_form_returns_tuple(tmp_path):
    path = _write_brief(tmp_path, ['required_child_slugs: [alpha, beta]'])
    brief = load_brief(path)
    assert brief.required_child_slugs == ('alpha', 'beta')

def test_required_child_slugs_comma_string_split(tmp_path):
    path = _write_brief(tmp_path, ['required_child_slugs: "gamma, delta"'])
    brief = load_brief(path)
    assert brief.required_child_slugs == ('gamma', 'delta')

def test_required_child_slugs_absent_returns_empty_tuple(tmp_path):
    path = _write_brief(tmp_path, [])
    brief = load_brief(path)
    assert brief.required_child_slugs == ()
    assert brief.required_child_slugs is not None

def test_required_child_slugs_whitespace_stripped(tmp_path):
    path = _write_brief(tmp_path, ['required_child_slugs: ["  alpha  ", " beta "]'])
    brief = load_brief(path)
    assert brief.required_child_slugs == ('alpha', 'beta')

def test_required_child_slugs_whitespace_stripped_comma_string(tmp_path):
    path = _write_brief(tmp_path, ['required_child_slugs: "  gamma ,  delta  "'])
    brief = load_brief(path)
    assert brief.required_child_slugs == ('gamma', 'delta')

def test_required_child_slugs_empty_strings_filtered(tmp_path):
    path = _write_brief(tmp_path, ['required_child_slugs: ["alpha", "", "  ", "beta"]'])
    brief = load_brief(path)
    assert brief.required_child_slugs == ('alpha', 'beta')

def test_required_child_slugs_empty_strings_filtered_comma_string(tmp_path):
    path = _write_brief(tmp_path, ['required_child_slugs: "alpha, , beta"'])
    brief = load_brief(path)
    assert brief.required_child_slugs == ('alpha', 'beta')

def test_required_child_slugs_single_item_list(tmp_path):
    path = _write_brief(tmp_path, ['required_child_slugs: [solo]'])
    brief = load_brief(path)
    assert brief.required_child_slugs == ('solo',)

def test_required_child_slugs_frozen_roundtrip_and_immutability(tmp_path):
    path = _write_brief(tmp_path, ['required_child_slugs: [x, y]'])
    brief = load_brief(path)
    assert brief.required_child_slugs == ('x', 'y')
    replaced = dataclasses.replace(brief, required_child_slugs=('x', 'y'))
    assert replaced.required_child_slugs == ('x', 'y')
    assert isinstance(replaced, PlanningBrief)
    with pytest.raises(dataclasses.FrozenInstanceError):
        replaced.required_child_slugs = ('z',)