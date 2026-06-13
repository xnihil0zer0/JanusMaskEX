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
  dependency on a sibling brief that has NOT completed -- this includes a dep
  whose record is ABSENT / not-yet-dispatched, or whose state is blocked /
  zombie / queued / in_flight (DEFECT A.1: these were prematurely RELEASED);
* returns True (DISPATCH) only when every declared dep brief is a genuine
  terminal-ACCEPTED brief (task_ids non-empty AND remaining empty), or the
  owning brief declares no frontmatter deps.

A.1 RED on HEAD: the absent / blocked cases currently return True (leak).
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


def test_absent_dep_slug_holds_dispatch(tmp_path):
    """DEFECT A.1: a declared dep slug with NO record (not yet dispatched /
    planned) means the dependency has NOT completed -> the dependent must be
    HELD, not prematurely released."""
    repo = tmp_path
    _write_brief(repo, "child", deps=["ghost"])  # 'ghost' has no record yet
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
    ]
    task = {"task_id": "child_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo) is False, (
        "an absent / not-yet-dispatched dep record means the dependency has "
        "not completed -> HOLD (False); releasing it is the A.1 leak"
    )


def test_blocked_dep_holds_dispatch(tmp_path):
    """DEFECT A.1: a dep brief that is BLOCKED has un-accepted work -> it is
    not complete -> the dependent must be HELD, not released."""
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
    assert awd._brief_dep_gate_ok(task, status_records, repo) is False, (
        "a BLOCKED dep brief still has un-accepted work -> HOLD (False); "
        "releasing it is the A.1 leak"
    )


def test_no_declared_deps_is_dispatchable(tmp_path):
    """A brief with no frontmatter deps is always dispatchable (byte-identical path)."""
    repo = tmp_path
    _write_brief(repo, "solo")  # no deps
    status_records = [_record("solo", ["solo_t1"], [], "queued")]
    task = {"task_id": "solo_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo) is True


# ---------------------------------------------------------------------------
# DEADLOCK-BREAKER (brief-dep-deadlock-breaker): a brief-frontmatter dep that
# is TERMINALLY unresolvable must RELEASE the dependent (release-with-warning)
# and surface telemetry marker ``brief_dep_unresolvable`` -- NOT infinite-hold,
# NOT terminally-block. Two terminal classes:
#   (a) no brief exists under ANY spelling for the dep slug;
#   (b) the dep brief exists but ALL of its tasks carry a blocked/.exhausted
#       marker (every task permanently dead).
# Plus TOLERANT slug matching: hyphen/underscore (and case) are normalized when
# resolving a dep slug to a brief, so a typo degrades to a successful match.
#
# These cases pass the daemon's live ``state_dir`` as the 4th argument so the
# deadlock-breaker is active; the legacy 3-arg call path (used by the existing
# cases above and in test_dep_gate_no_premature_release.py) is preserved
# byte-identical (absent -> HOLD), which is the anti-seesaw union guarantee.
# ---------------------------------------------------------------------------


def _state_dir(tmp_path, exhausted_task_ids=()):
    """Build a minimal daemon state_dir with optional blocked/.exhausted markers."""
    sd = tmp_path / "state"
    blocked = sd / "tasks" / "blocked"
    blocked.mkdir(parents=True, exist_ok=True)
    for tid in exhausted_task_ids:
        (blocked / f"{tid}.exhausted").write_text("1", encoding="utf-8")
    return sd


def _read_telemetry_events(state_dir):
    """Return the list of ``event`` strings written to impl_progress.jsonl."""
    import json

    ledger = state_dir / "impl_progress.jsonl"
    if not ledger.exists():
        return []
    events = []
    for line in ledger.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            row = json.loads(line)
        except ValueError:
            continue
        if isinstance(row, dict) and row.get("event"):
            events.append(row["event"])
    return events


def test_unresolvable_dep_no_brief_releases_with_warning(tmp_path):
    """(a) A dep slug with NO matching brief under any spelling is TERMINALLY
    unresolvable -> RELEASE the dependent (True) and surface telemetry marker
    ``brief_dep_unresolvable`` (release-with-warning, not infinite-hold)."""
    repo = tmp_path
    # 'agent_workers' matches no brief on disk and no status record (the real
    # observed wedge). The dependent's own brief exists.
    _write_brief(repo, "child", deps=["agent_workers"])
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
    ]
    state_dir = _state_dir(tmp_path)
    task = {"task_id": "child_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo, state_dir) is True, (
        "a dep slug with no brief under any spelling is terminally unresolvable "
        "-> RELEASE (True), not infinite-hold"
    )
    assert "brief_dep_unresolvable" in _read_telemetry_events(state_dir), (
        "the deadlock-breaker must surface telemetry marker 'brief_dep_unresolvable'"
    )


def test_unresolvable_dep_all_tasks_exhausted_releases_with_warning(tmp_path):
    """(b) The dep brief EXISTS but ALL its tasks carry a blocked/.exhausted
    marker (permanently dead) -> TERMINALLY unresolvable -> RELEASE the
    dependent (True) + telemetry marker ``brief_dep_unresolvable``."""
    repo = tmp_path
    _write_brief(repo, "child", deps=["sibling"])
    _write_brief(repo, "sibling")
    sib = _record("sibling", ["sib_t1", "sib_t2"], [], "blocked")
    sib["blocked"] = ["sib_t1", "sib_t2"]
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
        sib,
    ]
    # Every one of sibling's tasks is .exhausted -> the brief can never complete.
    state_dir = _state_dir(tmp_path, exhausted_task_ids=["sib_t1", "sib_t2"])
    task = {"task_id": "child_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo, state_dir) is True, (
        "a dep brief whose every task is .exhausted is terminally unresolvable "
        "-> RELEASE (True), not infinite-hold"
    )
    assert "brief_dep_unresolvable" in _read_telemetry_events(state_dir), (
        "all-tasks-exhausted must surface telemetry marker 'brief_dep_unresolvable'"
    )


def test_tolerant_slug_underscore_typo_resolves_to_brief(tmp_path):
    """TOLERANT slug: dep slug ``foo_bar`` (underscore) with a real brief slug
    ``foo-bar`` (hyphen) must RESOLVE to that brief (treated as present), so
    normal gating applies -- a not-yet-accepted resolved dep HOLDS the
    dependent rather than wedging on the typo or falsely releasing it."""
    repo = tmp_path
    _write_brief(repo, "child", deps=["foo_bar"])  # underscore typo
    _write_brief(repo, "foo-bar")  # real brief uses hyphen
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
        # real brief, slug spelled with a hyphen, still has un-accepted work
        _record("foo-bar", ["fb_t1"], [], "queued"),
    ]
    state_dir = _state_dir(tmp_path)
    task = {"task_id": "child_t1"}
    # Tolerant match resolves foo_bar -> foo-bar (present, un-accepted) -> HOLD,
    # NOT a wedge and NOT a terminal release.
    assert awd._brief_dep_gate_ok(task, status_records, repo, state_dir) is False, (
        "a hyphen/underscore-typo dep slug must tolerantly resolve to the real "
        "brief and gate normally (HOLD while that brief is un-accepted), not wedge"
    )
    assert "brief_dep_unresolvable" not in _read_telemetry_events(state_dir), (
        "a tolerantly-resolved dep is NOT unresolvable -> no warning marker"
    )


def test_tolerant_slug_resolved_then_accepted_releases(tmp_path):
    """TOLERANT slug, completion path: once the hyphen-spelled real brief is
    fully accepted, the underscore-typo dependent RELEASES normally (True)."""
    repo = tmp_path
    _write_brief(repo, "child", deps=["foo_bar"])
    _write_brief(repo, "foo-bar")
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
        _record("foo-bar", ["fb_t1"], ["fb_t1"], "complete"),
    ]
    state_dir = _state_dir(tmp_path)
    task = {"task_id": "child_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo, state_dir) is True


def test_transient_absent_dep_with_brief_on_disk_still_holds(tmp_path):
    """REGRESSION (transient HOLD preserved): a dep whose brief FILE EXISTS on
    disk but has no status record yet (not-yet-planned) is TRANSIENT, not
    terminal -> still HOLD (False), and no unresolvable warning is emitted."""
    repo = tmp_path
    _write_brief(repo, "child", deps=["sibling"])
    _write_brief(repo, "sibling")  # brief authored, just not planned yet
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
        # NOTE: no 'sibling' status record -> not yet planned (transient)
    ]
    state_dir = _state_dir(tmp_path)
    task = {"task_id": "child_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo, state_dir) is False, (
        "a dep whose brief exists on disk but is not yet planned is a TRANSIENT "
        "absence -> still HOLD (False); only no-brief-anywhere is terminal"
    )
    assert "brief_dep_unresolvable" not in _read_telemetry_events(state_dir), (
        "a transient (not-yet-planned) absence must NOT emit the warning marker"
    )


def test_queued_dep_still_holds_under_breaker(tmp_path):
    """REGRESSION (transient HOLD preserved): a resolved dep that is queued with
    un-accepted work still HOLDS even with the deadlock-breaker active."""
    repo = tmp_path
    _write_brief(repo, "child", deps=["sibling"])
    _write_brief(repo, "sibling")
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
        _record("sibling", ["sib_t1"], [], "queued"),
    ]
    state_dir = _state_dir(tmp_path)
    task = {"task_id": "child_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo, state_dir) is False


def test_in_flight_dep_still_holds_under_breaker(tmp_path):
    """REGRESSION (transient HOLD preserved): a resolved dep that is in_flight
    (partially accepted, work outstanding, none exhausted) still HOLDS."""
    repo = tmp_path
    _write_brief(repo, "child", deps=["sibling"])
    _write_brief(repo, "sibling")
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
        # two tasks, one accepted, one outstanding -> in_flight, NOT exhausted
        _record("sibling", ["sib_t1", "sib_t2"], ["sib_t1"], "in_flight"),
    ]
    state_dir = _state_dir(tmp_path)  # no .exhausted markers
    task = {"task_id": "child_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo, state_dir) is False, (
        "an in_flight dep with outstanding non-exhausted work must still HOLD"
    )
    assert "brief_dep_unresolvable" not in _read_telemetry_events(state_dir)


def test_blocked_but_retryable_dep_still_holds_under_breaker(tmp_path):
    """REGRESSION (transient HOLD preserved): a dep brief that is blocked but
    RETRYABLE (no .exhausted markers) is NOT terminal -> still HOLD (False)."""
    repo = tmp_path
    _write_brief(repo, "child", deps=["sibling"])
    _write_brief(repo, "sibling")
    sib = _record("sibling", ["sib_t1"], [], "blocked")
    sib["blocked"] = ["sib_t1"]
    status_records = [
        _record("child", ["child_t1"], [], "queued"),
        sib,
    ]
    state_dir = _state_dir(tmp_path)  # blocked, but NOT exhausted -> retryable
    task = {"task_id": "child_t1"}
    assert awd._brief_dep_gate_ok(task, status_records, repo, state_dir) is False, (
        "a blocked-but-retryable dep (no .exhausted) is transient -> still HOLD"
    )
    assert "brief_dep_unresolvable" not in _read_telemetry_events(state_dir)
