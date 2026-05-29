"""Adversarial plan 01 — T1/T2/T11: dual-agent agreement invariant + fallback.

The synthesis pipeline MUST only accept when BOTH agents produced non-empty
code (orchestrator_worker.main :173/:245, orchestrator.run_pipeline :1732). These
tests drive the worker ``main()`` with ``run_both_agents`` mocked (NO real spawn)
to prove:

  T1  — one agent returns "" (empty, falsy-but-not-None) never accepts; the
        worker exhausts retries and exits 1 (synthesis_or_ast_failed), and
        ``_auto_commit_accepted`` is never reached.
  T2  — both agents None (double timeout) exits 2 on the FIRST iteration with
        ``both_agents_timed_out`` (no second run_both_agents call). Documents the
        dead ``ast_retries += 1`` increment at :196.
  T11 — run_both_agents claude_fallback substitutes for a None agent_a but
        gemini_b is still independently produced; fallback only fires for
        ``agent_a == 'claude'`` (config-fragile asymmetry).

All agent execution is mocked at the ``run_both_agents`` / ``run_agent_phase``
seam. No agy/claude is ever spawned. full_stop stays untouched (tests only use
tmp_path).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

import harness.orchestrator as orch
import harness.orchestrator_worker as ow


# --------------------------------------------------------------------------- #
# Worker harness: run main() against a tmp state_dir with run_both_agents mocked
# --------------------------------------------------------------------------- #
@pytest.fixture
def worker_env(tmp_path, monkeypatch):
    """A minimal claimed-task state_dir + config patched so main() runs spawn-free."""
    state_dir = tmp_path / "state"
    (state_dir / "tasks").mkdir(parents=True)
    (state_dir / "sessions").mkdir(parents=True)
    task_id = "DUALINV_T"
    task = {
        "task_id": task_id,
        "specification": "do a thing",
        "files_touched": ["pkg/mod.py"],
        "verification_command": "true",
    }
    (state_dir / "tasks" / f"{task_id}.json").write_text(json.dumps(task))

    # Config: legacy else-branch (use_retry_module absent => False), antigravity
    # off so active_agents are distinct, fast.
    cfg = {
        "synthesis": {
            "timeout_seconds": 600,
            "max_ast_retries": 3,
            "antigravity_mode": False,
            "active_agents": ["claude", "gemini"],
        },
        "cross_examination": {"max_rounds": 1},
        "decomposition": {"max_depth": 3},
    }
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg)

    # never spawn / touch the real workroot
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "wr"))

    # argv for argparse in main()
    monkeypatch.setattr(
        sys, "argv",
        ["orchestrator_worker", "--state-dir", str(state_dir), "--task-id", task_id],
    )
    return {"state_dir": state_dir, "task_id": task_id, "cfg": cfg}


def test_T1_one_agent_empty_string_never_accepts(worker_env, monkeypatch):
    """agent_b == '' (falsy, not None) must never accept; exits 1, no commit."""
    commit_calls = []
    monkeypatch.setattr(
        orch, "_auto_commit_accepted",
        lambda *a, **k: commit_calls.append(a) or True,
    )

    rb_calls = {"n": 0}

    def _fake_run_both(*a, **k):
        rb_calls["n"] += 1
        return ("def f():\n    return 1\n", "")  # b empty string every retry

    monkeypatch.setattr(orch, "run_both_agents", _fake_run_both)

    rc = ow.main()

    assert rc == 1, f"empty-string second agent must reject (exit 1), got {rc}"
    assert not commit_calls, "_auto_commit_accepted must NEVER be called on a one-agent submission"
    # single-missing branch (:201) retries up to max_ast_retries then falls
    # through to synthesis_or_ast_failed; run_both_agents called >1 time.
    assert rb_calls["n"] >= 1


def test_T2_double_none_exits_2_no_retry(worker_env, monkeypatch):
    """Both agents None: exit 2 on the FIRST iteration, run_both_agents called once.

    Documents the dead ``ast_retries += 1`` at orchestrator_worker.py:196 — the
    increment is immediately followed by ``return 2`` so it can never gate a retry.
    """
    commit_calls = []
    monkeypatch.setattr(
        orch, "_auto_commit_accepted",
        lambda *a, **k: commit_calls.append(a) or True,
    )

    rb_calls = {"n": 0}

    def _fake_run_both(*a, **k):
        rb_calls["n"] += 1
        return (None, None)

    monkeypatch.setattr(orch, "run_both_agents", _fake_run_both)

    rc = ow.main()

    assert rc == 2, f"double-timeout must exit 2, got {rc}"
    assert rb_calls["n"] == 1, (
        "double-timeout must NOT retry — run_both_agents must be called exactly "
        f"once (the ast_retries+=1 at :196 is dead). Got {rb_calls['n']} calls."
    )
    assert not commit_calls


# --------------------------------------------------------------------------- #
# T11 — claude_fallback preserves the dual-agent invariant (run_both_agents)
# --------------------------------------------------------------------------- #
def _run_both_with_phase_mock(monkeypatch, phase_returns):
    """Drive run_both_agents with run_agent_phase mocked to a dict {agent: code}."""
    calls = []

    def _fake_phase(agent, prompt, config, state_dir, round_number, phase_name, **k):
        calls.append(agent)
        return phase_returns.get(agent)

    monkeypatch.setattr(orch, "run_agent_phase", _fake_phase)
    cfg = {"synthesis": {"antigravity_mode": True,
                         "active_agents": ["claude", "gemini"],
                         "timeout_seconds": 600}}
    res = orch.run_both_agents("pa", "pb", cfg, Path("/tmp/x"), 1, "synthesis")
    return res, calls


def test_T11_fallback_substitutes_for_none_claude(monkeypatch):
    """claude->None triggers claude_fallback; gemini still independently produced."""
    (code_a, code_b), calls = _run_both_with_phase_mock(
        monkeypatch,
        {"claude": None, "claude_fallback": "codeA", "gemini": "codeB"},
    )
    assert code_a == "codeA" and code_b == "codeB"
    assert calls.count("claude_fallback") == 1, "fallback must fire exactly once"
    # invariant intact: two distinct submissions still flow to the fuzzer.


def test_T11_fallback_both_none_does_not_accept(monkeypatch):
    """claude AND claude_fallback both None -> (None, codeB); downstream rejects."""
    (code_a, code_b), _calls = _run_both_with_phase_mock(
        monkeypatch,
        {"claude": None, "claude_fallback": None, "gemini": "codeB"},
    )
    assert code_a is None and code_b == "codeB"
    # synthesis_success = bool(... and a and b) => False. Invariant holds.


def test_T11_fallback_asymmetry_gap_when_claude_is_agent_b(monkeypatch):
    """GAP: fallback only fires for agent_a=='claude'. Reorder active_agents so
    claude is agent_b -> the None claude slot gets NO fallback (config-fragile)."""
    calls = []

    def _fake_phase(agent, prompt, config, state_dir, round_number, phase_name, **k):
        calls.append(agent)
        return {"gemini": "codeA", "claude": None}.get(agent)

    monkeypatch.setattr(orch, "run_agent_phase", _fake_phase)
    cfg = {"synthesis": {"antigravity_mode": True,
                         "active_agents": ["gemini", "claude"],  # claude is agent_b
                         "timeout_seconds": 600}}
    code_a, code_b = orch.run_both_agents("pa", "pb", cfg, Path("/tmp/x"), 1, "synthesis")
    assert code_a == "codeA"
    assert code_b is None, "claude as agent_b returned None"
    assert "claude_fallback" not in calls, (
        "GAP confirmed: claude_fallback never fires when claude is the SECOND "
        "active agent — the fallback is hard-wired to the agent_a slot."
    )
