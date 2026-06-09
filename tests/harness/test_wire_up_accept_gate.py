"""RED edge-asserting oracle for the accept-time wire-up gate
(epic: wire_up_phase, leaf: wire-up-accept-gate).

THE TRAP this oracle defends against: a worker could land the gate's module yet
forget to CALL it on the live accept path, leaving it orphaned. So this oracle does
NOT re-test reachability (that is the primitive's oracle). It proves the WIRING EDGE:
the real harness.orchestrator._auto_commit_accepted, with the wire_up gate enabled,
(1) actually calls orchestrator.check_wired for a new-module candidate, and (2) honors
its verdict -- an ORPHAN verdict rolls the staging commit back and does NOT merge to
the parent, while a WIRED verdict lets the accept proceed. Both are driven END-TO-END
through the real function against a real temp git repo (no agents), reusing the
test_phase_b_mutation_gate_adversarial fixture style.

Seams the implementation must expose (monkeypatched here):
  - orchestrator.check_wired           (module-level name, so the call site is spyable)
  - orchestrator._wire_up_gate_enabled (predicate reading the autowork.wire_up_gate flag)
"""
import json
import subprocess

import pytest

import harness.orchestrator as orchestrator
from harness.orchestrator import _auto_commit_accepted

_TARGET_REL = "new_feature.py"
_TEST_REL = "test_new_feature.py"
_VCMD = f"python -m pytest -p no:cacheprovider -q {_TEST_REL}"
_MODULE_OUTPUT = "def feature():\n    return 42\n"
_TEST_SRC = "from new_feature import feature\n\ndef test_feature():\n    assert feature() == 42\n"


def _git(cwd, *args):
    return subprocess.run(["git", "-C", str(cwd), *args], capture_output=True, text=True, check=True)


def _make_parent(tmp_path):
    """Parent git repo + state_dir; the authored test is committed so vcmd passes in
    the sibling staging worktree. The target module is NEW (not committed), so the
    candidate creates it -- the new-module case the wire_up gate guards."""
    worktree = tmp_path / "worktree"
    worktree.mkdir()
    _git(worktree, "init", "-q", "-b", "main")
    _git(worktree, "config", "user.name", "JanusMask Test")
    _git(worktree, "config", "user.email", "test@janusmask.local")
    state_dir = worktree / "state"
    (state_dir / "output").mkdir(parents=True)
    (state_dir / "tasks" / "processed").mkdir(parents=True)
    (worktree / _TEST_REL).write_text(_TEST_SRC, encoding="utf-8")
    _git(worktree, "add", _TEST_REL)
    _git(worktree, "commit", "-q", "-m", "initial")
    return state_dir, worktree


def _task(task_id):
    return {
        "task_id": task_id,
        "meta_task_type": "harness_plumbing",
        "files_touched": [_TARGET_REL],
        "verification_command": _VCMD,
    }


def _rows(path):
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_accept_path_calls_check_wired_for_new_module(tmp_path, monkeypatch):
    state_dir, _ = _make_parent(tmp_path)
    monkeypatch.setattr(orchestrator, "_wire_up_gate_enabled", lambda *a, **k: True, raising=False)
    seen = {}

    def spy(repo_root, module_rel, *a, **k):
        seen["module_rel"] = module_rel
        return orchestrator.WireResult(wired=True, importers=["x"], reason="", fix_hint="")

    monkeypatch.setattr(orchestrator, "check_wired", spy, raising=False)

    task_id = "WUP_CALLS"
    (state_dir / "output" / f"{task_id}.py").write_text(_MODULE_OUTPUT, encoding="utf-8")
    _auto_commit_accepted(state_dir, _task(task_id), task_id)

    assert seen.get("module_rel") and "new_feature" in seen["module_rel"], (
        "the live accept path must call check_wired for the new module"
    )


def test_orphan_verdict_blocks_merge(tmp_path, monkeypatch):
    state_dir, worktree = _make_parent(tmp_path)
    head_before = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    monkeypatch.setattr(orchestrator, "_wire_up_gate_enabled", lambda *a, **k: True, raising=False)
    monkeypatch.setattr(
        orchestrator, "check_wired",
        lambda *a, **k: orchestrator.WireResult(wired=False, importers=[], reason="orphan", fix_hint="wire it"),
        raising=False,
    )

    task_id = "WUP_ORPHAN"
    (state_dir / "output" / f"{task_id}.py").write_text(_MODULE_OUTPUT, encoding="utf-8")
    committed = _auto_commit_accepted(state_dir, _task(task_id), task_id)

    assert committed is False, "an orphan candidate must be rejected"
    head_after = _git(worktree, "rev-parse", "HEAD").stdout.strip()
    assert head_after == head_before, "an orphan must NOT be merged into the parent"
    assert any(r.get("event") == "orphan_unwired" for r in _rows(state_dir / "impl_progress.jsonl")), (
        "the orphan rejection must be recorded in the ledger"
    )


def test_wired_verdict_allows_accept(tmp_path, monkeypatch):
    state_dir, _ = _make_parent(tmp_path)
    monkeypatch.setattr(orchestrator, "_wire_up_gate_enabled", lambda *a, **k: True, raising=False)
    monkeypatch.setattr(
        orchestrator, "check_wired",
        lambda *a, **k: orchestrator.WireResult(wired=True, importers=["live"], reason="", fix_hint=""),
        raising=False,
    )

    task_id = "WUP_WIRED"
    (state_dir / "output" / f"{task_id}.py").write_text(_MODULE_OUTPUT, encoding="utf-8")
    committed = _auto_commit_accepted(state_dir, _task(task_id), task_id)

    assert committed is True, "a wired new module must be accepted"


def test_gate_disabled_is_a_noop(tmp_path, monkeypatch):
    # With the flag OFF, check_wired must not even be consulted (preserves prior behaviour).
    state_dir, _ = _make_parent(tmp_path)
    monkeypatch.setattr(orchestrator, "_wire_up_gate_enabled", lambda *a, **k: False, raising=False)
    called = {"hit": False}

    def spy(*a, **k):
        called["hit"] = True
        return orchestrator.WireResult(wired=False, importers=[], reason="", fix_hint="")

    monkeypatch.setattr(orchestrator, "check_wired", spy, raising=False)

    task_id = "WUP_OFF"
    (state_dir / "output" / f"{task_id}.py").write_text(_MODULE_OUTPUT, encoding="utf-8")
    _auto_commit_accepted(state_dir, _task(task_id), task_id)
    assert called["hit"] is False, "the wire_up gate must be a no-op when the flag is OFF"
