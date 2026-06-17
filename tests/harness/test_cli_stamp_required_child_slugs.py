"""RED oracle for harness.planner.cli.persist_plan required_child_slugs stamping.

DESIRED post-fix behaviour (ABSENT on HEAD, so this suite is correctly RED on
HEAD and goes GREEN once the impl lands): persist_plan stamps a
``required_child_slugs`` field onto an EPIC plan record from the brief object,
guarded on ``plan.get('plan_kind') == 'epic'`` and idempotent
(``'required_child_slugs' not in plan``), mirroring the existing
``required_task_ids`` stamping. Empty/None values and non-epic plans are never
stamped, and a pre-existing value is never overwritten.

Every test is fully hermetic: it builds its own tmp dir via ``tmp_path``,
constructs an attribute-light brief stub, redirects the process CWD into
``tmp_path`` with ``monkeypatch.chdir`` so persist_plan's best-effort lifecycle
journal write (relative ``state/``) can never touch live state/, calls
``persist_plan(plan, tmp_path / 'plan.json', brief_obj=stub)`` and reads the
JSON back with ``json.loads``.
"""
import json
import types
import pytest
from harness.planner.cli import persist_plan

def _make_brief(**attrs):
    """Build an attribute-light brief stub.

    persist_plan reads source_path / sha256 / working_dir / required_task_ids /
    parent_epic_slug (and, post-fix, required_child_slugs) defensively via
    getattr with defaults, so a SimpleNamespace exposing only what each test
    cares about suffices.
    """
    return types.SimpleNamespace(**attrs)

def _persist_and_load(plan, tmp_path, monkeypatch, brief):
    """Redirect CWD into tmp_path, persist, and return the reloaded JSON dict."""
    monkeypatch.chdir(tmp_path)
    out_path = tmp_path / 'plan.json'
    persist_plan(plan, out_path, brief_obj=brief)
    return json.loads(out_path.read_text())

def test_epic_with_required_child_slugs_tuple_is_stamped_as_list(tmp_path, monkeypatch):
    plan = {'plan_kind': 'epic', 'child_briefs': []}
    brief = _make_brief(required_child_slugs=('a', 'b'))
    data = _persist_and_load(plan, tmp_path, monkeypatch, brief)
    assert data['required_child_slugs'] == ['a', 'b']
    assert isinstance(data['required_child_slugs'], list)

def test_epic_with_required_child_slugs_list_preserves_order(tmp_path, monkeypatch):
    plan = {'plan_kind': 'epic', 'child_briefs': []}
    brief = _make_brief(required_child_slugs=['beta', 'alpha', 'gamma'])
    data = _persist_and_load(plan, tmp_path, monkeypatch, brief)
    assert data['required_child_slugs'] == ['beta', 'alpha', 'gamma']

def test_epic_single_child_slug_is_stamped(tmp_path, monkeypatch):
    plan = {'plan_kind': 'epic', 'child_briefs': []}
    brief = _make_brief(required_child_slugs=('solo',))
    data = _persist_and_load(plan, tmp_path, monkeypatch, brief)
    assert data['required_child_slugs'] == ['solo']

def test_epic_empty_tuple_not_stamped(tmp_path, monkeypatch):
    plan = {'plan_kind': 'epic', 'child_briefs': []}
    brief = _make_brief(required_child_slugs=())
    data = _persist_and_load(plan, tmp_path, monkeypatch, brief)
    assert 'required_child_slugs' not in data

def test_epic_none_not_stamped(tmp_path, monkeypatch):
    plan = {'plan_kind': 'epic', 'child_briefs': []}
    brief = _make_brief(required_child_slugs=None)
    data = _persist_and_load(plan, tmp_path, monkeypatch, brief)
    assert 'required_child_slugs' not in data

def test_non_epic_plan_not_stamped(tmp_path, monkeypatch):
    plan = {'tasks': []}
    brief = _make_brief(required_child_slugs=('a', 'b'))
    data = _persist_and_load(plan, tmp_path, monkeypatch, brief)
    assert 'required_child_slugs' not in data

def test_preexisting_required_child_slugs_not_overwritten(tmp_path, monkeypatch):
    plan = {'plan_kind': 'epic', 'child_briefs': [], 'required_child_slugs': ['x']}
    brief = _make_brief(required_child_slugs=('a', 'b'))
    data = _persist_and_load(plan, tmp_path, monkeypatch, brief)
    assert data['required_child_slugs'] == ['x']

def test_non_epic_plan_not_stamped_guard(tmp_path, monkeypatch):
    plan = {'plan_kind': 'leaf', 'tasks': []}
    brief = _make_brief(required_child_slugs=('a', 'b'))
    data = _persist_and_load(plan, tmp_path, monkeypatch, brief)
    assert 'required_child_slugs' not in data

def test_empty_or_none_skip_guard(tmp_path, monkeypatch):
    for value in ((), None):
        plan = {'plan_kind': 'epic', 'child_briefs': []}
        brief = _make_brief(required_child_slugs=value)
        data = _persist_and_load(plan, tmp_path, monkeypatch, brief)
        assert 'required_child_slugs' not in data

def test_preexisting_value_idempotent_guard(tmp_path, monkeypatch):
    plan = {'plan_kind': 'epic', 'child_briefs': [], 'required_child_slugs': ['keep']}
    brief = _make_brief(required_child_slugs=('override', 'ignored'))
    data = _persist_and_load(plan, tmp_path, monkeypatch, brief)
    assert data['required_child_slugs'] == ['keep']
    assert plan['required_child_slugs'] == ['keep']