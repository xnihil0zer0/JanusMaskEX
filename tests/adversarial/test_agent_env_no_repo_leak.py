"""CONTAIN C1 — the agent spawn env must not point CLAUDE_PROJECT_DIR at the repo.

Claude resolves its project root, hook discovery, ${CLAUDE_PROJECT_DIR} permission
roots and settings/MCP-config interpolation from the CLAUDE_PROJECT_DIR env var
(proven empirically: the system already runs with cwd=work_dir outside the repo
yet hooks/MCP resolve correctly, so the var -- not cwd -- drives interpolation).
Pointing it at the live repo defeats the (correct) outside-repo CWD relocation.

Fix-detector: CLAUDE_PROJECT_DIR must be the outside-repo per-spawn work_dir, while
JANUSMASK_PROJECT_DIR stays the repo (hooks/harness need it) and PYTHONPATH keeps
``import harness.*`` resolvable from the spawned env. RED before C1, GREEN after.
"""
from __future__ import annotations

import os
import subprocess
import sys

import harness.orchestrator as orch
from harness.paths import PROJECT_ROOT, agent_workroot


def _env(monkeypatch, tmp_path):
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "wr"))
    monkeypatch.setenv("JANUSMASK_TASK_ID", "C1_LEAK")
    return orch._build_agent_env("claude", str(PROJECT_ROOT / "state"), 1)


def test_claude_project_dir_is_outside_repo(monkeypatch, tmp_path):
    env = _env(monkeypatch, tmp_path)
    cpd = env["CLAUDE_PROJECT_DIR"]
    repo = str(PROJECT_ROOT)
    assert cpd != repo, "CLAUDE_PROJECT_DIR must NOT be the live repo (the leak)"
    from pathlib import Path
    assert PROJECT_ROOT not in Path(cpd).resolve().parents and Path(cpd).resolve() != PROJECT_ROOT, \
        f"CLAUDE_PROJECT_DIR {cpd} must be OUTSIDE the repo tree"
    # It must equal the per-spawn work_dir (under the outside-repo workroot).
    assert cpd == env["JANUSMASK_WORK_DIR"], "CLAUDE_PROJECT_DIR should be the spawn work_dir"
    assert str(agent_workroot()) in cpd


def test_janusmask_project_dir_stays_repo(monkeypatch, tmp_path):
    env = _env(monkeypatch, tmp_path)
    assert env["JANUSMASK_PROJECT_DIR"] == str(PROJECT_ROOT), \
        "JANUSMASK_PROJECT_DIR must remain the repo so the trusted hook process " \
        "resolves its read-roots to the source tree"


def test_pythonpath_keeps_harness_importable(monkeypatch, tmp_path):
    env = _env(monkeypatch, tmp_path)
    assert "PYTHONPATH" in env, "PYTHONPATH must be set explicitly (decoupled from CLAUDE_PROJECT_DIR)"
    assert str(PROJECT_ROOT) in env["PYTHONPATH"].split(os.pathsep)
    # Prove a fresh interpreter using ONLY this PYTHONPATH can import harness.
    r = subprocess.run(
        [sys.executable, "-c", "import harness.paths, harness.orchestrator_worker; print('OK')"],
        env={"PYTHONPATH": env["PYTHONPATH"], "PATH": os.environ.get("PATH", "")},
        capture_output=True, text=True, cwd=str(tmp_path),
    )
    assert r.returncode == 0 and "OK" in r.stdout, f"harness import from spawned PYTHONPATH failed: {r.stderr[:300]}"
