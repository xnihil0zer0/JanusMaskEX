"""Adversarial pin for META-PLAN-OUTBOX-FALLBACK.

Closes the gap discovered in META-PLAN-PERMISSION-MODE (537d63d): claude's
``-p`` mode silently drops ``--settings`` so the post_tool hook never fires
to promote ``outbox/{plan_draft,reconciliation}.json`` into the canonical
paths the planner reads. Three sites get an in-process fallback:

    1. ``harness/planner/blind_draft.py::collect_agent_draft``  (R1 plan_draft)
    2. ``harness/planner/reconciliation.py::collect_reconciliation_response``
       (R1 reconcile, defined inline as closure)
    3. ``harness/planner/adversarial_review.py::run_adversarial_review``
       (R2 reviewer poll loop)

All three use the shared resolver
``harness.planner.blind_draft._resolve_outbox_artifact`` which globs
``<agent_dir>/workdirs/<agent>/<agent>-r<round>-*/outbox/<filename>`` and
returns the most-recently-modified match (tie-breaker is mtime, NOT lexical).

This file pins:

* canonical paths win when present (no fallback fires)
* outbox fallback resolves a single plan_draft.json correctly
* zero outboxes preserve the existing crashed/timeout semantics
* multiple outboxes → newest mtime wins
* malformed JSON / schema-violating outbox content → status="invalid"
* wrong-round outbox dirs are filtered out by the round-N glob
* other-agent outbox dirs are filtered out by the agent prefix
* static-source pins for blind_draft + reconciliation + adversarial_review
"""
from __future__ import annotations

import inspect
import json
import os
import pathlib
import re
import sys
import time
from typing import Any, Dict

import pytest

_REPO = pathlib.Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from harness.planner import (  # noqa: E402
    adversarial_review,
    blind_draft,
    reconciliation,
)
from harness.planner.blind_draft import (  # noqa: E402
    _resolve_outbox_artifact,
    collect_agent_draft,
)
from harness.paths import agent_workroot  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_agent_workroot(tmp_path, monkeypatch):
    """AGENT-ISOLATION §3.7: outboxes were relocated OUTSIDE the repo. Pin the
    shared workroot to tmp_path so ``agent_workroot()`` resolves there and the
    resolver finds the outboxes these tests stage. With this set,
    ``agent_workroot()/<agent>`` == ``tmp_path/<agent>`` == the ``agent_dir``
    the tests build, so the (now-ignored) ``agent_dir`` arg still lines up."""
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path))


def _minimal_valid_task(task_id: str = "T1") -> Dict[str, Any]:
    """Return a single task that passes ``plan_validator.validate_plan``."""
    return {
        "task_id": task_id,
        "title": "minimal test task",
        "meta_task_type": "docs_writing",
        "priority": "low",
        "dependencies": [],
        "files_touched": ["docs/x.md"],
        "acceptance_criteria": ["x"],
        "spec_author": None,
        "estimated_complexity": "low",
        "verification_command": "echo ok",
        "spec": {
            "objective": "test",
            "functional_requirements": ["r1"],
            "interfaces": "i",
            "edge_cases": ["e1", "e2"],
            "non_goals": ["integration_tests"],
            "implementation_notes": "n",
        },
        "test_spec": {
            "unit_tests": [{"name": "t1"}, {"name": "t2"}],
            "integration_tests": [],
            "property_tests": [],
            "regression_tests": [{"name": "reg_e1"}, {"name": "reg_e2"}],
            "minimum_test_count": 2,
            "test_data_requirements": "none",
        },
        "token_budget_ratio": {
            "implementation_tokens": 100,
            "test_tokens": 200,
            "note": "standard",
        },
        "attribution_metadata": {
            "proposed_by": "test",
            "reconciled": False,
            "diff_resolution": None,
        },
    }


def _write_outbox_plan(
    agent_dir: pathlib.Path,
    agent: str,
    uuid8: str,
    plan: Dict[str, Any],
    *,
    round_number: int = 1,
    filename: str = "plan_draft.json",
) -> pathlib.Path:
    slug = f"{agent}-r{round_number}-notask-{uuid8}"
    # AGENT-ISOLATION §3.7: outboxes live under the shared workroot, not
    # agent_dir/workdirs (the _isolate_agent_workroot fixture pins it to tmp).
    outbox = agent_workroot() / agent / slug / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    target = outbox / filename
    target.write_text(json.dumps(plan), encoding="utf-8")
    return target


# --------------------------------------------------------------------- BlindDraft


class TestCollectAgentDraft:
    def test_canonical_per_agent_path_wins(self, tmp_path):
        agent_dir = tmp_path / "claude"
        canonical = agent_dir / "planning" / "sessions" / "claude_draft.json"
        canonical.parent.mkdir(parents=True)
        plan = {"tasks": [_minimal_valid_task("CANONICAL")]}
        canonical.write_text(json.dumps(plan), encoding="utf-8")
        # Also place a stale outbox; canonical must win.
        _write_outbox_plan(
            agent_dir, "claude", "deadbeef",
            {"tasks": [_minimal_valid_task("OUTBOX")]}
        )
        draft, status = collect_agent_draft(
            "claude", agent_dir, tmp_path / "state",
            elapsed=1.0, timeout=1800,
        )
        assert status == "ok"
        assert draft["tasks"][0]["task_id"] == "CANONICAL"

    def test_top_level_state_dir_canonical_fallback_works(self, tmp_path):
        agent_dir = tmp_path / "claude"
        agent_dir.mkdir()
        state_canonical = (
            tmp_path / "state" / "planning" / "sessions" / "claude_draft.json"
        )
        state_canonical.parent.mkdir(parents=True)
        plan = {"tasks": [_minimal_valid_task("STATE_CANONICAL")]}
        state_canonical.write_text(json.dumps(plan), encoding="utf-8")
        draft, status = collect_agent_draft(
            "claude", agent_dir, tmp_path / "state",
            elapsed=1.0, timeout=1800,
        )
        assert status == "ok"
        assert draft["tasks"][0]["task_id"] == "STATE_CANONICAL"

    def test_outbox_fallback_resolves_when_canonicals_missing(self, tmp_path):
        agent_dir = tmp_path / "claude"
        agent_dir.mkdir()
        plan = {"tasks": [_minimal_valid_task("OUTBOX_RECOVERED")]}
        _write_outbox_plan(agent_dir, "claude", "deadbeef", plan)
        draft, status = collect_agent_draft(
            "claude", agent_dir, tmp_path / "state",
            elapsed=1.0, timeout=1800,
        )
        assert status == "ok"
        assert draft["tasks"][0]["task_id"] == "OUTBOX_RECOVERED"

    def test_zero_outboxes_returns_crashed(self, tmp_path):
        agent_dir = tmp_path / "claude"
        agent_dir.mkdir()
        draft, status = collect_agent_draft(
            "claude", agent_dir, tmp_path / "state",
            elapsed=1.0, timeout=1800,
        )
        assert draft is None
        assert status == "crashed"

    def test_zero_outboxes_with_elapsed_at_timeout_returns_timeout(self, tmp_path):
        agent_dir = tmp_path / "claude"
        agent_dir.mkdir()
        draft, status = collect_agent_draft(
            "claude", agent_dir, tmp_path / "state",
            elapsed=1799.5, timeout=1800,
        )
        assert draft is None
        assert status == "timeout"

    def test_multiple_outboxes_newest_mtime_wins(self, tmp_path):
        agent_dir = tmp_path / "claude"
        agent_dir.mkdir()
        older = _write_outbox_plan(
            agent_dir, "claude", "aaaaaaaa",
            {"tasks": [_minimal_valid_task("OLD")]}
        )
        # Force older mtime (~1 hour ago).
        os.utime(older, (time.time() - 3600, time.time() - 3600))
        newer = _write_outbox_plan(
            agent_dir, "claude", "bbbbbbbb",
            {"tasks": [_minimal_valid_task("NEW")]}
        )
        os.utime(newer, (time.time(), time.time()))
        draft, status = collect_agent_draft(
            "claude", agent_dir, tmp_path / "state",
            elapsed=1.0, timeout=1800,
        )
        assert status == "ok"
        assert draft["tasks"][0]["task_id"] == "NEW"

    def test_outbox_malformed_json_returns_invalid(self, tmp_path):
        agent_dir = tmp_path / "claude"
        agent_dir.mkdir()
        slug = "claude-r1-notask-deadbeef"
        outbox = agent_workroot() / "claude" / slug / "outbox"
        outbox.mkdir(parents=True)
        (outbox / "plan_draft.json").write_text("{ this is not json")
        draft, status = collect_agent_draft(
            "claude", agent_dir, tmp_path / "state",
            elapsed=1.0, timeout=1800,
        )
        assert draft is None
        assert status == "invalid"

    def test_outbox_schema_violation_returns_invalid(self, tmp_path):
        agent_dir = tmp_path / "claude"
        agent_dir.mkdir()
        # Valid JSON but plan_validator will reject (missing required fields)
        _write_outbox_plan(
            agent_dir, "claude", "deadbeef",
            {"tasks": [{"task_id": "INCOMPLETE"}]},
        )
        draft, status = collect_agent_draft(
            "claude", agent_dir, tmp_path / "state",
            elapsed=1.0, timeout=1800,
        )
        assert draft is None
        assert status == "invalid"

    def test_wrong_round_outbox_ignored(self, tmp_path):
        agent_dir = tmp_path / "claude"
        agent_dir.mkdir()
        # r2 dir present, no r1 dir → should be ignored, falls through to crashed
        _write_outbox_plan(
            agent_dir, "claude", "deadbeef",
            {"tasks": [_minimal_valid_task("R2")]},
            round_number=2,
        )
        draft, status = collect_agent_draft(
            "claude", agent_dir, tmp_path / "state",
            elapsed=1.0, timeout=1800,
        )
        assert draft is None
        assert status == "crashed"

    def test_other_agent_outbox_ignored(self, tmp_path):
        agent_dir = tmp_path / "claude"
        agent_dir.mkdir()
        # gemini-prefixed slug under claude's agent_dir → must NOT be picked up
        slug = "gemini-r1-notask-deadbeef"
        outbox = agent_workroot() / "claude" / slug / "outbox"
        outbox.mkdir(parents=True)
        plan = {"tasks": [_minimal_valid_task("WRONG_AGENT")]}
        (outbox / "plan_draft.json").write_text(json.dumps(plan))
        draft, status = collect_agent_draft(
            "claude", agent_dir, tmp_path / "state",
            elapsed=1.0, timeout=1800,
        )
        assert draft is None
        assert status == "crashed"


# ---------------------------------------------------------------- ResolveOutbox


class TestResolveOutboxArtifact:
    def test_returns_none_when_workdirs_root_missing(self, tmp_path):
        agent_dir = tmp_path / "claude"
        agent_dir.mkdir()
        assert _resolve_outbox_artifact(agent_dir, "claude", "plan_draft.json") is None

    def test_filename_filter_distinguishes_plan_from_reconciliation(self, tmp_path):
        agent_dir = tmp_path / "claude"
        agent_dir.mkdir()
        slug = "claude-r1-notask-deadbeef"
        outbox = agent_workroot() / "claude" / slug / "outbox"
        outbox.mkdir(parents=True)
        (outbox / "reconciliation.json").write_text("{}")
        # Looking for plan_draft.json — must NOT match reconciliation.json
        assert (
            _resolve_outbox_artifact(agent_dir, "claude", "plan_draft.json")
            is None
        )
        assert (
            _resolve_outbox_artifact(agent_dir, "claude", "reconciliation.json")
            is not None
        )


# ---------------------------------------------------------------- StaticSourcePin


class TestStaticSourcePins:
    def test_blind_draft_has_outbox_glob_in_collect_agent_draft(self):
        src = inspect.getsource(blind_draft)
        # The resolver must exist as a module-level symbol.
        assert "_resolve_outbox_artifact" in src
        # collect_agent_draft must be promoted to module level (def at column 0).
        assert "\ndef collect_agent_draft(" in src, (
            "collect_agent_draft must be module-level for testability"
        )
        # Glob must filter by agent prefix + round + outbox folder + filename.
        resolver_src = inspect.getsource(blind_draft._resolve_outbox_artifact)
        assert "workdirs" in resolver_src
        assert "outbox" in resolver_src
        assert "round_number" in resolver_src
        assert "max(candidates" in resolver_src and "st_mtime" in resolver_src, (
            "tie-breaker must be mtime, not lexical"
        )

    def test_collect_agent_draft_canonical_first_outbox_last(self):
        src = inspect.getsource(blind_draft.collect_agent_draft)
        # Canonical (per-agent) is checked before top-level fallback before outbox.
        # Quote style is incidental — past whole-file submissions (R01H3) reformatted
        # the source's literals from double to single quotes via AST normalization.
        m_per_agent = re.search(r"""agent_dir\s*/\s*['"]planning['"]""", src)
        m_top_level = re.search(r"""state_dir\s*/\s*['"]planning['"]""", src)
        m_outbox = re.search(r"_resolve_outbox_artifact", src)
        assert m_per_agent is not None, "missing agent_dir / 'planning' pin"
        assert m_top_level is not None, "missing state_dir / 'planning' pin"
        assert m_outbox is not None, "missing _resolve_outbox_artifact pin"
        i_per_agent = m_per_agent.start()
        i_top_level = m_top_level.start()
        i_outbox = m_outbox.start()
        assert i_per_agent < i_top_level < i_outbox, (
            f"search order broken: per_agent={i_per_agent}, "
            f"top_level={i_top_level}, outbox={i_outbox}"
        )

    def test_reconciliation_has_outbox_fallback(self):
        src = inspect.getsource(reconciliation)
        # The fallback uses the shared resolver.
        assert "_resolve_outbox_artifact" in src
        # Must look up reconciliation.json (not plan_draft.json).
        recon_src = inspect.getsource(reconciliation.run_reconciliation)
        assert "reconciliation.json" in recon_src

    def test_reconciliation_downgrades_phantom_defend(self):
        """When an agent defends an item it didn't propose (c_task is
        None), downgrade to concede. Without this, an empty/invalid
        claude_draft combined with claude blanket-defending all
        gemini_only diff items routes every item through the tiebreaker
        and into unresolved_policy=flag_for_human, producing an empty
        merged plan."""
        src = inspect.getsource(reconciliation.run_reconciliation)
        # Must contain a downgrade for c_stance when c_task is None
        # AND symmetrically for g_stance / g_task. Quote-agnostic because
        # R01H4 whole-file submission AST-normalized the source to single quotes.
        assert (
            re.search(r"""c_stance\s*==\s*['"]defend['"]""", src) is not None
            and "c_task is None" in src
        ), "c_stance phantom-defend downgrade missing"
        assert (
            re.search(r"""g_stance\s*==\s*['"]defend['"]""", src) is not None
            and "g_task is None" in src
        ), "g_stance phantom-defend downgrade missing"

    def test_adversarial_review_has_outbox_fallback(self):
        src = inspect.getsource(adversarial_review.run_adversarial_review)
        # Reviewer fallback uses proc._work_dir for THIS spawn only.
        # It must NOT *call* _resolve_outbox_artifact — that resolver's
        # glob would falsely match R1 reconciliation outboxes (which
        # share the reconciliation.json filename) and corrupt the
        # critique with R1 stance data. Comments mentioning the symbol
        # are fine; only call sites are forbidden.
        assert "_work_dir" in src
        import re
        call_pattern = re.compile(r"\b_resolve_outbox_artifact\s*\(")
        assert not call_pattern.search(src), (
            "R2 reviewer must NOT call _resolve_outbox_artifact — its "
            "glob falsely matches R1 reconciliation outboxes"
        )
        assert "reconciliation.json" in src

    def test_adversarial_review_kill_agent_signature(self):
        """Pin the orchestrator.kill_agent signature usage in the finally
        block. The function requires (proc, agent, reason='handoff'); a
        bare ``kill_agent(proc)`` raises TypeError mid-cleanup."""
        src = inspect.getsource(adversarial_review.run_adversarial_review)
        import re
        # Find every kill_agent call site
        calls = re.findall(r"kill_agent\([^)]*\)", src)
        assert calls, "expected at least one kill_agent call in adversarial_review"
        for call in calls:
            # Must have a comma → at least 2 positional/keyword args
            assert "," in call, f"kill_agent missing required `agent` arg: {call!r}"

    def test_no_module_uses_lexical_glob_tiebreaker(self):
        """A regression where someone replaces ``max(.., key=mtime)`` with
        ``sorted(...)[0]`` or ``next(iter(glob))`` would silently lose the
        newest-wins contract. Catch that."""
        resolver_src = inspect.getsource(blind_draft._resolve_outbox_artifact)
        # The function must NOT use sorted() or [-1]/[0] indexing on the glob
        # (those are lexical, not mtime-based).
        assert "sorted(" not in resolver_src or "key=" in resolver_src, (
            "if sorted() is used, it must specify key=...st_mtime"
        )
