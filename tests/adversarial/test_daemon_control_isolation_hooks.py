"""Adversarial battery for plan 03 — autowork daemon self-heal, the
degenerate-escalation guard, control_gate (approval/pause), agent isolation
(``paths.agent_work_dir`` + CWD relocation), and the gemini ``pre_tool`` hook.

Every test MOCKS ``subprocess.Popen`` at the module under test — NO real agy /
claude / daemon is ever launched. ``JANUSMASK_AGENT_WORKROOT`` is pinned to a
tmp dir so the real ``../JanusMaskJR_agentwork`` sibling is never touched. The
real ``state/control/`` (full_stop=halted, deny-all allowlist) is never written;
all allowlist/queue reads use a per-test tmp ``state_dir``.

Tests whose name ends ``_GAP`` (or carry an inline ``GAP:`` comment) assert the
ACTUAL current behavior of an incompletely-implemented / latent-bug surface, as
evidence of a gap — they pass green but document the defect.
"""
from __future__ import annotations

import inspect
import json
import re
import subprocess
from pathlib import Path

import pytest

import harness.orchestrator as orch
import harness.autowork_daemon as dae
import harness.git_integration as gi
import harness.control_gate as cg
from harness.paths import PROJECT_ROOT, agent_workroot, agent_work_dir
from harness.hooks.gemini import pre_tool as gpt
from harness.hooks import _env as shared_env


# --------------------------------------------------------------------------- #
# shared helpers (mirrors test_agent_isolation.py templates)
# --------------------------------------------------------------------------- #
class _FakePopen:
    def __init__(self, cmd, **kwargs):
        self.cmd = cmd
        self.kwargs = kwargs
        self.pid = 424242
        self.returncode = None

    def poll(self):
        return None

    def wait(self, timeout=None):
        return 0


def _is_outside_repo(p) -> bool:
    p = Path(p).resolve()
    try:
        p.relative_to(PROJECT_ROOT.resolve())
        return False
    except ValueError:
        return True


@pytest.fixture
def workroot(tmp_path, monkeypatch):
    root = tmp_path / "agentwork"
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(root))
    return root


def _patch_daemon_popen(monkeypatch, captured):
    class _P(_FakePopen):
        def __init__(self, cmd, **kwargs):
            super().__init__(cmd, **kwargs)
            captured["cwd"] = kwargs.get("cwd")
            captured["env"] = kwargs.get("env", {})
            captured["cmd"] = cmd

    monkeypatch.setattr(dae.subprocess, "Popen", _P)


def _read_telemetry(state_dir: Path):
    ledger = state_dir / "impl_progress.jsonl"
    rows = []
    if ledger.exists():
        for line in ledger.read_text().splitlines():
            line = line.strip()
            if line:
                rows.append(json.loads(line))
    return rows


def _force_gemini_config():
    # Force the gemini default so the agent_cfg fallback resolves to bare agy.
    return {"control": {"autobrief_default_agent": "gemini"},
            "agents": {}}


# --------------------------------------------------------------------------- #
# Group 1 — cwd-outside-repo on every spawn site
# --------------------------------------------------------------------------- #
def test_TC1_1_spawn_worker_passes_no_cwd_and_is_harness_worker(tmp_path, monkeypatch):
    """_spawn_worker is the ONE spawn site without cwd= — verify it launches the
    trusted harness worker (orchestrator_worker), NOT an agent CLI."""
    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    pid = dae._spawn_worker(tmp_path / "state", "T1")
    assert pid == 424242
    # The daemon worker spawn passes NO cwd kwarg:
    assert captured["cwd"] is None
    argv = captured["cmd"]
    assert argv[1:3] == ["-m", "harness.orchestrator_worker"], argv
    # GAP (low): the worker spawn site is undocumented as "trusted, no cwd" — a
    # future change routing an agent CLI through here would silently bypass
    # Layer A. There is no guard asserting argv[2] == orchestrator_worker.


def test_TC1_2_agent_workroot_override_and_default_outside_repo(workroot, monkeypatch):
    wd = agent_work_dir("gemini", "s")
    assert _is_outside_repo(wd)
    assert str(wd).startswith(str(workroot.resolve()))
    # default (override unset) -> sibling _agentwork, still outside repo
    monkeypatch.delenv("JANUSMASK_AGENT_WORKROOT", raising=False)
    default_root = agent_workroot()
    assert default_root == PROJECT_ROOT.parent / f"{PROJECT_ROOT.name}_agentwork"
    assert _is_outside_repo(default_root)


def test_TC1_2b_override_inside_repo_is_NOT_rejected_GAP(monkeypatch):
    """GAP (med): agent_workroot() does NOT validate the override is outside the
    repo. An env var pointing inside PROJECT_ROOT silently defeats Layer A for
    ALL spawn sites at once. We assert the helper happily returns an inside-repo
    path (the bug), proving the missing guard."""
    inside = PROJECT_ROOT / "state" / "rogue_workroot"
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(inside))
    wd = agent_work_dir("gemini", "s")
    # The helper accepts it -> isolation silently defeated.
    assert not _is_outside_repo(wd), "expected the (buggy) inside-repo acceptance"
    assert str(wd).startswith(str(inside.resolve()))


def test_TC1_2c_relative_override_is_resolved_GAP(monkeypatch, tmp_path):
    """A relative override is .resolve()'d against CWD (no rejection)."""
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", "rel_workroot")
    root = agent_workroot()
    assert root.is_absolute()
    assert root == (Path.cwd() / "rel_workroot").resolve()


def test_TC1_3_retry_budget_cwd_outside_repo(workroot, tmp_path, monkeypatch):
    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    state_dir = tmp_path / "state"
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    tid = "RB_T"
    (state_dir / "tasks" / "blocked" / f"{tid}.json").write_text(json.dumps(
        {"task_id": tid, "objective": "fix the thing", "files_touched": ["pkg/x.py"]}))
    dae._escalate_to_autobrief(state_dir, tid, "fuzz_fail")
    assert captured.get("cwd") is not None
    assert _is_outside_repo(captured["cwd"])
    assert str(Path(captured["cwd"]).resolve()).startswith(str(workroot.resolve()))
    assert Path(captured["cwd"]).resolve() == Path(captured["env"]["JANUSMASK_WORK_DIR"]).resolve()


def test_TC1_4_inactivity_cwd_outside_repo(workroot, tmp_path, monkeypatch):
    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    state_dir = tmp_path / "state"
    (state_dir / "tasks").mkdir(parents=True)
    # tmp allowlist with actionable work so the guard does not short-circuit
    (state_dir / "tasks" / "Q.json").write_text(json.dumps({"task_id": "Q"}))
    cfg = {"control": {"autobrief_default_agent": "claude"},
           "agents": {"claude": {"command": "claude", "args": ["-p"]}}}
    dae._escalate_inactivity(state_dir, cfg)
    assert captured.get("cwd") is not None
    assert _is_outside_repo(captured["cwd"])
    assert Path(captured["cwd"]).resolve() == Path(captured["env"]["JANUSMASK_WORK_DIR"]).resolve()


def test_TC1_5_env_workdir_agrees_with_env_hook_fallback(workroot, tmp_path, monkeypatch):
    """_build_agent_env's WORK_DIR and the _env hook fallback compute the SAME
    dir when the explicit agent is supplied (no split-brain)."""
    monkeypatch.setenv("JANUSMASK_MODE", "synthesis")
    monkeypatch.setenv("JANUSMASK_TASK_ID", "ENVT")
    monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
    env = orch._build_agent_env("gemini", str(tmp_path / "state"), round_number=1)
    # The session slug carries a random uuid, so re-derive via the same slug:
    wd_env = Path(env["JANUSMASK_WORK_DIR"])
    sid = wd_env.name  # <agent>-r1-<task>-<uuid>
    # The hook fallback with the SAME agent + sid lands on the same dir:
    monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
    fallback = shared_env._work_dir(sid, agent="gemini")
    assert wd_env.resolve() == fallback.resolve()


# --------------------------------------------------------------------------- #
# Group 2 — degenerate-escalation guard
# --------------------------------------------------------------------------- #
def test_TC2_1_autobrief_skip_missing_task_json(workroot, tmp_path, monkeypatch):
    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    dae._escalate_to_autobrief(state_dir, "GONE", "fuzz_fail")
    assert "cmd" not in captured, "must NOT spawn when task json missing"
    rows = [r for r in _read_telemetry(state_dir)
            if r.get("event") == "skip_degenerate_escalation"]
    assert rows and rows[-1]["detail"] == "missing_task_json"


def test_TC2_2_autobrief_skip_empty_objective_files_no_errors(workroot, tmp_path, monkeypatch):
    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    state_dir = tmp_path / "state"
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    (state_dir / "tasks" / "blocked" / "E.json").write_text(json.dumps(
        {"task_id": "E", "objective": "", "files_touched": []}))
    dae._escalate_to_autobrief(state_dir, "E", "fuzz_fail")
    assert "cmd" not in captured
    rows = [r for r in _read_telemetry(state_dir)
            if r.get("event") == "skip_degenerate_escalation"]
    assert rows and rows[-1]["detail"] == "empty_objective_files_no_errors"


def test_TC2_3_autobrief_proceeds_when_only_errors_present(workroot, tmp_path, monkeypatch):
    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    state_dir = tmp_path / "state"
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    (state_dir / "tasks" / "blocked" / "ERR.json").write_text(json.dumps(
        {"task_id": "ERR", "objective": "", "files_touched": []}))
    # seed a fuzz result with failures under <state_dir>.parent/logs/fuzz_results
    fz = state_dir.parent / "logs" / "fuzz_results"
    fz.mkdir(parents=True)
    (fz / "ERR_run.json").write_text(json.dumps({"failures": [{"x": 1}]}))
    cfg_agent = {"control": {"autobrief_default_agent": "claude"}}
    dae._escalate_to_autobrief(state_dir, "ERR", "fuzz_fail")
    assert "cmd" in captured, "errors alone must rescue the escalation -> spawn"


def test_TC2_3b_no_errors_sentinel_exact_match(workroot, tmp_path):
    """GAP-doc (low): _no_errors compares the WHOLE stripped string to a single
    sentinel. _get_errors_for_task returns exactly that sentinel when empty, so
    the boundary is exact — verify it."""
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    out = dae._get_errors_for_task(state_dir, "NONE")
    assert out.strip() == "No traceback or fuzz error logs found."


def test_TC2_4_autobrief_proceeds_objective_only(workroot, tmp_path, monkeypatch):
    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    state_dir = tmp_path / "state"
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    (state_dir / "tasks" / "blocked" / "OBJ.json").write_text(json.dumps(
        {"task_id": "OBJ", "objective": "do X", "files_touched": []}))
    dae._escalate_to_autobrief(state_dir, "OBJ", "fuzz_fail")
    assert "cmd" in captured, "objective alone (AND requires all 3 empty) -> spawn"


def test_TC2_5_inactivity_skip_no_actionable_work(workroot, tmp_path, monkeypatch):
    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    dae._escalate_inactivity(state_dir, {})
    assert "cmd" not in captured
    rows = [r for r in _read_telemetry(state_dir)
            if r.get("event") == "skip_degenerate_escalation"]
    assert rows and rows[-1]["detail"] == "no_actionable_work"


def test_TC2_6_inactivity_exhausted_sidecar_not_live(workroot, tmp_path, monkeypatch):
    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    state_dir = tmp_path / "state"
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    (state_dir / "tasks" / "blocked" / "B.json").write_text(json.dumps({"task_id": "B"}))
    (state_dir / "tasks" / "blocked" / "B.exhausted").write_text("1")
    dae._escalate_inactivity(state_dir, {})
    assert "cmd" not in captured, "exhausted-sidecar blocked task is NOT live work"
    rows = [r for r in _read_telemetry(state_dir)
            if r.get("event") == "skip_degenerate_escalation"]
    assert rows and rows[-1]["detail"] == "no_actionable_work"
    # remove sidecar -> now live -> proceeds
    captured.clear()
    (state_dir / "tasks" / "blocked" / "B.exhausted").unlink()
    cfg = {"control": {"autobrief_default_agent": "claude"},
           "agents": {"claude": {"command": "claude", "args": ["-p"]}}}
    dae._escalate_inactivity(state_dir, cfg)
    assert "cmd" in captured


def test_TC2_7_guard_telemetry_shape(workroot, tmp_path, monkeypatch):
    _patch_daemon_popen(monkeypatch, {})
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    dae._escalate_to_autobrief(state_dir, "GONE", "fuzz_fail")
    rows = _read_telemetry(state_dir)
    skip = [r for r in rows if r.get("event") == "skip_degenerate_escalation"]
    assert skip
    r = skip[-1]
    assert r["task_id"] == "GONE" and r["phase"] == "autowork"
    assert r["detail"] == "missing_task_json"
    assert "ts" in r and "pid" in r


# --------------------------------------------------------------------------- #
# Group 3 — self-heal prompt scrub
# --------------------------------------------------------------------------- #
def test_TC3_1_retry_prompt_forbids_allowlist_and_repo_writes(workroot, tmp_path, monkeypatch):
    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    state_dir = tmp_path / "state"
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    (state_dir / "tasks" / "blocked" / "P.json").write_text(json.dumps(
        {"task_id": "P", "objective": "fix", "files_touched": ["pkg/a.py"]}))
    dae._escalate_to_autobrief(state_dir, "P", "fuzz_fail")
    argv = captured["cmd"]
    p_idx = argv.index("-p")
    prompt = argv[p_idx + 1]
    assert "OUTBOX" in prompt and "outbox" in prompt
    assert "Do NOT" in prompt
    # regression guard: the ex-phantom-task-no-promote legacy instruction is gone
    assert "as a new line to the allowlist" not in prompt
    assert "Append `" not in prompt
    # OUTBOX_PATH was resolved to a concrete path inside the workdir
    assert "{OUTBOX_PATH}" not in prompt
    assert "/outbox" in prompt


def test_TC3_2_inactivity_prompt_outbox_only(workroot, tmp_path, monkeypatch):
    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    state_dir = tmp_path / "state"
    (state_dir / "tasks").mkdir(parents=True)
    (state_dir / "tasks" / "Q.json").write_text(json.dumps({"task_id": "Q"}))
    cfg = {"control": {"autobrief_default_agent": "claude"},
           "agents": {"claude": {"command": "claude", "args": ["-p"]}}}
    dae._escalate_inactivity(state_dir, cfg)
    argv = captured["cmd"]
    p_idx = argv.index("-p")
    prompt = argv[p_idx + 1]
    assert "do NOT run git" in prompt
    assert "auto-promote allowlist" in prompt
    assert "outbox" in prompt and "diagnosis.md" in prompt
    assert "{OUTBOX_PATH}" not in prompt


def test_TC3_3_selfheal_gemini_default_spawns_hookless_agy_GAP(workroot, tmp_path, monkeypatch):
    """GAP (med): forcing autobrief_default_agent=gemini with no agents.<gemini>
    config resolves to bare ``agy -p --sandbox`` — NO --settings/BeforeTool hook.
    The self-heal containment for agy rests ONLY on prompt scrub + cwd + §1b; the
    _SHELL_ALLOW gate never loads."""
    captured = {}
    _patch_daemon_popen(monkeypatch, captured)
    state_dir = tmp_path / "state"
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    (state_dir / "tasks" / "blocked" / "G.json").write_text(json.dumps(
        {"task_id": "G", "objective": "x", "files_touched": ["pkg/a.py"]}))
    # config.yaml on disk will be read by _escalate_to_autobrief; to FORCE the
    # gemini fallback we point it at a tmp config with the gemini default + no
    # agents entry, by chdir'ing so 'harness/config.yaml' is absent and the
    # state_dir.parent/harness/config.yaml fallback is our crafted one.
    crafted = state_dir.parent / "harness"
    crafted.mkdir(parents=True)
    (crafted / "config.yaml").write_text(
        "control:\n  autobrief_default_agent: gemini\nagents: {}\n")
    monkeypatch.chdir(tmp_path)  # so cwd-relative 'harness/config.yaml' is absent
    dae._escalate_to_autobrief(state_dir, "G", "fuzz_fail")
    argv = captured["cmd"]
    assert argv[0].endswith("agy"), argv
    assert "--sandbox" in argv
    assert "--settings" not in argv, "hook gate never wired for bare agy"
    assert not any("gemini_settings.json" in str(a) for a in argv)


# --------------------------------------------------------------------------- #
# Group 4 — approval gate enforcement (§1b) + control_gate
# --------------------------------------------------------------------------- #
def test_TC4_1_apply_gate_rejects_non_member():
    err = gi._enforce_apply_scope(["a/c.py"], allowed_files={"a/b.py"},
                                  meta_task_type=None, approval_ok=False)
    assert err and "not a member" in err


def test_TC4_2_apply_gate_blocks_harness_without_approval():
    f = gi._enforce_apply_scope
    assert f(["harness/x.py"], allowed_files=None, meta_task_type="feature", approval_ok=False)
    assert f(["harness/x.py"], allowed_files=None, meta_task_type="harness_self_fix", approval_ok=False)
    assert f(["harness/x.py"], allowed_files=None, meta_task_type="harness_self_fix", approval_ok=True) is None


def test_TC4_3_matches_sensitive_recursive_semantics():
    m = gi._matches_sensitive
    g = gi._SENSITIVE_APPLY_GLOBS
    assert m("harness/a.py", g)
    assert m("harness/sub/a.py", g)
    assert m("config/x", g)
    assert m("scripts/y", g)
    assert m("harness", g)              # bare base name matches
    assert not m("harnessx/a.py", g)
    assert not m("harnessfoo", g)
    assert not m("notharness/a.py", g)


def test_TC4_4_apply_approval_granted_parsing(tmp_path):
    sd = tmp_path / "state"
    (sd / "control" / "decisions").mkdir(parents=True)
    g = orch._apply_approval_granted
    assert g(sd, "T") is False                                   # absent
    p = sd / "control" / "decisions" / "T.json"
    p.write_text(json.dumps({"decision": "approve"}))
    assert g(sd, "T") is True
    p.write_text(json.dumps({"decision": "approved"}))
    assert g(sd, "T") is True
    p.write_text(json.dumps({"decision": "reject"}))
    assert g(sd, "T") is False
    p.write_text("{not json")
    assert g(sd, "T") is False
    p.write_text(json.dumps([]))                                 # non-dict
    assert g(sd, "T") is False
    p.write_text(json.dumps({"decision": " APPROVE "}))          # strip+lower
    assert g(sd, "T") is True


def test_TC4_5_commit_path_None_allowed_still_hits_sensitive_gate():
    """allowed_files=None opts out of membership but the sensitive gate fires."""
    f = gi._enforce_apply_scope
    assert f(["harness/x.py"], allowed_files=None, meta_task_type="feature",
             approval_ok=False), "sensitive gate must fire even with None membership"
    # a non-sensitive path with None membership passes
    assert f(["pkg/x.py"], allowed_files=None, meta_task_type=None,
             approval_ok=False) is None


def test_TC4_6_await_decision_noop_timeout_and_approve(tmp_path):
    sd = tmp_path / "state"
    # phase not in require_approval -> 'auto' immediately
    cfg_noop = {"control": {"require_approval": []}}
    assert cg.await_decision(sd, "T", "synthesis", cfg_noop) == "auto"
    # phase IN require_approval, no decision file, tiny timeout -> 'timeout'
    cfg = {"control": {"require_approval": ["accepted"]}}
    fired = {}
    r = cg.await_decision(sd, "T", "accepted", cfg, timeout=0.02,
                          poll_interval=0.001,
                          emit_timeout=lambda t, p: fired.setdefault("to", (t, p)))
    assert r == "timeout"
    assert fired["to"] == ("T", "accepted")
    # drop an approve decision first -> returns 'approve'
    dec = cg.decisions_dir(sd, cfg)
    dec.mkdir(parents=True, exist_ok=True)
    (dec / "T.json").write_text(json.dumps({"decision": "approve"}))
    assert cg.await_decision(sd, "T", "accepted", cfg, timeout=0.5,
                             poll_interval=0.001) == "approve"


def test_TC4_7_check_pause_fail_open(tmp_path):
    sd = tmp_path / "state"
    sd.mkdir()
    cfg = {}
    flag = cg.pause_flag_path(sd, cfg)
    flag.parent.mkdir(parents=True, exist_ok=True)
    assert cg.check_pause(sd, cfg) is False           # absent
    flag.write_text("paused")
    assert cg.check_pause(sd, cfg) is True
    flag.unlink()
    flag.mkdir()                                       # directory -> IsADirectoryError
    assert cg.check_pause(sd, cfg) is False            # fail-open


# --------------------------------------------------------------------------- #
# Group 5 — _SHELL_ALLOW / _decide_shell hardening (hook-loading agents)
# --------------------------------------------------------------------------- #
@pytest.fixture
def hook_roots(tmp_path, monkeypatch):
    """Point _read_allowed_roots at tmp dirs via env so cat tests are hermetic."""
    work = tmp_path / "agentwork"
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(work))
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path / "state"))
    monkeypatch.setenv("JANUSMASK_PROJECT_DIR", str(tmp_path / "proj"))
    monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
    monkeypatch.setenv("JANUSMASK_AGENT", "gemini")
    return tmp_path


@pytest.mark.parametrize("cmd", [
    "tee x", "cp a b", "mv a b", "ln -s a b", "chmod 755 x",
    "rm -rf /tmp/x", 'python3 -c "1"', "python3 harness/sandbox.py",
])
def test_TC5_1_dropped_write_verbs_denied(cmd):
    d = gpt._decide_shell({"command": cmd})
    assert d["decision"] == "deny", cmd


def test_TC5_1b_deny_reason_string_is_stale_GAP():
    """GAP (low): the deny reason still advertises the OLD allowlist
    (tee/cp/mv/ln/cat<</python3 -c/sandbox.py/rm -rf) after §3.3 dropped them.
    Decision is correct; the message lies to the agent."""
    d = gpt._decide_shell({"command": "cp a b"})
    assert d["decision"] == "deny"
    reason = d.get("reason", "")
    # The stale advertisement is still present -> documents the UX/doc bug.
    assert "tee" in reason and "cp" in reason and "rm -rf" in reason
    assert "python3 -c" in reason and "harness/sandbox.py" in reason


@pytest.mark.parametrize("cmd", [
    "pytest", "pytest tests/x.py", "python3 -m pytest", "python -m pytest",
    "mkdir -p x", "touch x",
])
def test_TC5_2_retained_verbs_allowed(cmd):
    assert gpt._decide_shell({"command": cmd})["decision"] == "allow", cmd


def test_TC5_3_pytest_is_arbitrary_code_documented():
    """pytest collection auto-imports conftest/plugins = arbitrary code; allowed
    by design. _SHELL_ALLOW is explicitly NOT the code-exec barrier."""
    assert gpt._decide_shell({"command": "pytest -p no:cacheprovider"})["decision"] == "allow"


def test_TC5_4_bare_cat_root_confinement(hook_roots):
    work_dir = shared_env._work_dir("s", agent="gemini")
    work_dir.mkdir(parents=True, exist_ok=True)
    inside = work_dir / "inbox" / "task.json"
    inside.parent.mkdir(parents=True, exist_ok=True)
    inside.write_text("{}")
    assert gpt._decide_shell({"command": f"cat {inside}"}, "s")["decision"] == "allow"
    # absolute path outside roots -> deny
    assert gpt._decide_shell({"command": "cat /etc/passwd"}, "s")["decision"] == "deny"
    # flags -> deny
    assert gpt._decide_shell({"command": "cat -n x"}, "s")["decision"] == "deny"
    # stdin / empty -> deny
    assert gpt._decide_shell({"command": "cat -"}, "s")["decision"] == "deny"


def test_TC5_5_decide_write_or_replace_outbox_containment(hook_roots):
    work_dir = shared_env._work_dir("s", agent="gemini")
    outbox = work_dir / "outbox"
    outbox.mkdir(parents=True, exist_ok=True)
    # path OUTSIDE outbox -> deny
    d = gpt._decide_write_or_replace(
        "write_file", {"file_path": str(work_dir / "escape.py"), "content": "x=1"},
        "s", "gemini", "synthesis", "synthesis", 1)
    assert d["decision"] == "deny"
    # plan_draft.json in synthesis mode -> mode mismatch deny
    d2 = gpt._decide_write_or_replace(
        "write_file", {"file_path": str(outbox / "plan_draft.json"), "content": "{}"},
        "s", "gemini", "synthesis", "synthesis", 1)
    assert d2["decision"] == "deny"


def test_TC5_6_hook_gate_inert_for_bare_agy_GAP():
    """GAP (high): the production gemini command is bare ``agy -p --sandbox`` with
    NO --settings/BeforeTool hook, so _SHELL_ALLOW / _decide_shell NEVER load for
    the real agent. Group-5 hardening protects only a hypothetical settings-wired
    invocation. Read the real config.yaml and prove the wiring is absent."""
    cfg = orch.load_config()
    gem = cfg["agents"]["gemini"]
    assert str(gem["command"]).endswith("/agy"), gem["command"]
    args = gem["args"]
    assert "--sandbox" in args
    assert "--settings" not in args
    assert not any("gemini_settings.json" in str(a) for a in args)


# --------------------------------------------------------------------------- #
# Group 6 — _env workdir fallback
# --------------------------------------------------------------------------- #
def test_TC6_1_fallback_outside_repo_not_dead_state_workdirs(workroot, tmp_path, monkeypatch):
    monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
    monkeypatch.setenv("JANUSMASK_STATE_DIR", str(tmp_path / "state"))
    wd = shared_env._work_dir("s", agent="gemini")
    assert _is_outside_repo(wd)
    assert "workdirs" not in str(wd)
    assert str(wd).startswith(str(workroot.resolve()))
    assert wd.name == "s" and wd.parent.name == "gemini"
    # env wins when set
    monkeypatch.setenv("JANUSMASK_WORK_DIR", str(tmp_path / "explicit"))
    assert shared_env._work_dir("s", agent="gemini") == (tmp_path / "explicit").resolve()


def test_TC6_2_empty_agent_segment_split_brain_GAP(workroot, monkeypatch):
    """GAP (med): when both the agent arg AND JANUSMASK_AGENT are absent,
    _resolve_agent('') -> '' and the fallback workdir gets an EMPTY agent segment
    (<workroot>//<sid>), diverging from the orchestrator's <workroot>/<agent>/<sid>.
    Latent split-brain if any hook calls _work_dir without an explicit agent."""
    monkeypatch.delenv("JANUSMASK_WORK_DIR", raising=False)
    monkeypatch.delenv("JANUSMASK_AGENT", raising=False)
    wd = shared_env._work_dir("sid")  # no agent kwarg, no env
    # the empty agent segment collapses: <workroot>//sid -> parts show empty agent
    expected = (agent_workroot() / "" / "sid").resolve()
    assert wd == expected
    # contrast: the orchestrator-side path with a real agent differs
    real = (agent_workroot() / "gemini" / "sid").resolve()
    assert wd != real, "empty-agent fallback diverges from orchestrator path"
