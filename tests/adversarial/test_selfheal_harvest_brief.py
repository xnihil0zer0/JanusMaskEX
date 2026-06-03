"""Self-heal Link #3a oracle: the daemon must HARVEST a diagnosing agent's
self-heal brief out of its (out-of-repo) outbox into repo_root so the existing
``_auto_promote`` planner path can pick it up — gated by ``autowork.selfheal_auto_promote``.

RED on HEAD: ``autowork_daemon._harvest_selfheal_briefs`` does not exist, so the
self-heal brief is a dead-letter in the agent outbox and the loop never closes.
Contract: ``_harvest_selfheal_briefs(state_dir, repo_root, config) -> int`` scans
``agent_workroot()`` outboxes for ``brief_hooks_<task_id>_fix.md``; when the flag is
true copies each to ``<repo_root>/brief_hooks_selfheal_<task_id>.md`` (idempotent,
returns count); no-op returning 0 when the flag is false.
"""
from __future__ import annotations

import pathlib

import harness.paths as _paths
from harness import autowork_daemon as d


def _seed_outbox(workroot: pathlib.Path, agent: str, task_id: str) -> None:
    sess = workroot / agent / f"{agent}-r1-{task_id}-deadbeef" / "outbox"
    sess.mkdir(parents=True)
    (sess / f"brief_hooks_{task_id}_fix.md").write_text(
        "# Title\nCorrected spec for the failed task.\n", encoding="utf-8"
    )


def _patch_workroot(monkeypatch, workroot: pathlib.Path) -> None:
    monkeypatch.setattr(_paths, "agent_workroot", lambda: workroot)
    if hasattr(d, "agent_workroot"):
        monkeypatch.setattr(d, "agent_workroot", lambda: workroot)


def test_harvest_helper_exists() -> None:
    assert hasattr(d, "_harvest_selfheal_briefs"), (
        "autowork_daemon._harvest_selfheal_briefs missing — self-heal loop cannot close"
    )


def test_harvest_delivers_when_flag_on(tmp_path, monkeypatch) -> None:
    workroot = tmp_path / "agentwork"; workroot.mkdir()
    repo = tmp_path / "repo"; repo.mkdir()
    state = tmp_path / "state"; (state / "tasks").mkdir(parents=True)
    tid = "method_d_05_taxonomy_flip"
    _seed_outbox(workroot, "claude", tid)
    _patch_workroot(monkeypatch, workroot)
    cfg = {"autowork": {"selfheal_auto_promote": True}}

    n = d._harvest_selfheal_briefs(state, repo, cfg)
    dest = repo / f"brief_hooks_selfheal_{tid}.md"
    assert dest.exists(), "self-heal brief must be delivered into repo_root when flag on"
    assert n >= 1

    # idempotent: a second pass must not re-deliver an already-present brief
    n2 = d._harvest_selfheal_briefs(state, repo, cfg)
    assert n2 == 0, "harvest must be idempotent (already-delivered brief not re-copied)"


def test_harvest_noop_when_flag_off(tmp_path, monkeypatch) -> None:
    workroot = tmp_path / "agentwork"; workroot.mkdir()
    repo = tmp_path / "repo"; repo.mkdir()
    state = tmp_path / "state"; (state / "tasks").mkdir(parents=True)
    tid = "method_d_05_taxonomy_flip"
    _seed_outbox(workroot, "claude", tid)
    _patch_workroot(monkeypatch, workroot)
    cfg = {"autowork": {"selfheal_auto_promote": False}}

    n = d._harvest_selfheal_briefs(state, repo, cfg)
    assert n == 0 and not (repo / f"brief_hooks_selfheal_{tid}.md").exists(), (
        "harvest must be a no-op when autowork.selfheal_auto_promote is false"
    )
