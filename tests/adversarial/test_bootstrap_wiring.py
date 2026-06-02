"""Adversarial oracle for the _auto_promote external-bootstrap wiring (REV22 §4-7).

Verifies that harness.autowork_daemon._auto_promote, reached by BOTH run_daemon
and main(--once) via _iteration, bootstraps an EXTERNAL target (plan working_dir
non-self) before staging, and leaves SELF-builds untouched.

RED on HEAD: _auto_promote has no bootstrap call, so a plan carrying a non-self
working_dir never invokes target_bootstrap → the spy is never called.
GREEN after fix: the spy fires exactly for the non-self plan.

Reachability from both entrypoints is asserted statically (the single seam,
_iteration→_auto_promote, is what run_daemon and main(--once) both drive).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from harness import autowork_daemon as awd


def _write_plan(repo_root: Path, slug: str, tid: str, working_dir: str | None) -> Path:
    plan = {
        "tasks": [{"task_id": tid, "files_touched": ["x.py"]}],
    }
    if working_dir is not None:
        plan["working_dir"] = working_dir
    p = repo_root / f"plan_hooks_{slug}.json"
    p.write_text(json.dumps(plan), encoding="utf-8")
    return p


def _common_monkeypatch(monkeypatch, repo_root, recs, calls):
    monkeypatch.setattr(awd, "compute_brief_status", lambda r, s: recs)
    monkeypatch.setattr(awd, "_auto_promote_disabled", lambda s: False)
    monkeypatch.setattr(awd, "_full_stop_path", lambda s: Path("/nonexistent/full_stop"))
    monkeypatch.setattr(awd, "_auto_promote_brief_eligible", lambda *a, **k: True)
    monkeypatch.setattr(awd, "_retry_blocked_tasks", lambda s, summ: None)
    # neutralize plan-kickoff path (no unplanned briefs)
    # stage_task is a no-op spy so we isolate the bootstrap behavior
    monkeypatch.setattr(awd, "stage_task", lambda *a, **k: None)

    import harness.target_bootstrap as tb

    def _spy(working_dir):
        calls.append(str(working_dir))
        return Path(working_dir)

    monkeypatch.setattr(tb, "bootstrap_target", _spy)


def test_external_plan_triggers_bootstrap(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    ext = tmp_path / "external_target"
    ext.mkdir()

    _write_plan(repo_root, "extslug", "T_EXT", str(ext))
    recs = [{
        "slug": "extslug",
        "has_plan": True,
        "unstaged_task_ids": ["T_EXT"],
        "plan_filename": "plan_hooks_extslug.json",
        "brief_mtime": 0,
        "state": "planned",
    }]
    calls: list[str] = []
    _common_monkeypatch(monkeypatch, repo_root, recs, calls)

    awd._auto_promote(repo_root, state_dir, config={})

    assert calls == [str(ext.resolve())] or calls == [str(ext)], (
        f"external plan must trigger bootstrap once; got {calls}"
    )


def test_self_plan_does_not_trigger_bootstrap(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    # working_dir == the harness PROJECT_ROOT (self) -> must NOT bootstrap
    self_dir = str(awd.PROJECT_DIR) if hasattr(awd, "PROJECT_DIR") else None
    from harness.paths import PROJECT_ROOT
    self_dir = str(PROJECT_ROOT)

    _write_plan(repo_root, "selfslug", "T_SELF", self_dir)
    recs = [{
        "slug": "selfslug",
        "has_plan": True,
        "unstaged_task_ids": ["T_SELF"],
        "plan_filename": "plan_hooks_selfslug.json",
        "brief_mtime": 0,
        "state": "planned",
    }]
    calls: list[str] = []
    _common_monkeypatch(monkeypatch, repo_root, recs, calls)

    awd._auto_promote(repo_root, state_dir, config={})

    assert calls == [], f"self-build must NOT bootstrap; got {calls}"


def test_no_working_dir_does_not_trigger_bootstrap(tmp_path, monkeypatch):
    repo_root = tmp_path / "repo"
    repo_root.mkdir()
    state_dir = tmp_path / "state"
    state_dir.mkdir()

    _write_plan(repo_root, "noslug", "T_NONE", None)  # no working_dir
    recs = [{
        "slug": "noslug",
        "has_plan": True,
        "unstaged_task_ids": ["T_NONE"],
        "plan_filename": "plan_hooks_noslug.json",
        "brief_mtime": 0,
        "state": "planned",
    }]
    calls: list[str] = []
    _common_monkeypatch(monkeypatch, repo_root, recs, calls)

    awd._auto_promote(repo_root, state_dir, config={})

    assert calls == [], f"plan with no working_dir must NOT bootstrap; got {calls}"


def test_seam_reachable_from_both_entrypoints():
    # The single wiring seam is _iteration -> _auto_promote; both run_daemon
    # and main(--once) drive _iteration. Assert the seam exists statically.
    import inspect

    iter_src = inspect.getsource(awd._iteration)
    assert "_auto_promote(" in iter_src, "_iteration must call _auto_promote"
    rd_src = inspect.getsource(awd.run_daemon)
    assert "_iteration(" in rd_src, "run_daemon must drive _iteration"
    main_src = inspect.getsource(awd.main)
    # main(--once) reaches the loop via run_daemon (single-iteration path)
    assert "run_daemon(" in main_src or "_iteration(" in main_src
