"""RED oracle for the B6 credential-naming constraint hook in plan_normalizer.

B6: ``ast_enforcer`` flags ANY variable whose name matches
``(?i)(password|secret|key)`` assigned a string LITERAL as a "Hardcoded
credential detected" security error -- strict even for an external clean-room
target. A leaf whose natural implementation binds a field label / check id to a
variable named ``key`` therefore fails synthesis (``synthesis_or_ast_failed``)
and exhausts its retry budget, even though the code is correct and contains no
real secret.

Fix (handoff option a -- lowest risk, no loosening of the security gate): for an
EXTERNAL-build leaf plan, ``normalize_plan(plan, repo_root=<external>)`` appends
a short directive to every non-``test_authoring`` task's
``spec['implementation_notes']`` steering the blind synthesis agent away from
binding string literals to credential-named variables (use a neutral name or
iterate a collection literal). This mirrors the ``_inject_oracle_sources``
precedent -- it changes only the spec the agent reads, never the code it gates.

Strict no-op when ``repo_root`` is None, when it resolves to PROJECT_ROOT (a
JM-internal self-fix plan must NEVER be steered), and for an epic plan
(``child_slugs`` truthy). ``test_authoring`` tasks are left untouched. Pure
(deep copy, no input mutation) and idempotent (the marker is injected at most
once).
"""
from __future__ import annotations

import copy
import pathlib

from harness.paths import PROJECT_ROOT
from harness.planner.plan_normalizer import normalize_plan

MARKER = "CREDENTIAL-NAMING CONSTRAINT"


def _write_oracle(root: pathlib.Path, rel: str) -> None:
    p = root / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("def test_placeholder():\n    assert True\n", encoding="utf-8")


def _impl_task(task_id="backtrack-impl", leaf="backtrack", notes="", meta="data_model"):
    return {
        "task_id": task_id,
        "meta_task_type": meta,
        "files_touched": ["ngv2/%s.py" % leaf],
        "dependencies": [],
        "verification_command": "python -m pytest tests/test_%s.py -q" % leaf,
        "spec": {"objective": "build ngv2/%s.py" % leaf, "implementation_notes": notes},
    }


def _notes(plan, task_id):
    for t in plan["tasks"]:
        if t["task_id"] == task_id:
            return t["spec"]["implementation_notes"]
    raise AssertionError("task %r not found" % task_id)


def test_external_impl_task_gets_credential_constraint(tmp_path):
    """An external-build impl leaf gets the credential-naming directive."""
    _write_oracle(tmp_path, "tests/test_backtrack.py")
    plan = {"tasks": [_impl_task(notes="Build the backtracking solver.")]}
    out = normalize_plan(plan, repo_root=tmp_path)
    note = _notes(out, "backtrack-impl")
    assert MARKER in note
    # the directive must name the heuristic so the agent can avoid it
    low = note.lower()
    assert "string literal" in low
    assert any(w in low for w in ("key", "secret", "password"))
    # original notes are preserved
    assert "Build the backtracking solver." in note


def test_repo_root_none_is_strict_noop():
    plan = {"tasks": [_impl_task(notes="orig")]}
    before = copy.deepcopy(plan)
    out = normalize_plan(plan, repo_root=None)
    assert MARKER not in _notes(out, "backtrack-impl")
    assert plan == before  # input not mutated


def test_project_root_is_strict_noop(tmp_path):
    """A JM-internal self-fix plan (repo_root == PROJECT_ROOT) is never steered."""
    plan = {"tasks": [_impl_task(notes="orig")]}
    out = normalize_plan(plan, repo_root=PROJECT_ROOT)
    assert MARKER not in _notes(out, "backtrack-impl")


def test_epic_plan_is_strict_noop(tmp_path):
    plan = {"child_slugs": ["ngv2-e4-analysis"], "tasks": [_impl_task(notes="orig")]}
    out = normalize_plan(plan, repo_root=tmp_path)
    assert MARKER not in _notes(out, "backtrack-impl")


def test_test_authoring_task_untouched(tmp_path):
    """The constraint targets impl tasks only; oracle-authoring tasks are skipped."""
    _write_oracle(tmp_path, "tests/test_backtrack.py")
    _write_oracle(tmp_path, "tests/test_other.py")
    plan = {"tasks": [
        _impl_task(notes="impl"),
        {
            "task_id": "author-other-oracle",
            "meta_task_type": "test_authoring",
            "files_touched": ["tests/test_other.py"],
            "dependencies": [],
            "verification_command": "python -m pytest tests/test_other.py -q",
            "spec": {"objective": "author oracle", "implementation_notes": "write tests"},
        },
    ]}
    out = normalize_plan(plan, repo_root=tmp_path)
    assert MARKER in _notes(out, "backtrack-impl")
    assert MARKER not in _notes(out, "author-other-oracle")


def test_idempotent(tmp_path):
    _write_oracle(tmp_path, "tests/test_backtrack.py")
    plan = {"tasks": [_impl_task(notes="orig")]}
    once = normalize_plan(plan, repo_root=tmp_path)
    twice = normalize_plan(once, repo_root=tmp_path)
    assert _notes(twice, "backtrack-impl").count(MARKER) == 1
    assert once == twice
