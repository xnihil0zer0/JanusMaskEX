"""RED oracle for tools/brief_status.py -- ground-truth brief classifier.

Contract (tools.brief_status.classify_briefs):

    classify_briefs(repo_root) -> list[dict]

    Scan ``repo_root`` for ``brief_hooks_<slug>.md`` and ``plan_hooks_<slug>.json``
    and return one dict per brief/orphan-plan: ``{'slug', 'status', 'detail'}``.
    Status is derived from GROUND TRUTH (the brief's frontmatter + running its
    plan's verification commands at HEAD), so it cannot go stale:

      - brief frontmatter ``epic: true``                 -> 'EPIC'
      - brief has a plan, every distinct verification_command green -> 'DONE'
      - brief has a plan, some command red/errors          -> 'PENDING'
      - brief has NO plan, but the brief's own oracle green -> 'DONE'
      - brief has NO plan and is not already green          -> 'NEEDS-PLAN'
      - a plan with no matching brief                       -> 'ORPHAN-PLAN'

    A convenience query ``status_of(repo_root, slug)`` returns just the status
    string for one slug (or None if neither a brief nor a plan exists for it),
    so a pre-dispatch guard can ask "is this brief already DONE?" cheaply.

    Both functions are fail-safe over malformed inputs (a bad plan JSON is
    skipped, never raised).
"""
import json
import sys

import pytest

import tools.brief_status as bs


def _green(code):
    return f'{sys.executable} -c "import sys; sys.exit({code})"'


def _seed(repo, slug, *, exit_code=0, epic=False, plan=True, brief_cmd=False):
    fm = '---\nepic: true\n---\n\n' if epic else ''
    body = f'{fm}# Title\n\n{slug}\n'
    if brief_cmd:
        body += f'\nverification_command: "{_green(exit_code)}"\n'
    (repo / f'brief_hooks_{slug}.md').write_text(body, encoding='utf-8')
    if plan:
        (repo / f'plan_hooks_{slug}.json').write_text(
            json.dumps({'tasks': [{'task_id': f'{slug}-0',
                                   'verification_command': _green(exit_code)}]}),
            encoding='utf-8')


def _by_slug(rows):
    return {r['slug']: r['status'] for r in rows}


def test_green_plan_is_done(tmp_path):
    _seed(tmp_path, 'a', exit_code=0)
    assert _by_slug(bs.classify_briefs(tmp_path))['a'] == 'DONE'


def test_red_plan_is_pending(tmp_path):
    _seed(tmp_path, 'b', exit_code=1)
    assert _by_slug(bs.classify_briefs(tmp_path))['b'] == 'PENDING'


def test_epic_is_epic(tmp_path):
    _seed(tmp_path, 'c', epic=True)
    assert _by_slug(bs.classify_briefs(tmp_path))['c'] == 'EPIC'


def test_planless_but_green_brief_oracle_is_done(tmp_path):
    _seed(tmp_path, 'd', exit_code=0, plan=False, brief_cmd=True)
    assert _by_slug(bs.classify_briefs(tmp_path))['d'] == 'DONE'


def test_planless_leaf_needs_plan(tmp_path):
    _seed(tmp_path, 'e', plan=False, brief_cmd=False)
    assert _by_slug(bs.classify_briefs(tmp_path))['e'] == 'NEEDS-PLAN'


def test_plan_without_brief_is_orphan(tmp_path):
    (tmp_path / 'plan_hooks_f.json').write_text(
        json.dumps({'tasks': [{'task_id': 'f-0', 'verification_command': _green(0)}]}),
        encoding='utf-8')
    assert _by_slug(bs.classify_briefs(tmp_path))['f'] == 'ORPHAN-PLAN'


def test_mixed_repo_classifies_each_correctly(tmp_path):
    _seed(tmp_path, 'done1', exit_code=0)
    _seed(tmp_path, 'pend1', exit_code=1)
    _seed(tmp_path, 'epic1', epic=True)
    got = _by_slug(bs.classify_briefs(tmp_path))
    assert got == {'done1': 'DONE', 'pend1': 'PENDING', 'epic1': 'EPIC'}


def test_status_of_single_slug(tmp_path):
    _seed(tmp_path, 'g', exit_code=0)
    assert bs.status_of(tmp_path, 'g') == 'DONE'
    assert bs.status_of(tmp_path, 'no-such-slug') is None


def test_failsafe_on_malformed_plan(tmp_path):
    (tmp_path / 'brief_hooks_h.md').write_text('# Title\n', encoding='utf-8')
    (tmp_path / 'plan_hooks_h.json').write_text('{not json', encoding='utf-8')
    # malformed plan -> treated as if it has no usable commands; must not raise.
    rows = bs.classify_briefs(tmp_path)
    assert 'h' in _by_slug(rows)
