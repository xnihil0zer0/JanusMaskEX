"""Oracle: self-heal auto-promotion must skip completed / stale tasks.

RED on HEAD: ``harness.autowork_daemon`` has no
``_selfheal_target_satisfied_or_stale`` helper, ``_auto_promote_brief_eligible``
does not consult it, and ``_retry_blocked_tasks`` does not write a PERSISTENT
skip marker on exhaustion. So a self-heal corrective brief for a task whose work
is already done (e.g. ``md_d_01`` — its deliverable shipped under
``method_d_01``) keeps getting re-promoted: it fails (no valid new diff) ->
blocked -> the harvester regenerates the brief and EVICTS ``blocked/<tid>.*``
(including ``.exhausted``), resetting the retry budget -> eligible again -> loop.

GREEN after the fix: a self-heal brief ``selfheal_<tid>`` is INELIGIBLE for
auto-promotion when ``<tid>`` is already accepted in the ledger (completed) or a
persistent ``state/control/autowork/selfheal_skip/<tid>`` marker exists (stale),
and the exhaustion path writes that marker OUTSIDE ``blocked/`` so the harvester
cannot clear it.
"""
import json
import time

import pytest


def _mk_state(tmp_path):
    state = tmp_path / "state"
    (state / "control" / "autowork").mkdir(parents=True, exist_ok=True)
    (state / "tasks" / "blocked").mkdir(parents=True, exist_ok=True)
    return state


def _write_accepted_row(state, tid, sha="deadbeef"):
    row = {"ts": "2026-06-05T00:00:00Z", "phase": "accepted",
           "task_id": tid, "event": "auto_commit", "commit_sha": sha, "exit": 0}
    with (state / "impl_progress.jsonl").open("a") as f:
        f.write(json.dumps(row) + "\n")


# ---- the new helper -------------------------------------------------------

def test_helper_true_on_persistent_skip_marker(tmp_path):
    from harness.autowork_daemon import _selfheal_target_satisfied_or_stale
    state = _mk_state(tmp_path)
    skip_dir = state / "control" / "autowork" / "selfheal_skip"
    skip_dir.mkdir(parents=True, exist_ok=True)
    (skip_dir / "md_d_01_extract_class_interface").write_text("1")
    assert _selfheal_target_satisfied_or_stale(state, "md_d_01_extract_class_interface") is True


def test_helper_true_when_tid_already_accepted(tmp_path):
    from harness.autowork_daemon import _selfheal_target_satisfied_or_stale
    state = _mk_state(tmp_path)
    _write_accepted_row(state, "some_done_task")
    assert _selfheal_target_satisfied_or_stale(state, "some_done_task") is True


def test_helper_false_for_fresh_tid(tmp_path):
    """A genuine, never-seen failure is NOT stale/done -> still promotable."""
    from harness.autowork_daemon import _selfheal_target_satisfied_or_stale
    state = _mk_state(tmp_path)
    assert _selfheal_target_satisfied_or_stale(state, "brand_new_failure") is False


# ---- eligibility integration ---------------------------------------------

def test_eligible_false_for_satisfied_selfheal_brief(tmp_path, monkeypatch):
    """Even with the flag ON and provenance valid, a satisfied/stale self-heal
    brief is ineligible (the new guard short-circuits before the fast-path)."""
    import harness.selfheal as selfheal
    from harness import autowork_daemon
    state = _mk_state(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    tid = "md_d_01_extract_class_interface"
    slug = "selfheal_" + tid
    (repo / f"brief_hooks_{slug}.md").write_text("# x\n")
    # Make the provenance fast-path WOULD-grant eligibility, isolating the guard.
    monkeypatch.setattr(selfheal, "_selfheal_provenance_valid", lambda *a, **k: True)
    skip_dir = state / "control" / "autowork" / "selfheal_skip"
    skip_dir.mkdir(parents=True, exist_ok=True)
    (skip_dir / tid).write_text("1")
    cfg = {"autowork": {"selfheal_auto_promote": True}, "selfheal_auto_promote": True}
    out = autowork_daemon._auto_promote_brief_eligible(
        state, slug, time.time(), config=cfg, repo_root=repo)
    assert out is False


def test_eligible_true_for_fresh_selfheal_brief(tmp_path, monkeypatch):
    """Regression: a genuine fresh self-heal brief (not done/stale) stays
    eligible so real failures still self-heal."""
    import harness.selfheal as selfheal
    from harness import autowork_daemon
    state = _mk_state(tmp_path)
    repo = tmp_path / "repo"
    repo.mkdir()
    slug = "selfheal_brand_new_failure"
    (repo / f"brief_hooks_{slug}.md").write_text("# x\n")
    monkeypatch.setattr(selfheal, "_selfheal_provenance_valid", lambda *a, **k: True)
    cfg = {"autowork": {"selfheal_auto_promote": True}, "selfheal_auto_promote": True}
    out = autowork_daemon._auto_promote_brief_eligible(
        state, slug, time.time(), config=cfg, repo_root=repo)
    assert out is True


# ---- persistence at exhaustion -------------------------------------------

def test_exhaustion_writes_persistent_skip_marker(tmp_path, monkeypatch):
    """When a blocked task exhausts its retry budget, a persistent skip marker
    is written under control/autowork/selfheal_skip/ (NOT in blocked/, so the
    harvester's blocked/ eviction cannot clear it)."""
    from harness import autowork_daemon
    state = _mk_state(tmp_path)
    blocked = state / "tasks" / "blocked"
    tid = "md_d_01_extract_class_interface"
    (blocked / f"{tid}.json").write_text(json.dumps({"task_id": tid}))
    (blocked / f"{tid}.retry.json").write_text(json.dumps(
        {"attempts": 3, "ts": 0, "last_outcome": "auto_commit_failed"}))
    # Neutralize the escalation side-effect so the test stays hermetic.
    monkeypatch.setattr(autowork_daemon, "_escalate_to_autobrief", lambda *a, **k: None)
    autowork_daemon._retry_blocked_tasks(state, {}, max_attempts=3)
    marker = state / "control" / "autowork" / "selfheal_skip" / tid
    assert marker.exists(), "exhaustion must write a persistent selfheal_skip marker"
