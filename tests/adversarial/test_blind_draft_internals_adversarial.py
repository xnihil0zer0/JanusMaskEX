"""Adversarial pins — blind_draft internals (Plan 04, CASE-G/H/I).

CASE-G: _resolve_outbox_artifact stale-epoch + missing-root edges (extends the
        sibling test_planning_outbox_fallback_adversarial.py).
CASE-H: collect_agent_draft status ladder (timeout/crashed/suspect_hallucination
        /invalid/ok).
CASE-I: _PerAgentConfig stack-inspection state_dir trick — agent-specific dir
        only inside a frame literally named run_agent_phase/spawn_agent whose
        local `agent` is set; else default. Brittle coupling pinned per the gap.
"""
from __future__ import annotations

import json
import os
import pathlib
import sys
import time

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.planner.blind_draft import (  # noqa: E402
    _PerAgentConfig,
    _resolve_outbox_artifact,
    collect_agent_draft,
)
from harness.paths import agent_workroot  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "agentwork"))


def _valid_task(task_id="T1"):
    return {
        "task_id": task_id, "title": "t", "meta_task_type": "docs_writing",
        "priority": "low", "dependencies": [], "files_touched": ["docs/x.md"],
        "acceptance_criteria": ["x"], "spec_author": None,
        "estimated_complexity": "low", "verification_command": "echo ok",
        "spec": {"objective": "o", "functional_requirements": ["r1"],
                 "interfaces": "i", "edge_cases": ["e1", "e2"],
                 "non_goals": ["integration_tests"], "implementation_notes": "n"},
        "test_spec": {"unit_tests": [{"name": "u1"}, {"name": "u2"}],
                      "integration_tests": [], "property_tests": [],
                      "regression_tests": [{"name": "r1"}, {"name": "r2"}],
                      "minimum_test_count": 2, "test_data_requirements": "none"},
        "token_budget_ratio": {"implementation_tokens": 100, "test_tokens": 200, "note": "n"},
        "attribution_metadata": {"proposed_by": "test", "reconciled": False, "diff_resolution": None},
    }


def _write_outbox(agent, plan, *, uuid8="deadbeef", round_no=1, filename="plan_draft.json"):
    slug = f"{agent}-r{round_no}-notask-{uuid8}"
    outbox = agent_workroot() / agent / slug / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    tgt = outbox / filename
    tgt.write_text(json.dumps(plan) if isinstance(plan, dict) else plan)
    return tgt


# ------------------------------------------------------------------- CASE-G


class TestResolveOutboxEdges:
    def test_missing_root_returns_none(self, tmp_path):
        # agent_workroot()/<agent> does not exist at all.
        assert _resolve_outbox_artifact(tmp_path / "claude", "claude", "plan_draft.json") is None

    def test_stale_epoch_floor_filters_all_candidates(self, tmp_path):
        tgt = _write_outbox("claude", {"tasks": []})
        # Set the candidate mtime to the past, then require an epoch above it.
        past = time.time() - 3600
        os.utime(tgt, (past, past))
        result = _resolve_outbox_artifact(
            tmp_path / "claude", "claude", "plan_draft.json",
            spawn_start_epoch=time.time(),  # floor above the stale mtime
        )
        assert result is None, "stale-outbox guard should reject candidates below epoch floor"

    def test_epoch_at_or_below_mtime_keeps_candidate(self, tmp_path):
        tgt = _write_outbox("claude", {"tasks": []})
        now = time.time()
        os.utime(tgt, (now, now))
        result = _resolve_outbox_artifact(
            tmp_path / "claude", "claude", "plan_draft.json",
            spawn_start_epoch=now - 10,
        )
        assert result == tgt

    def test_wrong_round_glob_filtered(self, tmp_path):
        _write_outbox("claude", {"tasks": []}, round_no=2)
        assert _resolve_outbox_artifact(
            tmp_path / "claude", "claude", "plan_draft.json", round_number=1) is None

    def test_other_agent_dir_not_matched(self, tmp_path):
        # gemini outbox while resolving claude -> claude root has no such dir.
        _write_outbox("gemini", {"tasks": []})
        assert _resolve_outbox_artifact(
            tmp_path / "claude", "claude", "plan_draft.json") is None


# ------------------------------------------------------------------- CASE-H


class TestCollectAgentDraftStatusLadder:
    def test_timeout_when_no_draft_and_elapsed_near_timeout(self, tmp_path):
        d, s = collect_agent_draft("claude", tmp_path / "claude", tmp_path / "st",
                                   elapsed=1799.5, timeout=1800)
        assert (d, s) == (None, "timeout")

    def test_crashed_when_no_draft_and_small_elapsed(self, tmp_path):
        d, s = collect_agent_draft("claude", tmp_path / "claude", tmp_path / "st",
                                   elapsed=1.0, timeout=1800)
        assert (d, s) == (None, "crashed")

    def test_suspect_hallucination_when_latency_under_threshold(self, tmp_path):
        tgt = _write_outbox("claude", {"tasks": [_valid_task()]})
        now = time.time()
        os.utime(tgt, (now, now))
        # spawn_start_epoch just before mtime => latency < 10s default threshold.
        d, s = collect_agent_draft("claude", tmp_path / "claude", tmp_path / "st",
                                   elapsed=1.0, timeout=1800, spawn_start_epoch=now - 1.0)
        assert (d, s) == (None, "suspect_hallucination")

    def test_invalid_on_malformed_json(self, tmp_path):
        _write_outbox("claude", "{ not json")
        d, s = collect_agent_draft("claude", tmp_path / "claude", tmp_path / "st",
                                   elapsed=1.0, timeout=1800)
        assert (d, s) == (None, "invalid")

    def test_invalid_on_schema_violation(self, tmp_path):
        _write_outbox("claude", {"tasks": [{"task_id": "X"}]})
        d, s = collect_agent_draft("claude", tmp_path / "claude", tmp_path / "st",
                                   elapsed=1.0, timeout=1800)
        assert (d, s) == (None, "invalid")

    def test_ok_on_valid_draft_with_sufficient_latency(self, tmp_path):
        tgt = _write_outbox("claude", {"tasks": [_valid_task()]})
        now = time.time()
        os.utime(tgt, (now, now))
        d, s = collect_agent_draft("claude", tmp_path / "claude", tmp_path / "st",
                                   elapsed=1.0, timeout=1800, spawn_start_epoch=now - 60)
        assert s == "ok" and d["tasks"][0]["task_id"] == "T1"


# ------------------------------------------------------------------- CASE-I


class TestPerAgentConfigFrameTrick:
    def test_returns_default_outside_known_frame(self, tmp_path):
        cfg = _PerAgentConfig({"state_dir": "DEFAULT"}, tmp_path / "c", tmp_path / "g")
        # Called from an unrelated frame -> base default.
        assert cfg.get("state_dir") == "DEFAULT"

    def test_returns_gemini_dir_inside_spawn_agent_frame(self, tmp_path):
        cfg = _PerAgentConfig({"state_dir": "DEFAULT"}, tmp_path / "c", tmp_path / "g")

        def spawn_agent():  # noqa: D401 — name is load-bearing for the stack trick
            agent = "gemini"  # noqa: F841 — read via inspect.stack f_locals
            return cfg.get("state_dir")

        assert spawn_agent() == str(tmp_path / "g")

    def test_returns_claude_dir_inside_run_agent_phase_frame(self, tmp_path):
        cfg = _PerAgentConfig({"state_dir": "DEFAULT"}, tmp_path / "c", tmp_path / "g")

        def run_agent_phase():
            agent = "claude"  # noqa: F841
            return cfg["state_dir"]  # __getitem__ delegates to get

        assert run_agent_phase() == str(tmp_path / "c")

    def test_brittle_when_frame_renamed(self, tmp_path):
        """GAP: the trick is coupled to the literal function names. A frame with
        a DIFFERENT name (a refactor/inline) silently returns the default
        state_dir — planning sessions would then collide. Pin the failure mode."""
        cfg = _PerAgentConfig({"state_dir": "DEFAULT"}, tmp_path / "c", tmp_path / "g")

        def spawn_agent_renamed():  # NOT in ('run_agent_phase','spawn_agent')
            agent = "gemini"  # noqa: F841
            return cfg.get("state_dir")

        assert spawn_agent_renamed() == "DEFAULT", (
            "rename no longer falls back to default — trick semantics changed"
        )

    def test_non_state_dir_keys_pass_through(self, tmp_path):
        cfg = _PerAgentConfig({"state_dir": "D", "other": 7}, tmp_path / "c", tmp_path / "g")
        assert cfg["other"] == 7
        assert cfg.get("missing", "fb") == "fb"
