"""Adversarial plan 01 — T5/T6/T13: spawn cwd + prompt + workroot isolation.

Extends (does not duplicate) test_agent_isolation.py / parallel_prompt_isolation.

  T5  — spawn_agent launches Popen with cwd OUTSIDE the repo and resolves the
        {WORK_DIR} token in the prompt passed to _build_agent_command.
  T6  — prepare_task_prompt points agents at {WORK_DIR}/inbox/task.json + targets/
        and never at a {STATE_DIR}/tasks repo path; multi-file + partial-edit
        variants reference inbox/targets/<rel>; staged dest filename matches the
        hook's _INBOX_EXPECTATIONS['synthesis'] == ('task.json',).
  T13 — agent_workroot honors $JANUSMASK_AGENT_WORKROOT literally (no expanduser),
        falls back to the repo SIBLING when unset, and takes no state_dir arg.

No agy/claude spawned — Popen is a non-exec FakePopen.
"""
from __future__ import annotations

import inspect
from pathlib import Path

import pytest

import harness.orchestrator as orch
from harness.paths import PROJECT_ROOT, agent_workroot, agent_work_dir
from harness.hooks._env import _INBOX_EXPECTATIONS


def _outside_repo(p) -> bool:
    p = Path(p).resolve()
    try:
        p.relative_to(PROJECT_ROOT.resolve())
        return False
    except ValueError:
        return True


# --------------------------------------------------------------------------- #
# T5 — spawn_agent cwd outside repo + {WORK_DIR} substituted in resolved prompt
# --------------------------------------------------------------------------- #
def test_T5_spawn_cwd_outside_repo_and_prompt_workdir_substituted(tmp_path, monkeypatch):
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "wr"))
    monkeypatch.setenv("JANUSMASK_TASK_ID", "ISO5")
    captured = {}

    class _P:
        def __init__(self, cmd, **kwargs):
            captured["cmd"] = cmd
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = kwargs.get("env", {})
            self.pid = 999
            self.returncode = None

        def poll(self):
            return None

    monkeypatch.setattr(orch.subprocess, "Popen", _P)
    monkeypatch.setattr(orch, "start_stream_threads", lambda *a, **k: ())

    # capture the resolved prompt handed to _build_agent_command
    real_build = orch._build_agent_command

    def _spy_build(agent, resolved_prompt, config):
        captured["resolved_prompt"] = resolved_prompt
        return real_build(agent, resolved_prompt, config)

    monkeypatch.setattr(orch, "_build_agent_command", _spy_build)

    state_dir = tmp_path / "state"
    state_dir.mkdir()
    config = {"state_dir": str(state_dir),
              "agents": {"gemini": {"command": "agy", "args": ["-p", "--sandbox"]}}}

    orch.spawn_agent("gemini", "read {WORK_DIR}/inbox/task.json then submit", config, round_number=1)

    assert captured["cwd"] is not None
    assert _outside_repo(captured["cwd"]), f"cwd {captured['cwd']} must be outside repo"
    assert Path(captured["cwd"]).resolve() == Path(captured["env"]["JANUSMASK_WORK_DIR"]).resolve()
    # {WORK_DIR} token resolved to the real workdir in the resolved prompt:
    rp = captured["resolved_prompt"]
    assert "{WORK_DIR}" not in rp, "the {WORK_DIR} placeholder must be substituted before spawn"
    assert str(Path(captured["env"]["JANUSMASK_WORK_DIR"])) in rp


# --------------------------------------------------------------------------- #
# T6 — prepare_task_prompt routes to per-spawn inbox, never repo spec path
# --------------------------------------------------------------------------- #
def test_T6_single_file_prompt_inbox_paths():
    p = orch.prepare_task_prompt({"task_id": "T6S", "specification": "demo",
                                  "files_touched": ["pkg/a.py"]})
    assert "{WORK_DIR}/inbox/task.json" in p
    assert "{WORK_DIR}/inbox/targets/" in p
    assert "{STATE_DIR}/tasks" not in p
    assert "current_task_" not in p


def test_T6_multifile_prompt_targets_block():
    p = orch.prepare_task_prompt({"task_id": "T6M", "specification": "demo",
                                  "files_touched": ["pkg/a.py", "pkg/b.py"]})
    assert "MULTI-FILE DISPATCH" in p
    assert "{WORK_DIR}/inbox/targets/<rel>" in p
    assert "__JANUSMASK_MANIFEST__" in p
    assert "{STATE_DIR}/tasks" not in p


def test_T6_partial_edit_prompt_targets_block():
    p = orch.prepare_task_prompt({"task_id": "T6P", "specification": "demo",
                                  "partial_edit": True, "files_touched": ["pkg/big.py"]})
    assert "PARTIAL-EDIT DISPATCH" in p
    assert "{WORK_DIR}/inbox/targets/<rel>" in p
    assert "__JANUSMASK_PATCHES__" in p
    assert "{STATE_DIR}/tasks" not in p


def test_T6_staged_dest_matches_hook_expectation():
    """The prompt keys on inbox/task.json; the staging map + hook must agree."""
    inbox_name, _candidates = orch._INBOX_SOURCES_BY_MODE["synthesis"]
    assert inbox_name == "task.json"
    assert _INBOX_EXPECTATIONS["synthesis"] == ("task.json",)


def test_T6_gap_inbox_source_candidates_omit_canonical_spec_path():
    """GAP (plan §5 :2468-2471): the worker writes the spec to
    tasks/current_task_<id>.json via current_task_spec_path, and _stage_inbox
    only PREPENDS that path when JANUSMASK_TASK_ID is set in the environment.
    The static _INBOX_SOURCES_BY_MODE['synthesis'] candidate list is the
    LEGACY shared tasks/current_task.json — which the worker no longer writes.
    So if JANUSMASK_TASK_ID is unset at stage time, inbox/task.json (and thus
    inbox/targets/) is never populated."""
    _name, candidates = orch._INBOX_SOURCES_BY_MODE["synthesis"]
    # The static candidate list contains only the legacy shared path:
    assert candidates == ("tasks/current_task.json",), (
        "static synthesis candidates changed — re-verify the env-dependent "
        "prepend logic in _stage_inbox"
    )
    # i.e. the per-task spec path is NOT in the static list; it only appears via
    # the env-var prepend at runtime. Documents the silent-empty-context hazard.
    assert "tasks/current_task_" not in candidates[0]


# --------------------------------------------------------------------------- #
# T13 — agent_workroot override semantics
# --------------------------------------------------------------------------- #
def test_T13_workroot_honors_literal_override_no_expanduser(monkeypatch):
    # a ~-containing value must NOT be expanduser'd (literal, resolved abs).
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", "/tmp/janus_wr_~literal")
    wr = agent_workroot()
    assert "~literal" in str(wr), f"~ must be kept literal, got {wr}"
    assert wr.is_absolute()


def test_T13_workroot_default_is_repo_sibling(monkeypatch):
    monkeypatch.delenv("JANUSMASK_AGENT_WORKROOT", raising=False)
    wr = agent_workroot()
    assert wr == PROJECT_ROOT.parent / f"{PROJECT_ROOT.name}_agentwork"
    assert _outside_repo(wr)


def test_T13_workroot_takes_no_state_dir_arg():
    """workroot must be repo-derived, invariant to any caller state_dir."""
    sig = inspect.signature(agent_workroot)
    assert len(sig.parameters) == 0, "agent_workroot must take no args (repo-derived)"
    # agent_work_dir takes (agent, session_slug) — NOT a state_dir:
    wd_sig = inspect.signature(agent_work_dir)
    assert list(wd_sig.parameters) == ["agent", "session_slug"]


# --------------------------------------------------------------------------- #
# M5 — verify-don't-fix pin: JANUSMASK_TASK_ID is set in the process env BEFORE
# any staging/spawn on the real worker path, so _stage_inbox/_stage_targets always
# see the canonical per-task spec (tasks/current_task_<id>.json). If a synthesis
# path is ever found that stages before setting the global, M5 promotes to a fix.
# --------------------------------------------------------------------------- #
def test_M5_worker_sets_task_id_env_before_staging_and_spawn():
    import re
    src = (PROJECT_ROOT / "harness" / "orchestrator_worker.py").read_text()
    set_m = re.search(r"os\.environ\[['\"]JANUSMASK_TASK_ID['\"]\]\s*=", src)
    assert set_m, "worker no longer sets os.environ['JANUSMASK_TASK_ID']"
    # Everything that consumes the canonical spec / spawns an agent must come AFTER.
    consumers = [m.start() for m in re.finditer(
        r"_stage_inbox|_stage_targets|spawn_agent|run_both_agents|run_synthesis", src)]
    assert consumers, "no staging/spawn callsite found — test is stale"
    assert set_m.start() < min(consumers), (
        "JANUSMASK_TASK_ID is set AFTER a staging/spawn site — M5 silent-empty-context "
        "regression; the canonical per-task spec would not be staged")
