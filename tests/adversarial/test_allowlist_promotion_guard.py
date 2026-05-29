"""GAP_M12 regression guard: no self-heal / auto-promote path may ever write the
``auto_promote.allowlist``. Promotion is an operator decision (memory:
ex-phantom-task-no-promote — never auto-append ``EX_fix`` or any ``<task>_fix``).

This is the one do-NOT invariant that had ZERO guarding tests (the other three —
single-agent acceptance, BYPASS_FUZZER_TYPES, full_stop sentinel — are covered).
The self-heal prompts at autowork_daemon.py:656/1683 only *instruct* the agent not
to touch the allowlist; nothing asserted that the harness code itself never does.

No agy/agent spawn: subprocess.Popen is mocked so the self-heal escalation captures
its command without launching anything.
"""
from __future__ import annotations

import json
import pathlib

import pytest

import harness.autowork_daemon as dae
from harness.paths import PROJECT_ROOT


_BASELINE_ALLOWLIST = (
    "# auto_promote.allowlist — operator-curated; deny-all baseline\n"
    "# (only an operator adds slugs, one at a time)\n"
)


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


@pytest.fixture
def state_with_allowlist(tmp_path, monkeypatch):
    """A state dir with a seeded allowlist and an out-of-repo agent workroot."""
    monkeypatch.setenv("JANUSMASK_AGENT_WORKROOT", str(tmp_path / "agentwork"))
    state_dir = tmp_path / "state"
    (state_dir / "control" / "autowork").mkdir(parents=True)
    (state_dir / "tasks" / "blocked").mkdir(parents=True)
    allow = state_dir / "control" / "autowork" / "auto_promote.allowlist"
    allow.write_text(_BASELINE_ALLOWLIST, encoding="utf-8")
    monkeypatch.setattr(dae.subprocess, "Popen", _FakePopen)
    return state_dir, allow


def _assert_allowlist_pristine(allow: pathlib.Path, task_id: str):
    txt = allow.read_text(encoding="utf-8")
    assert txt == _BASELINE_ALLOWLIST, "self-heal MUTATED the auto_promote.allowlist"
    assert "EX_fix" not in txt, "EX_fix was written to the allowlist"
    assert f"{task_id}_fix" not in txt, f"{task_id}_fix was written to the allowlist"
    # No bare slug line slipped in (only the 2 comment lines may exist).
    slugs = [ln for ln in txt.splitlines() if ln.strip() and not ln.lstrip().startswith("#")]
    assert slugs == [], f"unexpected promoted slugs appeared: {slugs}"


@pytest.mark.parametrize("task_id", ["EX", "RB_demo_task", "daemon_inactivity_stuck"])
def test_M12_retry_budget_selfheal_never_writes_allowlist(state_with_allowlist, task_id):
    """The retry-budget self-heal (_escalate_to_autobrief) literally names a
    ``{task_id}_fix`` slug in its prompt — assert it never promotes it."""
    state_dir, allow = state_with_allowlist
    (state_dir / "tasks" / "blocked" / f"{task_id}.json").write_text(json.dumps(
        {"task_id": task_id, "objective": "x", "files_touched": ["pkg/x.py"]}))
    dae._escalate_to_autobrief(state_dir, task_id, "fuzz_fail")
    _assert_allowlist_pristine(allow, task_id)


def test_M12_inactivity_selfheal_never_writes_allowlist(state_with_allowlist):
    """The inactivity self-heal (_escalate_inactivity) must not touch the allowlist."""
    state_dir, allow = state_with_allowlist
    config = {"control": {"autobrief_default_agent": "gemini"}, "agents": {}}
    try:
        dae._escalate_inactivity(state_dir, config)
    except Exception:
        # Even on an internal error it must not have mutated the allowlist.
        pass
    _assert_allowlist_pristine(allow, "daemon_inactivity_stuck")


def test_M12_selfheal_prompts_still_forbid_allowlist_edits():
    """Pin the PROCEDURAL guard: both self-heal prompts must keep telling the agent
    not to edit the allowlist (operator-only promotion). Catches a future prompt
    edit that silently drops the warning."""
    import inspect
    src = inspect.getsource(dae)
    # Both escalation builders must carry the do-not-edit-allowlist instruction.
    assert src.count("Do NOT edit the auto-promote allowlist") + \
        src.count("do NOT edit the auto-promote allowlist") >= 2, (
        "a self-heal prompt dropped the 'do not edit the allowlist' instruction")


def test_M12_no_harness_code_writes_the_allowlist():
    """Static tripwire: no harness/*.py constructs the allowlist path and then
    writes it. The ONLY sanctioned writers are scripts/bootstrap.sh (deny-all
    seed) and the operator WebUI PUT endpoint (tools/webui_control.py) — neither
    lives under harness/. A future code path that appends a slug trips this."""
    harness_dir = PROJECT_ROOT / "harness"
    offenders = []
    for py in harness_dir.rglob("*.py"):
        text = py.read_text(encoding="utf-8", errors="replace")
        if "auto_promote.allowlist" not in text:
            continue
        lines = text.splitlines()
        for i, ln in enumerate(lines):
            if "auto_promote.allowlist" not in ln:
                continue
            # Look at a small window around the path reference for a write op.
            window = "\n".join(lines[max(0, i - 1): i + 4])
            if any(w in window for w in (".write_text(", ".write(", "open(",)) and \
                    ("'w'" in window or '"w"' in window or "'a'" in window or
                     '"a"' in window or ".write_text(" in window):
                offenders.append(f"{py.relative_to(PROJECT_ROOT)}:{i + 1}")
    assert offenders == [], (
        f"harness code appears to WRITE the auto_promote.allowlist: {offenders}")
