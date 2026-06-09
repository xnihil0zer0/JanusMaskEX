"""RED oracle for the wire-up gate's repo_root selection
(harness_self_fix: wire_up_gate_staging_tree).

THE BUG: the accept-time wire-up gate runs AFTER the staged commit and BEFORE the
staging->parent merge. At that moment the just-committed new module lives ONLY in the
staging worktree (``staging_path``), not in the parent/working tree. But
``_run_wire_up_gate`` resolved ``repo_root = working_dir or worktree_root`` and called
``check_wired(repo_root, rel)`` against that PARENT tree -- which does not yet contain
the file. ``check_wired`` -> discover_modules(parent) -> ``rel`` not in the module set
-> ``wired=False`` -> EVERY new module (self OR external) is wrongly rejected as
``orphan_unwired``. (Masked until now because the gate flag was default-OFF and the
unit tests monkeypatch ``check_wired`` away.)

CONTRACT: the gate must consult ``check_wired`` against the tree where the
just-committed new module ACTUALLY lives -- the staging worktree. We prove it by
spying ``check_wired`` and asserting the ``repo_root`` it was handed actually contains
the new module on disk. RED before the fix (repo_root = parent, file absent),
GREEN after (repo_root = staging_path, file present).
"""
import subprocess
from pathlib import Path

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


def test_gate_checks_the_staging_tree_where_the_new_module_lives(tmp_path, monkeypatch):
    state_dir, _worktree = _make_parent(tmp_path)
    monkeypatch.setattr(orchestrator, "_wire_up_gate_enabled", lambda *a, **k: True, raising=False)
    seen = {}

    def spy(repo_root, module_rel, *a, **k):
        seen["repo_root"] = repo_root
        seen["module_rel"] = module_rel
        # The decisive assertion: the tree the gate checks MUST contain the
        # just-committed new module. True only when repo_root == staging_path.
        seen["module_on_disk"] = (Path(repo_root) / module_rel).exists()
        return orchestrator.WireResult(wired=True, importers=["x"], reason="", fix_hint="")

    monkeypatch.setattr(orchestrator, "check_wired", spy, raising=False)

    task_id = "WUP_STAGING_TREE"
    (state_dir / "output" / f"{task_id}.py").write_text(_MODULE_OUTPUT, encoding="utf-8")
    _auto_commit_accepted(state_dir, _task(task_id), task_id)

    assert seen.get("module_rel") and "new_feature" in seen["module_rel"], (
        "the gate must call check_wired for the new module"
    )
    assert seen.get("module_on_disk") is True, (
        "the wire-up gate must call check_wired against the tree where the just-committed "
        "new module actually lives (the staging worktree), not a parent tree that lacks it"
    )
