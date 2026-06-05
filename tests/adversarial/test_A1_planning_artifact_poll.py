"""A1 — poll_for_submission must recognize the planning/reconciliation outbox
artifact (plan_draft.json / reconciliation.json), not only synthesis'
outbox/submission.py.

Blocker-1 root cause: in planning/reconciliation mode the agent submits a JSON
artifact, but poll_for_submission only watched for the synthesis submission, so
claude-proper was reported "died without submitting" -> run_both_agents fired
the agy ``claude_fallback`` (Antigravity / Google credits) needlessly even
though claude-proper DID write a valid plan_draft.json. These oracles pin that:

  A1a — JANUSMASK_MODE=planning + outbox/plan_draft.json present -> poll returns
        the artifact text (truthy), so run_both_agents does NOT fire the fallback.
        Returned even under a DENY registry: the planning artifact is JSON, not
        Python code, so it must BYPASS the submit_code interceptor (which would
        AST-deny it) — it was already gate-validated on the agent's Write.
  A1b — JANUSMASK_MODE=reconciliation + outbox/reconciliation.json present ->
        poll returns the artifact text.
  A1c — synthesis mode must NOT treat a stray plan_draft.json as a submission
        (no over-broad detection); poll returns None.

No agy/claude spawned; FakePopen never execs.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

import harness.orchestrator as orch


class _FakePopen:
    def __init__(self, work_dir, poll_seq=None):
        self._work_dir = work_dir
        self.pid = 777
        self.returncode = None
        self._poll_seq = list(poll_seq) if poll_seq else None

    def poll(self):
        if self._poll_seq:
            rc = self._poll_seq.pop(0)
            if rc is not None:
                self.returncode = rc
            return rc
        return None  # alive


class _FakeRegistry:
    def __init__(self, deny=False):
        self.deny = deny
        self.calls = []

    def pre_tool_use(self, agent, tool, payload):
        self.calls.append(("pre", agent, tool))
        return {"decision": "deny", "reason": "blocked"} if self.deny else None

    def post_tool_use(self, agent, tool, payload):
        self.calls.append(("post", agent, tool))


@pytest.fixture
def state(tmp_path, monkeypatch):
    sd = tmp_path / "state"
    (sd / "sessions").mkdir(parents=True)
    monkeypatch.setenv("JANUSMASK_TASK_ID", "A1")
    return sd


def _patch_registry(monkeypatch, reg):
    import harness.interceptors as interceptors
    monkeypatch.setattr(interceptors, "registry", reg)


_PLAN = {"tasks": [{"task_id": "t1", "title": "PLAN_MARKER_OK"}]}


def test_A1a_planning_mode_detects_plan_draft(state, tmp_path, monkeypatch):
    # DENY registry on purpose: the planning JSON artifact must be returned
    # WITHOUT going through the submit_code interceptor (which would AST-deny it).
    reg = _FakeRegistry(deny=True)
    _patch_registry(monkeypatch, reg)
    monkeypatch.setenv("JANUSMASK_MODE", "planning")

    wd = tmp_path / "wd"
    (wd / "outbox").mkdir(parents=True)
    (wd / "outbox" / "plan_draft.json").write_text(json.dumps(_PLAN))
    proc = _FakePopen(wd)  # alive forever; must return WELL before timeout

    t0 = time.monotonic()
    code = orch.poll_for_submission("claude", state, 1, proc, timeout=5)
    elapsed = time.monotonic() - t0
    assert code is not None and "PLAN_MARKER_OK" in code, (
        "planning mode must recognize outbox/plan_draft.json so the agy "
        "claude_fallback is not fired needlessly"
    )
    assert elapsed < 4.0, "must detect the artifact promptly, not wait the timeout"


def test_A1b_reconciliation_mode_detects_reconciliation(state, tmp_path, monkeypatch):
    reg = _FakeRegistry(deny=True)
    _patch_registry(monkeypatch, reg)
    monkeypatch.setenv("JANUSMASK_MODE", "reconciliation")

    wd = tmp_path / "wd_r"
    (wd / "outbox").mkdir(parents=True)
    (wd / "outbox" / "reconciliation.json").write_text(
        json.dumps({"responses": [{"diff_item_id": "RECON_MARKER", "stance": "concede"}]})
    )
    proc = _FakePopen(wd)

    code = orch.poll_for_submission("claude", state, 1, proc, timeout=5)
    assert code is not None and "RECON_MARKER" in code


def test_A1c_synthesis_mode_ignores_stray_plan_draft(state, tmp_path, monkeypatch):
    reg = _FakeRegistry(deny=False)
    _patch_registry(monkeypatch, reg)
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")

    wd = tmp_path / "wd_s"
    (wd / "outbox").mkdir(parents=True)
    # Only a plan_draft.json (no synthesis submission.py) — must be ignored.
    (wd / "outbox" / "plan_draft.json").write_text(json.dumps(_PLAN))
    proc = _FakePopen(wd, poll_seq=[None, 0])  # exits so the loop terminates

    code = orch.poll_for_submission("claude", state, 1, proc, timeout=3)
    assert code is None, "synthesis mode must not treat plan_draft.json as a submission"
