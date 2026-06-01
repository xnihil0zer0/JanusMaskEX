"""AGENT-ISOLATION §6 verification gate.

Covers the load-bearing controls of AGENT_ISOLATION_fix_plan.md:

* §6.1 (structural) — every agent spawn site launches with ``cwd`` set to the
  relocated, OUTSIDE-the-repo workdir, so ``git`` cannot auto-discover ``.git``
  from CWD and bare repo-relative paths no longer resolve into the source tree.
* §6.2 — the §1b apply-path gate: a manifest/patch targeting ``harness/**`` /
  ``config/**`` / ``scripts/**`` is rejected unless the task is a sanctioned
  ``harness_self_fix`` AND operator approval fired; non-member targets are
  rejected even outside the protected paths.
* §6.4b — BOTH ``autowork_daemon`` self-heal spawns (retry-budget and
  inactivity watchdog) launch outside the repo and no longer instruct
  repo-root / allowlist writes.

These run with ``JANUSMASK_AGENT_WORKROOT`` redirected to a tmp dir so the test
never touches the real ``../JanusMaskJR_agentwork`` sibling. The empirical
real-``agy`` negative probe (§6.1 launching a live agent) is run out-of-band as
a controlled script, not baked into this deterministic gate.
"""
from __future__ import annotations

import inspect
import json
import subprocess
from pathlib import Path

import pytest

import harness.orchestrator as orch
import harness.autowork_daemon as dae
import harness.git_integration as gi
from harness.paths import PROJECT_ROOT, agent_workroot, agent_work_dir


# --------------------------------------------------------------------------- #
# §6.1 — spawn sites set cwd outside the repo
# --------------------------------------------------------------------------- #
class _FakePopen:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = 424242
        self.returncode = None

    def poll(self):
        return None

    def communicate(self, input=None, timeout=None):
        self.returncode = 0
        return ('', '')


def _is_outside_repo(p: Path) -> bool:
    p = Path(p).resolve()
    try:
        p.relative_to(PROJECT_ROOT.resolve())
        return False  # inside the repo -> NOT isolated
    except ValueError:
        return True


@pytest.fixture
def workroot(tmp_path, monkeypatch):
    root = tmp_path / "agentwork"
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(root))
    return root


def test_agent_workroot_is_outside_repo(workroot):
    wd = agent_work_dir("gemini", "gemini-r1-T-deadbeef")
    assert _is_outside_repo(wd), f"workdir {wd} must be outside the repo"
    assert str(wd).startswith(str(workroot.resolve()))


def test_spawn_agent_cwd_relocated_outside_repo(workroot, tmp_path, monkeypatch):
    captured = {}

    class _P(_FakePopen):
        def __init__(self, cmd, **kwargs):
            super().__init__(cmd, **kwargs)
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = kwargs.get("env", {})

    monkeypatch.setattr(orch.subprocess, "Popen", _P)
    monkeypatch.setattr(orch, "start_stream_threads", lambda *a, **k: ())
    monkeypatch.setenv("JANUSMASK_TASK_ID", "ISO_T")
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = {"state_dir": str(state_dir),
              "agents": {"gemini": {"command": "agy", "args": ["-p", "--sandbox"]}}}
    orch.spawn_agent("gemini", "prompt", config, round_number=1)

    assert captured["cwd"] is not None, "spawn_agent must pass cwd= to Popen"
    assert _is_outside_repo(Path(captured["cwd"])), \
        f"spawn cwd {captured['cwd']} must be outside the repo"
    # cwd must equal the isolated work_dir advertised in the env
    assert Path(captured["cwd"]).resolve() == Path(captured["env"]["JANUSMASK_WORK_DIR"]).resolve()
    assert str(Path(captured["cwd"]).resolve()).startswith(str(workroot.resolve()))


def _run_daemon_escalation(fn_kwargs, monkeypatch, captured):
    class _P(_FakePopen):
        def __init__(self, cmd, **kwargs):
            super().__init__(cmd, **kwargs)
            captured["cwd"] = kwargs.get("cwd")
            captured["cmd"] = cmd

    monkeypatch.setattr(dae.subprocess, "Popen", _P)


def test_daemon_retry_budget_spawn_cwd_outside_repo(workroot, tmp_path, monkeypatch):
    captured = {}
    _run_daemon_escalation({}, monkeypatch, captured)
    state_dir = tmp_path / "state"
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    task_id = "DAEMON_RETRY_T"
    # retry-budget self-heal reads the task spec from tasks/blocked/<id>.json
    (state_dir / "tasks" / "blocked" / f"{task_id}.json").write_text(json.dumps(
        {"task_id": task_id, "objective": "do a thing", "files_touched": ["pkg/x.py"]}))
    dae._escalate_to_autobrief(state_dir, task_id, "fuzz_fail")
    assert captured.get("cwd") is not None, "retry-budget self-heal must pass cwd="
    assert _is_outside_repo(Path(captured["cwd"])), \
        f"daemon retry self-heal cwd {captured['cwd']} must be outside the repo"


def test_daemon_inactivity_spawn_cwd_outside_repo(workroot, tmp_path, monkeypatch):
    captured = {}
    _run_daemon_escalation({}, monkeypatch, captured)
    state_dir = tmp_path / "state"
    (state_dir / "tasks").mkdir(parents=True)
    # Make _has_queued true so the degenerate-escalation guard lets us through.
    (state_dir / "tasks" / "SOME_QUEUED.json").write_text(json.dumps({"task_id": "SOME_QUEUED"}))
    config = {"control": {"autobrief_default_agent": "claude"},
              "agents": {"claude": {"command": "claude", "args": ["-p"]}}}
    # J3 (C7-R): this toy claude config carries no --settings; this test covers cwd
    # isolation, NOT the hook gate the daemon claude path now enforces (covered by
    # test_daemon_control_isolation_hooks TC3_4/TC3_5), so stub the C7-R assertion.
    monkeypatch.setattr(orch, "_assert_claude_hook_config", lambda cmd: None)
    dae._escalate_inactivity(state_dir, config)
    assert captured.get("cwd") is not None, "inactivity self-heal must pass cwd="
    assert _is_outside_repo(Path(captured["cwd"])), \
        f"daemon inactivity self-heal cwd {captured['cwd']} must be outside the repo"


def test_selfheal_prompts_scrubbed_of_repo_writes():
    """§3.8.3 — neither self-heal spawn may instruct allowlist / repo-root writes."""
    src = inspect.getsource(dae._escalate_to_autobrief) + inspect.getsource(dae._escalate_inactivity)
    # The pre-fix prompts told the agent to append to the live allowlist and to
    # write brief_hooks at the repo root. After scrubbing those instructions are
    # gone and replaced with outbox-only guidance.
    assert "Append `" not in src and "as a new line to the allowlist" not in src
    assert "OUTBOX" in src  # outbox-only guidance present
    assert "do NOT run git" in src or "Do NOT" in src


# --------------------------------------------------------------------------- #
# §6.2 — §1b apply-path scoping (helper + end-to-end through a real commit)
# --------------------------------------------------------------------------- #
def test_apply_scope_helper_units():
    f = gi._enforce_apply_scope
    assert f(["harness/orchestrator.py"], allowed_files=None, meta_task_type=None, approval_ok=False)
    assert f(["harness/x.py"], allowed_files=None, meta_task_type="harness_self_fix", approval_ok=False)
    assert f(["harness/x.py"], allowed_files=None, meta_task_type="other", approval_ok=True)
    assert f(["harness/x.py"], allowed_files=None, meta_task_type="harness_self_fix", approval_ok=True) is None
    assert f(["config/config.yaml"], allowed_files=None, meta_task_type=None, approval_ok=False)
    assert f(["scripts/run.sh"], allowed_files=None, meta_task_type=None, approval_ok=False)
    assert f(["pkg/mod.py"], allowed_files=None, meta_task_type=None, approval_ok=False) is None
    # membership
    assert f(["pkg/mod.py"], allowed_files={"pkg/mod.py"}, meta_task_type=None, approval_ok=False) is None
    assert f(["pkg/evil.py"], allowed_files={"pkg/mod.py"}, meta_task_type=None, approval_ok=False)
    # no false-positive on a harness_ filename prefix that is not under harness/
    assert f(["pkg/harness_helper.py"], allowed_files=None, meta_task_type=None, approval_ok=False) is None


def _git(args, cwd):
    subprocess.run(["git", *args], cwd=str(cwd), check=True,
                   capture_output=True, text=True)


@pytest.fixture
def tmp_repo(tmp_path):
    repo = tmp_path / "repo"
    (repo / "harness").mkdir(parents=True)
    (repo / "pkg").mkdir(parents=True)
    (repo / "state" / "output").mkdir(parents=True)
    (repo / "harness" / "x.py").write_text("x = 1\n")
    (repo / "pkg" / "mod.py").write_text("y = 1\n")
    _git(["init", "-q"], repo)
    _git(["config", "user.email", "t@t"], repo)
    _git(["config", "user.name", "t"], repo)
    _git(["add", "-A"], repo)
    _git(["commit", "-qm", "init"], repo)
    return repo


def test_apply_gate_rejects_harness_without_approval(tmp_repo):
    sd = tmp_repo / "state"
    (sd / "output" / "SF.files.json").write_text(json.dumps({"harness/x.py": "x = 2\n"}))
    r = gi.commit_accepted_output("SF", str(tmp_repo / "harness" / "x.py"), sd,
                                  worktree_root=tmp_repo, allowed_files={"harness/x.py"},
                                  meta_task_type="harness_self_fix", approval_ok=False)
    assert r["committed"] is False
    assert "scope violation" in (r["error"] or "")


def test_apply_gate_allows_harness_with_approval(tmp_repo):
    sd = tmp_repo / "state"
    (sd / "output" / "SF.files.json").write_text(json.dumps({"harness/x.py": "x = 2\n"}))
    r = gi.commit_accepted_output("SF", str(tmp_repo / "harness" / "x.py"), sd,
                                  worktree_root=tmp_repo, allowed_files={"harness/x.py"},
                                  meta_task_type="harness_self_fix", approval_ok=True)
    assert r["committed"] is True and r["sha"]


def test_apply_gate_rejects_non_member(tmp_repo):
    sd = tmp_repo / "state"
    (sd / "output" / "BAD.files.json").write_text(json.dumps({"pkg/evil.py": "z = 1\n"}))
    r = gi.commit_accepted_output("BAD", str(tmp_repo / "pkg" / "mod.py"), sd,
                                  worktree_root=tmp_repo, allowed_files={"pkg/mod.py"},
                                  meta_task_type=None, approval_ok=False)
    assert r["committed"] is False
    assert "not a member" in (r["error"] or "")


def test_apply_approval_granted_reads_decision_file(tmp_path):
    sd = tmp_path / "state"
    (sd / "control" / "decisions").mkdir(parents=True)
    assert orch._apply_approval_granted(sd, "T") is False  # absent -> closed
    (sd / "control" / "decisions" / "T.json").write_text(json.dumps({"decision": "approve"}))
    assert orch._apply_approval_granted(sd, "T") is True
    (sd / "control" / "decisions" / "T.json").write_text(json.dumps({"decision": "reject"}))
    assert orch._apply_approval_granted(sd, "T") is False
