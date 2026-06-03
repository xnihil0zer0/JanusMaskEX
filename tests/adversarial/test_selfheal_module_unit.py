"""Self-heal S2a oracle (module-direct): the NEW leaf module ``harness/selfheal.py``
must own the self-heal primitives in isolation, so the daemon needs only a 1-line
re-export import (S2b) and the harvest/eligibility wiring (S3).

RED on HEAD: ``harness/selfheal.py`` does not exist. This oracle exercises the module
DIRECTLY (``import harness.selfheal``), NOT via the ``autowork_daemon`` namespace, so it
is satisfiable by a single-file new-module task. The daemon-namespaced twins
(``test_selfheal_flag_eligibility`` / ``test_selfheal_harvest_brief``) go green once the
S2b re-export import lands.

Contract:
  _selfheal_auto_promote_enabled(config) -> bool   # default-deny, tolerant of non-dict
  _is_selfheal_brief(slug) -> bool                 # True iff slug startswith 'selfheal_'
  _harvest_selfheal_briefs(state_dir, repo_root, config) -> int
      # scans harness.paths.agent_workroot() outboxes for brief_hooks_<id>_fix.md;
      # flag on -> copy each to <repo_root>/brief_hooks_selfheal_<id>.md (idempotent);
      # flag off -> no-op returning 0. Never writes auto_promote.allowlist.
"""
from __future__ import annotations

import pathlib

import harness.paths as _paths


def _seed_outbox(workroot: pathlib.Path, agent: str, task_id: str) -> None:
    sess = workroot / agent / f"{agent}-r1-{task_id}-deadbeef" / "outbox"
    sess.mkdir(parents=True)
    (sess / f"brief_hooks_{task_id}_fix.md").write_text(
        "# Title\nCorrected spec for the failed task.\n", encoding="utf-8"
    )


def test_module_is_importable_and_leaf() -> None:
    import harness.selfheal as s  # must import without pulling autowork_daemon (no cycle)
    for name in ("_selfheal_auto_promote_enabled", "_is_selfheal_brief", "_harvest_selfheal_briefs"):
        assert hasattr(s, name), f"harness.selfheal.{name} missing"


def test_flag_helper_default_deny() -> None:
    import harness.selfheal as s
    assert s._selfheal_auto_promote_enabled({"autowork": {"selfheal_auto_promote": True}}) is True
    assert s._selfheal_auto_promote_enabled({"autowork": {"selfheal_auto_promote": False}}) is False
    assert s._selfheal_auto_promote_enabled({"autowork": {}}) is False
    assert s._selfheal_auto_promote_enabled({}) is False
    assert s._selfheal_auto_promote_enabled(None) is False  # tolerant of non-dict


def test_is_selfheal_brief() -> None:
    import harness.selfheal as s
    assert s._is_selfheal_brief("selfheal_method_d_05") is True
    assert s._is_selfheal_brief("other_brief") is False
    assert s._is_selfheal_brief(None) is False


def test_harvest_delivers_when_flag_on(tmp_path, monkeypatch) -> None:
    import harness.selfheal as s
    workroot = tmp_path / "agentwork"; workroot.mkdir()
    repo = tmp_path / "repo"; repo.mkdir()
    state = tmp_path / "state"; (state / "tasks").mkdir(parents=True)
    tid = "method_d_05_taxonomy_flip"
    _seed_outbox(workroot, "claude", tid)
    monkeypatch.setattr(_paths, "agent_workroot", lambda: workroot)
    cfg = {"autowork": {"selfheal_auto_promote": True}}

    n = s._harvest_selfheal_briefs(state, repo, cfg)
    dest = repo / f"brief_hooks_selfheal_{tid}.md"
    assert dest.exists(), "self-heal brief must be delivered into repo_root when flag on"
    assert n >= 1
    assert s._harvest_selfheal_briefs(state, repo, cfg) == 0, "harvest must be idempotent"


def test_harvest_noop_when_flag_off(tmp_path, monkeypatch) -> None:
    import harness.selfheal as s
    workroot = tmp_path / "agentwork"; workroot.mkdir()
    repo = tmp_path / "repo"; repo.mkdir()
    state = tmp_path / "state"; (state / "tasks").mkdir(parents=True)
    tid = "method_d_05_taxonomy_flip"
    _seed_outbox(workroot, "claude", tid)
    monkeypatch.setattr(_paths, "agent_workroot", lambda: workroot)
    cfg = {"autowork": {"selfheal_auto_promote": False}}

    n = s._harvest_selfheal_briefs(state, repo, cfg)
    assert n == 0 and not (repo / f"brief_hooks_selfheal_{tid}.md").exists(), (
        "harvest must be a no-op when autowork.selfheal_auto_promote is false"
    )
