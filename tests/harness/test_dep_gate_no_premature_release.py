"""RED oracle for DEFECT A.1: brief-level dep-gate PREMATURE RELEASE.

``harness.autowork_daemon._brief_dep_gate_ok`` is the brief-level dependency
gate: a candidate task is HELD (returns ``False``) while a sibling brief named
in its owning brief's frontmatter ``dependencies:`` is not yet fully ACCEPTED.

THE LEAK (defect A.1): the gate releases (``continue`` -> falls through to
``return True``) a dependent whose dependency is merely NOT-YET-RUN:

  * ``rec is None``  (the dep's status record is ABSENT)            -> released
  * ``state == 'blocked'`` / ``'zombie'`` (dep not-yet-complete)    -> released

The canonical trigger: a fresh 2-task plan (an impl task + its paired
``test_authoring`` oracle whose brief ``dependencies: [impl-slug]``). At
plan-time the impl record does not exist yet, so the oracle's dep reads ABSENT
and the oracle is dispatched BEFORE the impl lands -> premature release.

INTENDED behaviour: a dependent is RELEASED only when its dependency is a
genuine terminal-ACCEPTED brief (``task_ids`` non-empty AND ``remaining``
empty). A dependency that is absent / not-yet-dispatched / blocked / zombie
means "the dep simply has not COMPLETED yet" -> the dependent MUST be HELD
(``False``). (A true unbreakable deadlock is to be surfaced via explicit
telemetry, NOT a silent state-based release.)

RED on HEAD: ``_brief_dep_gate_ok`` returns ``True`` for the absent / blocked /
zombie cases below; this oracle asserts ``False`` (HOLD), so it FAILS until the
A.1 fix lands.
"""
import textwrap

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


def test_absent_dependency_record_holds_dispatch(tmp_path):
    """DEFECT A.1 core case: a dep whose status record is ABSENT (not yet
    dispatched/planned) must HOLD the dependent, NOT release it.

    This is the exact 2-task-plan trigger: the oracle's brief depends on the
    impl slug, but at plan-time the impl record does not exist yet.
    """
    repo = tmp_path
    _write_brief(repo, "oracle", deps=["impl"])
    # NOTE: the 'impl' brief/record is intentionally NOT present yet — its
    # status record is ABSENT (it has not been dispatched / planned).
    status_records = [
        _record("oracle", ["oracle_t1"], [], "queued"),
    ]
    task = {"task_id": "oracle_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo) is False, (
        "a dependent whose dependency record is ABSENT (not-yet-run) must be "
        "HELD (False) — releasing it is the A.1 premature-release leak"
    )


def test_blocked_dependency_not_yet_complete_holds_dispatch(tmp_path):
    """A dep brief that is BLOCKED has un-accepted work, i.e. is NOT complete,
    so the dependent must be HELD — releasing on 'blocked' is premature."""
    repo = tmp_path
    _write_brief(repo, "oracle", deps=["impl"])
    _write_brief(repo, "impl")
    dep = _record("impl", ["impl_t1"], [], "blocked")
    dep["blocked"] = ["impl_t1"]
    status_records = [
        _record("oracle", ["oracle_t1"], [], "queued"),
        dep,
    ]
    task = {"task_id": "oracle_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo) is False, (
        "a dependent whose dependency is BLOCKED (un-accepted work remaining) "
        "must be HELD (False) — releasing it is the A.1 premature-release leak"
    )


def test_zombie_dependency_not_yet_complete_holds_dispatch(tmp_path):
    """A dep brief in the ZOMBIE state still has un-accepted work, so the
    dependent must be HELD rather than prematurely released."""
    repo = tmp_path
    _write_brief(repo, "oracle", deps=["impl"])
    _write_brief(repo, "impl")
    status_records = [
        _record("oracle", ["oracle_t1"], [], "queued"),
        _record("impl", ["impl_t1"], [], "zombie"),
    ]
    task = {"task_id": "oracle_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo) is False, (
        "a dependent whose dependency is ZOMBIE (un-accepted work remaining) "
        "must be HELD (False) — releasing it is the A.1 premature-release leak"
    )


def test_accepted_dependency_still_releases(tmp_path):
    """REGRESSION GUARD: a genuinely terminal-ACCEPTED dependency (task_ids
    non-empty AND none remaining) must still RELEASE the dependent (True).

    The fix must stop premature release WITHOUT breaking the legitimate
    release-on-completion path.
    """
    repo = tmp_path
    _write_brief(repo, "oracle", deps=["impl"])
    _write_brief(repo, "impl")
    status_records = [
        _record("oracle", ["oracle_t1"], [], "queued"),
        _record("impl", ["impl_t1"], ["impl_t1"], "complete"),
    ]
    task = {"task_id": "oracle_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo) is True, (
        "a fully-ACCEPTED dependency must still release the dependent (True)"
    )


def test_no_declared_deps_still_dispatchable(tmp_path):
    """REGRESSION GUARD: a brief with no frontmatter deps is always
    dispatchable (the no-dep fast path must remain byte-identical)."""
    repo = tmp_path
    _write_brief(repo, "solo")  # no deps
    status_records = [_record("solo", ["solo_t1"], [], "queued")]
    task = {"task_id": "solo_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo) is True
