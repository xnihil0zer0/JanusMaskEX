"""RED oracle for FIX 2: daemon brief-level dependency gating.

Brief frontmatter ``dependencies: [sibling-slug]`` is stripped at plan
normalization (a slug is not an in-plan task_id), so the daemon has no way to
hold a brief's tasks until the depended-on SIBLING BRIEF's tasks have all
landed. The symptom: a child brief that imports a sibling module gets staged +
dispatched before the sibling's output lands -> smoke_failed -> blocked ->
wasted attempt.

The fix adds a brief-level dep gate, exposed as
``autowork_daemon._brief_dep_gate_ok(task, status_records, repo_root)``:

* returns False (HOLD)  when the task's owning brief declares a frontmatter
  dependency on a sibling brief that EXISTS but is not yet fully accepted;
* returns True (DISPATCH) when every declared dep brief is fully accepted, OR
  when a declared dep slug is ABSENT / never-planned / terminally-blocked
  (no-deadlock fallback -- the gate must never wedge the queue forever).

RED on HEAD: the helper does not exist (AttributeError).
"""
import textwrap

import pytest

from harness import autowork_daemon as awd


def _write_brief(repo_root, slug, deps=None):
    fm = ""
    if deps:
        lines = ["---", "dependencies:"]
        lines += [f'  - "{d}"' for d in deps]
        lines += ["---", ""]
        fm = "\n".join(lines)
    body = textwrap.dedent(
        f"""\
        # Goal
        brief {slug}
        # Required plan shape
        x
        """
    )
    (repo_root / f"brief_hooks_{slug}.md").write_text(fm + body, encoding="utf-8")


def _record(slug, task_ids, accepted_ids, state):
    accepted = [{"task_id": t} for t in accepted_ids]
    remaining = [t for t in task_ids if t not in accepted_ids]
    return {
        "slug": slug,
        "brief_filename": f"brief_hooks_{slug}.md",
        "task_ids": list(task_ids),
        "accepted": accepted,
        "remaining": remaining,
        "blocked": [],
        "state": state,
    }


def test_unmet_brief_dep_holds_dispatch(tmp_path):
    """A task whose brief depends on an un-accepted sibling brief is HELD."""
    repo = tmp_path
    _write_brief(repo, "child", deps=["sibling"])
    _write_brief(repo, "sibling")
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
        # sibling has an un-accepted task -> NOT complete
        _record("sibling", ["sib_t1"], [], "queued"),
    ]
    task = {"task_id": "child_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo) is False, (
        "task must be HELD while its declared sibling brief dep is not fully accepted"
    )


def test_met_brief_dep_allows_dispatch(tmp_path):
    """Once the sibling brief is fully accepted (complete), dispatch is allowed."""
    repo = tmp_path
    _write_brief(repo, "child", deps=["sibling"])
    _write_brief(repo, "sibling")
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
        _record("sibling", ["sib_t1"], ["sib_t1"], "complete"),
    ]
    task = {"task_id": "child_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo) is True


def test_absent_dep_slug_does_not_deadlock(tmp_path):
    """A declared dep slug with NO record (never planned) must NOT wedge -> dispatch."""
    repo = tmp_path
    _write_brief(repo, "child", deps=["ghost"])  # 'ghost' is never planned
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
    ]
    task = {"task_id": "child_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo) is True, (
        "an absent / never-planned dep slug must fall back to DISPATCH (no deadlock)"
    )


def test_terminally_blocked_dep_does_not_deadlock(tmp_path):
    """A dep brief that is terminally blocked must NOT wedge the queue forever."""
    repo = tmp_path
    _write_brief(repo, "child", deps=["sibling"])
    _write_brief(repo, "sibling")
    sib = _record("sibling", ["sib_t1"], [], "blocked")
    sib["blocked"] = ["sib_t1"]
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
        sib,
    ]
    task = {"task_id": "child_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo) is True, (
        "a terminally-blocked dep brief must fall back to DISPATCH (no deadlock)"
    )


def test_no_declared_deps_is_dispatchable(tmp_path):
    """A brief with no frontmatter deps is always dispatchable (byte-identical path)."""
    repo = tmp_path
    _write_brief(repo, "solo")  # no deps
    status_records = [_record("solo", ["solo_t1"], [], "queued")]
    task = {"task_id": "solo_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo) is True
