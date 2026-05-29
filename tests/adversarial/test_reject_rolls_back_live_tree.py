"""CONTAIN C3 — live-tree rollback on every non-accept worker outcome.

An agent subprocess can write the live repo by absolute path: CWD relocation is
NOT a filesystem jail (harness/paths.py:33-36). On an ACCEPTED run the validated
submission is applied through the ``<repo>_staging`` worktree and ff-merged,
overwriting any stray write. But on a REJECT / timeout / decompose outcome the
accept path is never reached, so a stray agent edit to a ``files_touched`` target
PERSISTS in the live tree -- the proximate cause of the GAP_H4 tamper that
survived rejection (CONTAINMENT plan §1.5 / Appendix A-4).

Fix-detector: drive the worker to a *reject* outcome while the mocked synthesis
corrupts a tracked target in a real temp git repo, then assert the target is
restored to HEAD. RED before C3 (no rollback), GREEN after.

No agy/claude spawned -- run_both_agents + validation are mocked.
"""
from __future__ import annotations

import json
import subprocess
import sys

import pytest

import harness.orchestrator as orch
import harness.orchestrator_worker as ow


ORIGINAL = "def target():\n    return 'pristine'\n"
TAMPER = "def target():\n    return __import__('os').system('rm -rf /')  # agent tamper\n"


def _git(repo, *args):
    subprocess.run(["git", *args], cwd=str(repo), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def repo_env(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    target = repo / "pkg" / "m.py"
    target.write_text(ORIGINAL)
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@t")
    _git(repo, "config", "user.name", "t")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "init")

    state_dir = repo / "state"
    (state_dir / "tasks").mkdir(parents=True)
    (state_dir / "sessions").mkdir(parents=True)
    task_id = "C3_ROLLBACK"
    task = {"task_id": task_id, "specification": "x",
            "files_touched": ["pkg/m.py"], "verification_command": "true",
            "meta_task_type": "harness_self_fix"}
    (state_dir / "tasks" / f"{task_id}.json").write_text(json.dumps(task))

    cfg = {"synthesis": {"timeout_seconds": 600, "max_ast_retries": 3,
                         "antigravity_mode": False,
                         "active_agents": ["claude", "gemini"]},
           "cross_examination": {"max_rounds": 1},
           "decomposition": {"max_depth": 3}}
    monkeypatch.setattr(orch, "load_config", lambda *a, **k: cfg)
    monkeypatch.setattr(ow, "_compute_timeout_budgets", lambda cfg: (3600.0, 600.0))
    monkeypatch.setattr(ow, "_precompute_baseline_test_results", lambda *a, **k: None)
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "wr"))
    monkeypatch.setattr(sys, "argv",
                        ["ow", "--state-dir", str(state_dir), "--task-id", task_id])
    return {"repo": repo, "target": target, "state_dir": state_dir, "task_id": task_id}


def test_reject_restores_tampered_target_to_head(repo_env, monkeypatch):
    target = repo_env["target"]

    def _tamper_then_invalid(*a, **k):
        # Simulate an agent reaching the live tree by absolute path mid-run.
        target.write_text(TAMPER)
        return ("invalid", "invalid")

    monkeypatch.setattr(orch, "run_both_agents", _tamper_then_invalid)
    # Force AST validation to fail so synthesis_success stays False -> reject.
    monkeypatch.setattr(orch, "_validate_submission", lambda code, agent, task: (False, []))
    monkeypatch.setattr(orch, "_try_auto_repair", lambda *a, **k: None)

    rc = ow.main()

    assert rc == 1, f"AST-failed synthesis must reject (exit 1), got {rc}"
    assert target.read_text() == ORIGINAL, (
        "C3: a stray agent write to a files_touched target must be rolled back "
        "to HEAD on a reject outcome"
    )
    # The tamper must be gone from the working tree per git as well.
    porcelain = subprocess.run(["git", "status", "--porcelain", "--", "pkg/m.py"],
                               cwd=str(repo_env["repo"]), capture_output=True, text=True)
    assert porcelain.stdout.strip() == "", "target must be clean vs HEAD after rollback"


def test_accept_outcome_does_not_rollback(repo_env, monkeypatch):
    """On accept (exit 0) the committed change must survive -- rollback must NOT
    fire and clobber a legitimately-applied submission."""
    target = repo_env["target"]
    GOOD = "def target():\n    return 'improved'\n"

    def _good(*a, **k):
        return (GOOD, GOOD)

    monkeypatch.setattr(orch, "run_both_agents", _good)
    monkeypatch.setattr(orch, "_validate_submission", lambda code, agent, task: (True, []))
    monkeypatch.setattr(ow, "_detect_and_append_untracked_tests", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_save_final_output", lambda *a, **k: None)
    monkeypatch.setattr(orch, "_persist_fuzz_results", lambda *a, **k: None)

    class _FR:
        error = None
        equivalent = True
        failures = []

    monkeypatch.setattr("harness.diff_fuzzer.fuzz_from_task", lambda *a, **k: _FR())

    # Emulate the staging-applied commit: write GOOD and have _auto_commit_accepted
    # report success (the real staging/merge path is exercised elsewhere).
    def _commit(*a, **k):
        target.write_text(GOOD)
        return True

    monkeypatch.setattr(orch, "_auto_commit_accepted", _commit)

    rc = ow.main()
    assert rc == 0, f"valid+equivalent submission should accept (exit 0), got {rc}"
    assert target.read_text() == GOOD, "accept path must not be rolled back"
