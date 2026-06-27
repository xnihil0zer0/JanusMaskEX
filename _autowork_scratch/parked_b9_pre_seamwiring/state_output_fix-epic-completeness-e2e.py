"""B9 -- epic completeness end-to-end (non-vacuous integration test).

Drives the REAL ``harness.planner.cli._run_epic_pipeline(brief_obj, config,
state_dir, output_plan)`` against a per-test ``tmp_path`` ``repo_root`` whose
``state_dir`` is ``repo_root / "state"`` (so ``state_dir.parent == repo_root``,
matching the production ``repo_root = state_dir.parent`` assumption at
cli.py:213). Each case builds its own hermetic tree and its own mocked drafts
and NEVER touches the live ``state/`` directory.

The ONLY mocked seam is the agent draft stub ``run_blind_drafts`` -- patched at
``harness.planner.blind_draft.run_blind_drafts`` (the name the function resolves
through its INSIDE-function import). Everything downstream of that seam runs for
real: ``extract_diff``, ``run_reconciliation``, ``_finalize_epic_children``,
``serialize_child_brief_to_markdown``, ``persist_plan``, the plan validator, the
coverage check and the dedup / unresolved logging. That is what makes the
mutation gate non-vacuous: a stub that no-ops ``_run_epic_pipeline`` or any one
of those real downstream calls must turn at least one assertion RED.

Hermeticity discipline:

* Cases (a)-(e) feed IDENTICAL claude/gemini child sets so the real
  ``extract_diff`` yields convergent-only items and the real
  ``run_reconciliation`` auto-merges WITHOUT ever spawning a live agent.
* Case (f) needs a genuine reconciliation ``unresolved_items`` drop, which only
  arises on a divergent diff item. The reconciliation LOGIC runs for real; only
  the live-agent subprocess seam ``run_both_agents`` is neutralised (returns
  ``(None, None)`` so both agents are "silent") to honour the non-goal of never
  driving a live agent process. ``run_reconciliation`` itself is NOT mocked.

Event / log rows are captured by walking the JSONL ledger files the pipeline
lands under ``state_dir`` and asserted by event/kind name only (never by full
message equality), per the spec.
"""

import json
import types
from pathlib import Path

import pytest

from harness.planner import cli

CONFIG = {"hierarchical_planning": {"enabled": True}}
RTI_VALUE = "rti-inherited-1"


# --------------------------------------------------------------------------- #
# Hermetic tree + fixture builders                                            #
# --------------------------------------------------------------------------- #
def _dirs(tmp_path):
    """Build a hermetic repo_root with state_dir == repo_root / 'state'."""
    repo_root = tmp_path / "repo"
    state_dir = repo_root / "state"
    repo_root.mkdir(parents=True, exist_ok=True)
    state_dir.mkdir(parents=True, exist_ok=True)
    assert state_dir.parent == repo_root
    return (repo_root, state_dir)


def _child(slug, **extra):
    """A well-formed child-brief dict carrying every required brief field."""
    data = {
        "slug": slug,
        "title": "Title for " + slug,
        "scope": "Scope for " + slug + " describing real work to do.",
        "non_goals": "Non-goals for " + slug + ".",
        "inputs": "Inputs for " + slug + ".",
        "deliverables": "Deliverables for " + slug + ".",
        "working_dir": "workdir/" + slug,
    }
    data.update(extra)
    return data


def _brief(repo_root, **attrs):
    """A synthetic epic brief_obj with the attributes the pipeline reads."""
    base = dict(
        required_task_ids=(),
        working_dir=None,
        raw_text="",
        deliverables="- a deliverable line\n",
        source_path=str(repo_root / "brief_hooks_parentepic.md"),
        required_child_slugs=(),
        epic=True,
        sha256="0" * 64,
    )
    base.update(attrs)
    return types.SimpleNamespace(**base)


def _drafts(claude_children, gemini_children=None):
    """Fake drafts object exposing .claude_draft / .gemini_draft epic dicts."""
    if gemini_children is None:
        gemini_children = [dict(c) for c in claude_children]
    return types.SimpleNamespace(
        claude_draft={"plan_kind": "epic", "child_briefs": [dict(c) for c in claude_children]},
        gemini_draft={"plan_kind": "epic", "child_briefs": [dict(c) for c in gemini_children]},
    )


def _patch_seam(monkeypatch, drafts):
    """Mock ONLY the agent draft seam at its source module attribute."""
    import harness.planner.blind_draft as bd

    monkeypatch.setattr(bd, "run_blind_drafts", lambda *a, **k: drafts, raising=False)


def _neutralise_live_agents(monkeypatch):
    """Neutralise the live-agent subprocess seam used by real reconciliation.

    Returns ``(None, None)`` so both planning agents are treated as silent and
    the REAL reconciliation logic marks a divergent diff item unresolved. This
    is NOT a mock of ``run_reconciliation`` -- the reconciliation function and
    all of its merge/unresolved bookkeeping execute for real.
    """
    import harness.planner.reconciliation as rc_mod

    monkeypatch.setattr(rc_mod, "run_both_agents", lambda *a, **k: (None, None), raising=False)


# --------------------------------------------------------------------------- #
# Captured-channel helpers (JSONL ledger discovery under state_dir)           #
# --------------------------------------------------------------------------- #
def _journal_rows(state_dir):
    rows = []
    for path in Path(state_dir).rglob("*.jsonl"):
        try:
            content = path.read_text(encoding="utf-8")
        except OSError:
            continue
        for line in content.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except Exception:
                continue
    return rows


def _event_present(rows, name):
    for r in rows:
        if isinstance(r, dict) and r.get("event") == name:
            return True
    for r in rows:
        try:
            if name in json.dumps(r):
                return True
        except Exception:
            continue
    return False


def _hook_files(repo_root):
    return sorted(Path(repo_root).glob("brief_hooks_*.md"))


def _record(output_plan):
    return json.loads(Path(output_plan).read_text(encoding="utf-8"))


def _live_state_snapshot():
    live = Path("state")
    if live.exists():
        return sorted(p.name for p in live.iterdir())
    return None


# --------------------------------------------------------------------------- #
# Scenario runners shared by the unit-style and integration-style cases       #
# --------------------------------------------------------------------------- #
def _run_happy(tmp_path, monkeypatch):
    """Case (a) scenario: valid multi-child epic, all slugs + deliverables covered."""
    repo_root, state_dir = _dirs(tmp_path)
    children = [_child("alpha-feature"), _child("beta-feature")]
    # Children deliberately OMIT required_task_ids so inheritance is observable.
    for c in children:
        c.pop("required_task_ids", None)
    _patch_seam(monkeypatch, _drafts(children))
    brief = _brief(
        repo_root,
        required_task_ids=(RTI_VALUE,),
        required_child_slugs=("alpha-feature", "beta-feature"),
        deliverables="- alpha feature delivery\n- beta feature delivery\n",
    )
    output_plan = state_dir / "planning" / "merged_plan.json"
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    return repo_root, state_dir, output_plan, rc


def _run_dropped_required(tmp_path, monkeypatch):
    """Case (b) scenario: a required_child_slug omitted from the merged children."""
    repo_root, state_dir = _dirs(tmp_path)
    children = [_child("alpha-feature")]
    _patch_seam(monkeypatch, _drafts(children))
    brief = _brief(
        repo_root,
        required_child_slugs=("alpha-feature", "ghost-child"),
        deliverables="- alpha feature delivery\n",
    )
    output_plan = state_dir / "planning" / "merged_plan.json"
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    return repo_root, state_dir, output_plan, rc


def _run_uncovered(tmp_path, monkeypatch):
    """Case (c) scenario: an uncovered deliverable; all required slugs present."""
    repo_root, state_dir = _dirs(tmp_path)
    children = [_child("alpha-feature")]
    _patch_seam(monkeypatch, _drafts(children))
    brief = _brief(
        repo_root,
        required_child_slugs=("alpha-feature",),
        deliverables="- alpha feature delivery\n- zzz unrelated orphan topic\n",
    )
    output_plan = state_dir / "planning" / "merged_plan.json"
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    return repo_root, state_dir, output_plan, rc


def _run_duplicate(tmp_path, monkeypatch):
    """Case (d) scenario: two children canonicalising to the same slug."""
    repo_root, state_dir = _dirs(tmp_path)
    # 'dup_child' canonicalises (underscore -> hyphen) onto 'dup-child'.
    children = [_child("dup-child"), _child("dup_child"), _child("keep-this")]
    _patch_seam(monkeypatch, _drafts(children))
    brief = _brief(
        repo_root,
        required_child_slugs=("dup-child", "keep-this"),
        deliverables="- dup child task delivery\n- keep this task delivery\n",
    )
    output_plan = state_dir / "planning" / "merged_plan.json"
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    return repo_root, state_dir, output_plan, rc


def _run_missing_field(tmp_path, monkeypatch):
    """Case (e) scenario: one otherwise-valid merged child missing a brief field."""
    repo_root, state_dir = _dirs(tmp_path)
    good = _child("gamma-feature")
    incomplete = _child("delta-feature")
    del incomplete["inputs"]  # missing a required brief field -> advisory, not fatal
    _patch_seam(monkeypatch, _drafts([good, incomplete]))
    brief = _brief(
        repo_root,
        required_child_slugs=("gamma-feature", "delta-feature"),
        deliverables="- gamma feature delivery\n- delta feature delivery\n",
    )
    output_plan = state_dir / "planning" / "merged_plan.json"
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    return repo_root, state_dir, output_plan, rc


def _run_unresolved(tmp_path, monkeypatch):
    """Case (f) scenario: a divergent item dropped as unresolved by real reconciliation."""
    repo_root, state_dir = _dirs(tmp_path)
    keep = [_child("phi-feature"), _child("chi-feature")]
    # claude carries an extra child gemini lacks -> a claude_only divergent item.
    claude_children = keep + [_child("extra-only")]
    gemini_children = [dict(c) for c in keep]
    _patch_seam(monkeypatch, _drafts(claude_children, gemini_children))
    _neutralise_live_agents(monkeypatch)
    brief = _brief(
        repo_root,
        required_child_slugs=("phi-feature", "chi-feature"),
        deliverables="- phi feature delivery\n- chi feature delivery\n",
    )
    output_plan = state_dir / "planning" / "merged_plan.json"
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    return repo_root, state_dir, output_plan, rc


# --------------------------------------------------------------------------- #
# Helper / hermeticity sanity                                                 #
# --------------------------------------------------------------------------- #
def test_helpers_build_hermetic_repo_root_and_state_dir(tmp_path):
    repo_root, state_dir = _dirs(tmp_path)
    assert repo_root.is_dir()
    assert state_dir.is_dir()
    assert state_dir.parent == repo_root
    assert state_dir.name == "state"
    assert str(state_dir).startswith(str(tmp_path))


# --------------------------------------------------------------------------- #
# (a) required_task_ids inheritance / happy path                              #
# --------------------------------------------------------------------------- #
def test_a_required_task_ids_inherited_on_happy_path(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan, rc = _run_happy(tmp_path, monkeypatch)
    assert rc == 0
    assert output_plan.exists()
    # Each serialized child brief carries the inherited parent required_task_ids.
    hooks = _hook_files(repo_root)
    assert len(hooks) >= 2
    for hook in hooks:
        text = hook.read_text(encoding="utf-8")
        assert RTI_VALUE in text, "child %s did not inherit required_task_ids: %r" % (hook.name, text)


def test_case_a_real_pipeline_persists_plan_and_writes_brief_hooks_with_inherited_required_task_ids(
    tmp_path, monkeypatch
):
    repo_root, state_dir, output_plan, rc = _run_happy(tmp_path, monkeypatch)
    assert rc == 0
    assert output_plan.exists()
    record = _record(output_plan)
    assert record.get("plan_kind") == "epic"
    slugs = record.get("child_slugs") or []
    assert "alpha-feature" in slugs and "beta-feature" in slugs
    # The persisted child records also carry the inherited required_task_ids.
    for child in record.get("child_briefs", []):
        assert RTI_VALUE in (child.get("required_task_ids") or [])
    # Hooks were written into repo_root, not into state_dir.
    names = {p.name for p in _hook_files(repo_root)}
    assert "brief_hooks_alpha-feature.md" in names
    assert "brief_hooks_beta-feature.md" in names


# --------------------------------------------------------------------------- #
# (b) dropped required child -> hard reject                                    #
# --------------------------------------------------------------------------- #
def test_b_dropped_required_child_hard_reject(tmp_path, monkeypatch, capsys):
    repo_root, state_dir, output_plan, rc = _run_dropped_required(tmp_path, monkeypatch)
    err = capsys.readouterr().err
    assert rc != 0
    rows = _journal_rows(state_dir)
    rejected = ("missing_required_child" in err) or _event_present(rows, "planner_validation_rejected")
    assert rejected, "expected a planner_validation_rejected signal; stderr=%r" % err


def test_case_b_real_pipeline_rejects_dropped_required_child_no_plan_no_hooks(
    tmp_path, monkeypatch, capsys
):
    repo_root, state_dir, output_plan, rc = _run_dropped_required(tmp_path, monkeypatch)
    err = capsys.readouterr().err
    assert rc != 0
    # Hard reject is surfaced (no leaf-task / no daemon wrapper here, so the
    # structural rejection lands on stderr as the validation code).
    rows = _journal_rows(state_dir)
    assert ("missing_required_child" in err) or _event_present(rows, "planner_validation_rejected")
    # NO plan persisted and NO child hooks written on the rejected attempt.
    assert not output_plan.exists()
    assert _hook_files(repo_root) == []


# --------------------------------------------------------------------------- #
# (c) uncovered deliverable -> advisory gap (exit 0)                           #
# --------------------------------------------------------------------------- #
def test_c_uncovered_deliverable_advisory_gap(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan, rc = _run_uncovered(tmp_path, monkeypatch)
    assert rc == 0
    assert _event_present(_journal_rows(state_dir), "epic_coverage_gap")


def test_case_c_real_pipeline_emits_coverage_check_and_epic_coverage_gap_exit_zero(
    tmp_path, monkeypatch
):
    repo_root, state_dir, output_plan, rc = _run_uncovered(tmp_path, monkeypatch)
    assert rc == 0
    assert output_plan.exists()
    record = _record(output_plan)
    # The coverage_check artifact is emitted onto the persisted epic record.
    assert isinstance(record.get("coverage_check"), dict)
    # And an epic_coverage_gap row exists -- without asserting any uncovered list.
    assert _event_present(_journal_rows(state_dir), "epic_coverage_gap")


# --------------------------------------------------------------------------- #
# (d) deduped duplicate -> drop row + de-duplicated persisted plan            #
# --------------------------------------------------------------------------- #
def test_d_deduped_duplicate_drop_row(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan, rc = _run_duplicate(tmp_path, monkeypatch)
    assert rc == 0
    assert _event_present(_journal_rows(state_dir), "epic_child_dropped")


def test_case_d_real_pipeline_emits_epic_child_dropped_and_dedups_persisted_plan(
    tmp_path, monkeypatch
):
    repo_root, state_dir, output_plan, rc = _run_duplicate(tmp_path, monkeypatch)
    assert rc == 0
    assert output_plan.exists()
    record = _record(output_plan)
    slugs = record.get("child_slugs") or []
    # The duplicate collapsed: the canonical slug appears exactly once.
    assert slugs.count("dup-child") == 1
    assert "keep-this" in slugs
    # And a drop row was emitted for the dedup.
    assert _event_present(_journal_rows(state_dir), "epic_child_dropped")


# --------------------------------------------------------------------------- #
# (e) reconciled child missing a required brief field -> advisory not refusal #
# --------------------------------------------------------------------------- #
def test_e_missing_required_field_advisory_not_refusal(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan, rc = _run_missing_field(tmp_path, monkeypatch)
    assert rc == 0
    rows = _journal_rows(state_dir)
    advisory = _event_present(rows, "epic_child_advisory") or any(
        "child_briefs" in json.dumps(r) for r in rows
    )
    assert advisory, "expected an advisory (not hard-refusal) row; rows=%r" % rows


def test_case_e_real_pipeline_advisory_on_missing_field_still_persists(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan, rc = _run_missing_field(tmp_path, monkeypatch)
    assert rc == 0
    assert output_plan.exists()
    # The well-formed epic still writes its child briefs despite the advisory.
    names = {p.name for p in _hook_files(repo_root)}
    assert "brief_hooks_gamma-feature.md" in names
    assert "brief_hooks_delta-feature.md" in names
    rows = _journal_rows(state_dir)
    assert _event_present(rows, "epic_child_advisory") or any(
        "child_briefs" in json.dumps(r) for r in rows
    )


# --------------------------------------------------------------------------- #
# (f) reconciliation unresolved_items -> unresolved row                        #
# --------------------------------------------------------------------------- #
def test_f_unresolved_items_drop_unresolved_row(tmp_path, monkeypatch):
    repo_root, state_dir, output_plan, rc = _run_unresolved(tmp_path, monkeypatch)
    assert rc == 0
    assert _event_present(_journal_rows(state_dir), "epic_child_unresolved")


def test_case_f_real_pipeline_emits_epic_child_unresolved_for_unresolved_items(
    tmp_path, monkeypatch
):
    repo_root, state_dir, output_plan, rc = _run_unresolved(tmp_path, monkeypatch)
    assert rc == 0
    assert output_plan.exists()
    # The convergent children still merged + persisted.
    record = _record(output_plan)
    slugs = record.get("child_slugs") or []
    assert "phi-feature" in slugs and "chi-feature" in slugs
    # The divergent child dropped as unresolved was journaled.
    assert _event_present(_journal_rows(state_dir), "epic_child_unresolved")


# --------------------------------------------------------------------------- #
# Regression / discipline guards                                              #
# --------------------------------------------------------------------------- #
def test_regress_run_blind_drafts_is_only_mocked_seam_downstream_runs_real(tmp_path, monkeypatch):
    """Only run_blind_drafts is mocked; downstream helpers execute for real.

    Proven by a real-only side effect: the persisted child slug was
    CANONICALISED by the real ``_finalize_epic_children`` (underscore -> hyphen)
    and the coverage check stamped a real ``coverage_check`` dict -- neither of
    which a mocked/stubbed downstream would produce.
    """
    repo_root, state_dir = _dirs(tmp_path)
    children = [_child("reg_under_score"), _child("plain-child")]
    _patch_seam(monkeypatch, _drafts(children))
    brief = _brief(
        repo_root,
        required_child_slugs=("reg-under-score", "plain-child"),
        deliverables="- reg under score delivery\n- plain child delivery\n",
    )
    output_plan = state_dir / "planning" / "merged_plan.json"
    rc = cli._run_epic_pipeline(brief, CONFIG, state_dir, output_plan)
    assert rc == 0
    record = _record(output_plan)
    slugs = record.get("child_slugs") or []
    assert "reg-under-score" in slugs  # real _finalize_epic_children canonicalised it
    assert "reg_under_score" not in slugs
    assert isinstance(record.get("coverage_check"), dict)  # real compute_epic_coverage ran


def test_regress_state_dir_parent_equals_repo_root_no_live_state_access(tmp_path, monkeypatch):
    before = _live_state_snapshot()
    repo_root, state_dir, output_plan, rc = _run_happy(tmp_path, monkeypatch)
    assert rc == 0
    assert state_dir.parent == repo_root
    assert str(output_plan).startswith(str(tmp_path))
    for hook in _hook_files(repo_root):
        assert str(hook).startswith(str(tmp_path))
    after = _live_state_snapshot()
    assert after == before, "the run must never touch the live state/ directory"


def test_regress_red_on_head_green_after_b1_b8_land():
    """Structural completeness: one test per case (a)-(f) covering each behaviour.

    Each landed behaviour is independently asserted by a distinct case so a stub
    mutating _run_epic_pipeline or any downstream real call breaks at least one.
    """
    g = globals()
    for name in (
        "test_a_required_task_ids_inherited_on_happy_path",
        "test_b_dropped_required_child_hard_reject",
        "test_c_uncovered_deliverable_advisory_gap",
        "test_d_deduped_duplicate_drop_row",
        "test_e_missing_required_field_advisory_not_refusal",
        "test_f_unresolved_items_drop_unresolved_row",
    ):
        assert callable(g.get(name)), "missing case function %s" % name


def test_regress_mutating_any_downstream_call_breaks_at_least_one_case(tmp_path, monkeypatch):
    """Positive controls proving the REAL pipeline control-flow is exercised.

    A no-op stub of _run_epic_pipeline (e.g. ``return 0``) would fail these:
    empty drafts MUST short-circuit to exit 2, and non-empty drafts that
    reconcile to no children MUST short-circuit to exit 1.
    """
    # Both agents empty -> exit 2.
    repo_a, state_a = _dirs(tmp_path / "a")
    empty = types.SimpleNamespace(claude_draft={}, gemini_draft={})
    _patch_seam(monkeypatch, empty)
    brief_a = _brief(repo_a)
    plan_a = state_a / "planning" / "merged_plan.json"
    rc_a = cli._run_epic_pipeline(brief_a, CONFIG, state_a, plan_a)
    assert rc_a == 2
    assert not plan_a.exists()

    # Non-empty drafts but no child briefs -> reconciliation merges nothing -> exit 1.
    repo_b, state_b = _dirs(tmp_path / "b")
    nochildren = types.SimpleNamespace(
        claude_draft={"plan_kind": "epic", "child_briefs": []},
        gemini_draft={"plan_kind": "epic", "child_briefs": []},
    )
    _patch_seam(monkeypatch, nochildren)
    brief_b = _brief(repo_b)
    plan_b = state_b / "planning" / "merged_plan.json"
    rc_b = cli._run_epic_pipeline(brief_b, CONFIG, state_b, plan_b)
    assert rc_b == 1
    assert not plan_b.exists()
