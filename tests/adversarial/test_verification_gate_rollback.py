"""Adversarial plan 01 — T10: verification gate rollback + hardcoded-600 gap.

The verification block in _auto_commit_accepted (orchestrator.py :1480-1576) runs
the resolved verification_command inside the staging worktree; a non-zero exit
rolls back the commit and returns False.

  T10a — verification_command "false" (exit 1) -> rollback, returns False, no
         net commit, verification_failed ledger row.
  T10b — empty / None verification_command -> verification_missing rollback,
         returns False.
  T10c — GAP (plan §5 :1543): the subprocess timeout is hardcoded to 600s while
         synthesis.timeout_seconds was raised to 1200. A legit >600s verify is
         killed (exit 124) and rejected. Proven by source inspection — the 600
         is not derived from config.

No agy/claude spawned. Real tmp git repo; verification_command resolution mocked.
"""
from __future__ import annotations

import inspect
import json
import re
import subprocess
from pathlib import Path

import pytest

import harness.orchestrator as orch


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True, capture_output=True, text=True)


@pytest.fixture
def repo(tmp_path):
    """A real git repo with state/output; state_dir = repo/state."""
    repo = tmp_path / "repo"
    (repo / "pkg").mkdir(parents=True)
    (repo / "state" / "output").mkdir(parents=True)
    (repo / "pkg" / "mod.py").write_text("v = 1\n")
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "init"], repo)
    return repo


def _head(repo):
    return subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(repo),
                          capture_output=True, text=True).stdout.strip()


def test_T10a_verification_failure_rolls_back(repo, monkeypatch):
    sd = repo / "state"
    task_id = "VF"
    task = {"task_id": task_id, "files_touched": ["pkg/mod.py"],
            "verification_command": "false"}
    (sd / "output" / f"{task_id}.files.json").write_text(json.dumps({"pkg/mod.py": "v = 2\n"}))
    # resolve vcmd -> "false" (exit 1)
    monkeypatch.setattr(orch, "_resolve_verification_command", lambda s, t, i: "false")

    head_before = _head(repo)
    ok = orch._auto_commit_accepted(sd, task, task_id)
    assert ok is False, "verification failure must reject"
    assert _head(repo) == head_before, "commit must be rolled back to prior HEAD"

    # verification_failed ledger row present
    ledger = (sd / "impl_progress.jsonl")
    rows = [json.loads(l) for l in ledger.read_text().splitlines()] if ledger.exists() else []
    assert any(r.get("event") == "verification_failed" for r in rows), rows


def test_T10b_empty_vcmd_is_verification_missing(repo, monkeypatch):
    sd = repo / "state"
    task_id = "VM"
    task = {"task_id": task_id, "files_touched": ["pkg/mod.py"], "verification_command": ""}
    (sd / "output" / f"{task_id}.files.json").write_text(json.dumps({"pkg/mod.py": "v = 9\n"}))
    monkeypatch.setattr(orch, "_resolve_verification_command", lambda s, t, i: "")

    head_before = _head(repo)
    ok = orch._auto_commit_accepted(sd, task, task_id)
    assert ok is False
    assert _head(repo) == head_before, "missing vcmd must roll back"
    ledger = (sd / "impl_progress.jsonl")
    rows = [json.loads(l) for l in ledger.read_text().splitlines()] if ledger.exists() else []
    assert any(r.get("event") == "verification_missing" for r in rows), rows


def test_T10c_verification_timeout_hardcoded_600_not_config_derived():
    """GAP: the verify subprocess timeout is the literal 600, not derived from
    synthesis.timeout_seconds (raised to 1200 in 28db488). A >600s verify is
    killed at 600s -> exit 124 -> reject."""
    src = inspect.getsource(orch._auto_commit_accepted)
    # the verify subprocess.run uses timeout=600 literally
    assert re.search(r"subprocess\.run\(.*timeout=600", src, re.DOTALL), (
        "expected hardcoded timeout=600 on the verify subprocess.run"
    )
    # and it is NOT derived from config/timeout_seconds anywhere in the function
    assert "timeout_seconds" not in src, (
        "GAP would be closed if the verify timeout were derived from "
        "synthesis.timeout_seconds"
    )
    # the timeout path stamps exit 124 + a '600s' message
    assert "verify_exit = 124" in src
    assert "600s" in src


def test_T10c_baseline_precompute_also_hardcoded_600():
    """The worker's baseline verification precompute shares the same hardcoded
    600s timeout (orchestrator_worker._precompute_baseline_test_results)."""
    import harness.orchestrator_worker as ow
    src = inspect.getsource(ow._precompute_baseline_test_results)
    assert "timeout=600" in src
    assert "after 600s" in src
