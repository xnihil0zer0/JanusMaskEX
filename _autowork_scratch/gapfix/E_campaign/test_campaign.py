"""Hermetic oracle for ngv2.campaign — fully injected seams, no network/clone/hunt."""
from __future__ import annotations

import os
import tempfile

import pytest

from ngv2 import campaign


# --------------------------------------------------------------------------
# select_targets (pure)
# --------------------------------------------------------------------------
def test_select_excludes_hunted_and_caps_at_n():
    ranked = ["a/1", "b/2", "c/3", "d/4"]
    hunted = {"b/2"}
    assert campaign.select_targets(ranked, hunted, 2) == ["a/1", "c/3"]


def test_select_dedups_and_preserves_rank_order():
    ranked = ["a/1", "a/1", "b/2"]
    assert campaign.select_targets(ranked, set(), 5) == ["a/1", "b/2"]


def test_select_zero_or_negative_n_selects_nothing():
    assert campaign.select_targets(["a/1"], set(), 0) == []
    assert campaign.select_targets(["a/1"], set(), -1) == []


# --------------------------------------------------------------------------
# ledger
# --------------------------------------------------------------------------
def test_ledger_record_and_load_roundtrip():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ledger.json")
        assert campaign.load_hunted(path) == set()
        campaign.record_hunted(path, "a/1", "completed", "2026-06-14T00:00:00Z")
        campaign.record_hunted(path, "b/2", "error", "2026-06-14T01:00:00Z")
        assert campaign.load_hunted(path) == {"a/1", "b/2"}


def test_ledger_increments_count_on_rehunt():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ledger.json")
        campaign.record_hunted(path, "a/1", "completed", "2026-06-14T00:00:00Z")
        entry = campaign.record_hunted(path, "a/1", "completed", "2026-06-15T00:00:00Z")
        assert entry["count"] == 2


def test_ledger_cooldown_makes_stale_entries_rehuntable():
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "ledger.json")
        campaign.record_hunted(path, "old/1", "completed", "2026-06-01T00:00:00Z")
        campaign.record_hunted(path, "new/2", "completed", "2026-06-14T00:00:00Z")
        # 24h cooldown, "now" = 2026-06-14T12:00:00Z -> old/1 is stale, droppable
        excluded = campaign.load_hunted(
            path, now="2026-06-14T12:00:00Z", cooldown_hours=24.0
        )
        assert "old/1" not in excluded
        assert "new/2" in excluded


# --------------------------------------------------------------------------
# run_campaign (full seam injection)
# --------------------------------------------------------------------------
class _Spy:
    """Records seam invocations for a hermetic campaign run."""

    def __init__(self, eligible, hunted, *, fail_repo=None, ledger=None):
        self.eligible = list(eligible)
        self.hunted = set(hunted)
        self.fail_repo = fail_repo
        self.ledger = ledger if ledger is not None else {}
        self.refresh_calls = 0
        self.cloned = []
        self.hunted_calls = []
        self.recorded = []

    # seams
    def refresh(self):
        self.refresh_calls += 1
        return {"short_circuited": False}

    def list_eligible(self):
        return list(self.eligible)

    def rank(self, eligible):
        # deterministic: sort descending so order != input order
        return sorted(eligible, reverse=True)

    def load_hunted(self):
        return set(self.hunted) | set(self.ledger.keys())

    def record_hunted(self, repo, outcome, now):
        self.recorded.append((repo, outcome))
        self.ledger[repo] = {"last": now, "outcome": outcome}

    def clone(self, repo):
        if repo == self.fail_repo:
            raise RuntimeError("clone boom for %s" % repo)
        self.cloned.append(repo)
        return {"repo_root": "/tmp/%s" % repo}

    def hunt(self, repo, clone_obj):
        self.hunted_calls.append(repo)
        return {"final_step": {"phase": "awaiting_submission"}}

    def now(self):
        return "2026-06-14T00:00:00Z"

    def seams(self, n):
        return dict(
            refresh=self.refresh,
            list_eligible=self.list_eligible,
            rank=self.rank,
            load_hunted=self.load_hunted,
            record_hunted=self.record_hunted,
            clone=self.clone,
            hunt=self.hunt,
            n=n,
            now=self.now,
        )


def test_run_campaign_full_flow():
    spy = _Spy(eligible=["a/1", "b/2", "c/3", "d/4"], hunted={"d/4"})
    summary = campaign.run_campaign(**spy.seams(n=2))

    # refresh invoked exactly once, best-effort
    assert spy.refresh_calls == 1
    assert summary["refreshed"] is True
    assert summary["refresh_error"] is None

    # ranked desc => ["d/4","c/3","b/2","a/1"]; d/4 hunted-excluded; top 2 fresh
    assert summary["selected"] == ["c/3", "b/2"]

    # clone + hunt called once per selected target
    assert spy.cloned == ["c/3", "b/2"]
    assert spy.hunted_calls == ["c/3", "b/2"]

    # ledger records each hunted target with derived outcome
    assert spy.recorded == [
        ("c/3", "awaiting_submission"),
        ("b/2", "awaiting_submission"),
    ]
    assert all(r["error"] is None for r in summary["results"])


def test_run_campaign_rotation_second_run_picks_different_targets():
    shared_ledger = {}
    spy1 = _Spy(eligible=["a/1", "b/2", "c/3", "d/4"], hunted=set(), ledger=shared_ledger)
    s1 = campaign.run_campaign(**spy1.seams(n=2))
    assert s1["selected"] == ["d/4", "c/3"]  # ranked desc, top 2

    # second run reuses the UPDATED ledger -> rotates onto the next 2
    spy2 = _Spy(eligible=["a/1", "b/2", "c/3", "d/4"], hunted=set(), ledger=shared_ledger)
    s2 = campaign.run_campaign(**spy2.seams(n=2))
    assert s2["selected"] == ["b/2", "a/1"]
    assert set(s1["selected"]).isdisjoint(s2["selected"])


def test_run_campaign_one_target_failure_does_not_abort_others():
    spy = _Spy(eligible=["a/1", "b/2", "c/3"], hunted=set(), fail_repo="c/3")
    summary = campaign.run_campaign(**spy.seams(n=3))
    # ranked desc => c/3, b/2, a/1 ; c/3 clone raises but others proceed
    assert spy.hunted_calls == ["b/2", "a/1"]
    by_repo = {r["repo"]: r for r in summary["results"]}
    assert by_repo["c/3"]["outcome"] == "error"
    assert by_repo["c/3"]["error"] is not None
    assert by_repo["b/2"]["outcome"] == "awaiting_submission"
    # the failed target is still recorded in the ledger (so rotation advances)
    assert ("c/3", "error") in spy.recorded


def test_run_campaign_refresh_failure_is_not_fatal():
    spy = _Spy(eligible=["a/1"], hunted=set())

    def _boom():
        raise RuntimeError("network down")

    seams = spy.seams(n=1)
    seams["refresh"] = _boom
    summary = campaign.run_campaign(**seams)
    assert summary["refreshed"] is False
    assert summary["refresh_error"] is not None
    # the hunt still proceeds
    assert spy.hunted_calls == ["a/1"]
