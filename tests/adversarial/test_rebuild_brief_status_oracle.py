"""Operator-authored per-unit oracle for the brief_status module's three public
units, named ``test_<unit>_<behaviour>`` so the rebuild engine's
``pytest -k <unit>`` selects exactly one unit's tests (the existing
tests/test_brief_status.py names tests by behaviour, which per-unit -k scoping
can't isolate -> whole-file fallback -> cascade across the multi-unit module).

Used as the verification oracle for the JanusMask->JR leaf-cluster self-rebuild
(session #39 P2). Each unit's tests exercise ONLY that unit; eligibility/backlog
call their already-reconstructed intra-module dependency compute_brief_status,
which the dep-ordered loop reconstructs first. The tmp_path fixtures make the
file portable (it carries no JanusMask state), so it runs identically in JR."""

import json

from harness.brief_status import (
    compute_autowork_backlog,
    compute_autowork_eligibility,
    compute_brief_status,
)


def _mk(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    state = tmp_path / "state"
    state.mkdir()
    return repo, state


def _allowlist(state, *slugs):
    p = state / "control" / "autowork" / "auto_promote.allowlist"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(slugs) + "\n", encoding="utf-8")


# ----- compute_brief_status -----
def test_compute_brief_status_reports_unplanned_brief(tmp_path):
    repo, state = _mk(tmp_path)
    (repo / "brief_hooks_alpha.md").write_text("content")
    rows = compute_brief_status(repo, state)
    assert len(rows) == 1
    assert rows[0]["slug"] == "alpha"
    assert rows[0]["state"] == "unplanned"
    assert rows[0]["has_plan"] is False


def test_compute_brief_status_reports_complete_when_all_accepted(tmp_path):
    repo, state = _mk(tmp_path)
    (repo / "brief_hooks_beta.md").write_text("content")
    (repo / "plan_hooks_beta.json").write_text(json.dumps({"tasks": [{"task_id": "t1"}]}))
    (state / "impl_progress.jsonl").write_text(
        json.dumps({"phase": "accepted", "event": "auto_commit", "task_id": "t1",
                    "commit_sha": "abc", "ts": 1}) + "\n"
    )
    rows = compute_brief_status(repo, state)
    assert rows[0]["state"] == "complete"
    assert rows[0]["remaining"] == []


# ----- compute_autowork_eligibility -----
def test_compute_autowork_eligibility_eligible_when_allowlisted(tmp_path):
    repo, state = _mk(tmp_path)
    (repo / "brief_hooks_gamma.md").write_text("content")
    _allowlist(state, "gamma")
    out = compute_autowork_eligibility(repo, state)  # now=time.time(), fresh brief
    assert "gamma" in out["eligible"]
    assert out["eligible_count"] == 1
    assert out["allowlist_present"] is True


def test_compute_autowork_eligibility_blocked_stale_past_max_age(tmp_path):
    repo, state = _mk(tmp_path)
    (repo / "brief_hooks_delta.md").write_text("content")
    _allowlist(state, "delta")
    # max_age_sec=0 forces now - mtime > max_age -> stale, even for a fresh brief.
    out = compute_autowork_eligibility(repo, state, max_age_sec=0)
    assert "delta" not in out["eligible"]
    assert {"slug": "delta", "reason": "stale"} in out["blocked"]


def test_compute_autowork_eligibility_blocked_when_allowlist_missing(tmp_path):
    repo, state = _mk(tmp_path)
    (repo / "brief_hooks_epsilon.md").write_text("content")  # no allowlist file
    out = compute_autowork_eligibility(repo, state)
    assert out["allowlist_present"] is False
    assert {"slug": "epsilon", "reason": "allowlist_missing"} in out["blocked"]


# ----- compute_autowork_backlog -----
def test_compute_autowork_backlog_eligible_unplanned_has_work(tmp_path):
    repo, state = _mk(tmp_path)
    (repo / "brief_hooks_zeta.md").write_text("content")  # unplanned -> has work
    _allowlist(state, "zeta")
    out = compute_autowork_backlog(repo, state)
    assert "zeta" in out["eligible_with_work"]
    assert any(d["slug"] == "zeta" and d["has_unfinished_work"] for d in out["detail"])
