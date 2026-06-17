"""RED oracle pinning the desired post-fix behaviour of
``harness.planner.brief_generator.serialize_child_brief_to_markdown``:

A non-empty ``required_task_ids`` sequence must serialize to a YAML block-list
in the frontmatter that round-trips through
``harness.planner.brief_loader.load_brief``, while an empty list / a missing key
emits no ``required_task_ids:`` line at all.

These tests are RED on current HEAD because the serializer does not emit any
``required_task_ids`` block yet; they go GREEN once that emission lands.
"""
from harness.planner.brief_generator import serialize_child_brief_to_markdown
from harness.planner.brief_loader import load_brief

def _base_brief_data(**overrides) -> dict:
    """A hermetic brief dict whose five required sections are all non-empty so
    ``load_brief`` validation never rejects the round-trip.

    Deliberately omits ``working_dir`` so no in-repo working_dir check fires and
    every case stays hermetic on ``tmp_path``.
    """
    data = {'title': 'Example child brief', 'scope': 'Do the thing described by the parent epic.', 'non_goals': 'Do not rewrite unrelated subsystems.', 'inputs': 'An existing module and its tests.', 'deliverables': 'A patched module plus a passing test.'}
    data.update(overrides)
    return data

def _round_trip(serialized: str, tmp_path):
    brief_path = tmp_path / 'brief.md'
    brief_path.write_text(serialized, encoding='utf-8')
    return load_brief(brief_path)

def test_required_task_ids_block_list_emitted_and_round_trips(tmp_path):
    brief_data = _base_brief_data(required_task_ids=['task-1', 'task-2'])
    serialized = serialize_child_brief_to_markdown(brief_data)
    assert 'required_task_ids:' in serialized
    assert '  - "task-1"' in serialized
    assert '  - "task-2"' in serialized
    brief = _round_trip(serialized, tmp_path)
    assert brief.required_task_ids == ('task-1', 'task-2')
    assert isinstance(brief.required_task_ids, tuple)

def test_empty_required_task_ids_emits_no_line_and_loads_clean(tmp_path):
    brief_data = _base_brief_data(required_task_ids=[])
    serialized = serialize_child_brief_to_markdown(brief_data)
    assert 'required_task_ids:' not in serialized
    brief = _round_trip(serialized, tmp_path)
    assert brief.required_task_ids == ()

def test_missing_required_task_ids_emits_no_line_and_loads_clean(tmp_path):
    brief_data = _base_brief_data()
    assert 'required_task_ids' not in brief_data
    serialized = serialize_child_brief_to_markdown(brief_data)
    assert 'required_task_ids:' not in serialized
    brief = _round_trip(serialized, tmp_path)
    assert brief.required_task_ids == ()

def test_required_task_ids_quoting_escaping_round_trips_via_double_quote(tmp_path):
    tricky_id = 'task-"x"'
    brief_data = _base_brief_data(required_task_ids=[tricky_id])
    serialized = serialize_child_brief_to_markdown(brief_data)
    assert 'required_task_ids:' in serialized
    assert '  - "task-\\"x\\""' in serialized
    brief = _round_trip(serialized, tmp_path)
    assert brief.required_task_ids == (tricky_id,)

def test_existing_five_sections_and_dependencies_frontmatter_unchanged(tmp_path):
    brief_data = _base_brief_data(dependencies=['dep-1', 'dep-2'])
    serialized = serialize_child_brief_to_markdown(brief_data)
    assert 'dependencies:' in serialized
    assert '  - "dep-1"' in serialized
    assert '  - "dep-2"' in serialized
    assert 'required_task_ids:' not in serialized
    for heading in ('# Title', '# Scope', '# Non-Goals', '# Inputs', '# Deliverables'):
        assert heading in serialized
    brief = _round_trip(serialized, tmp_path)
    assert brief.dependencies == ('dep-1', 'dep-2')
    assert brief.required_task_ids == ()
    assert brief.title == 'Example child brief'

def test_brief_without_optionals_still_omits_frontmatter_block(tmp_path):
    brief_data = _base_brief_data()
    serialized = serialize_child_brief_to_markdown(brief_data)
    assert not serialized.lstrip().startswith('---')
    assert 'required_task_ids:' not in serialized
    brief = _round_trip(serialized, tmp_path)
    assert brief.required_task_ids == ()
    assert brief.dependencies == ()