"""Self-heal Link #5 (INTEGRATION/behavioral acceptance) oracle — REV25 §2 / §4(B).

This is the closed-loop seam check (principle P-I/P-IV): it drives the REAL
daemon path end-to-end on a CORRECTABLE failure (an AST-rule violation that
explicit guidance fixes — NOT a deterministic Gemini-eval case, which needs P5
that we are NOT building here) and asserts the loop actually CLOSES:

  reject terminal captures the AST reason  (selfheal_01)
    -> diagnosing agent writes brief_hooks_<task_id>_fix.md to its outbox
    -> the daemon HARVESTS it into repo_root                (selfheal_02 + module)
    -> the flag makes that harvested slug auto-promote-eligible (selfheal_03)
    -> the SAME task_id is re-stageable with a corrective constraint (selfheal_04)

It does NOT spawn live agents: it seeds the diagnosing-agent's outbox artifact
(the dead-letter the loop must read back) and an ``ast_validation_failed``
ledger reason, then exercises the real wiring:

  * ``harness.selfheal`` MUST exist as a NEW module (REV25 §2 architecture).
  * the daemon namespace MUST re-export the helpers (``from harness.selfheal
    import _selfheal_auto_promote_enabled, _harvest_selfheal_briefs,
    _is_selfheal_brief``) so the existing structural oracles keep passing.
  * ``_auto_promote`` MUST actually INVOKE the harvest (wiring, not just a
    defined-but-uncalled helper).
  * with the flag ON the harvested brief lands in repo_root and its
    ``selfheal_<task_id>`` slug is auto-promote-eligible WITHOUT mutating the
    operator allowlist; with the flag OFF the loop stays open (no harvest).

RED on HEAD: ``harness/selfheal.py`` does not exist and ``_auto_promote`` never
harvests, so the diagnosis brief is a permanent dead-letter and the loop never
closes.
"""
from __future__ import annotations

import json
import pathlib

import harness.paths as _paths
from harness import autowork_daemon as d

CORRECTABLE_TASK_ID = "selfheal_demo_bare_except"
# A correctable AST-rule violation: a bare-except that explicit guidance fixes
# ("catch a specific exception"). NOT a deterministic Gemini-eval case (needs P5).
AST_REASON = (
    "gemini: no_bare_except (Line 3): bare 'except:' is banned; "
    "catch a specific exception type"
)


def _new_module_exists() -> bool:
    repo = pathlib.Path(__file__).resolve().parents[2]
    return (repo / "harness" / "selfheal.py").is_file()


def _seed_outbox(workroot: pathlib.Path, agent: str, task_id: str) -> None:
    sess = workroot / agent / f"{agent}-r1-{task_id}-cafef00d" / "outbox"
    sess.mkdir(parents=True)
    (sess / f"brief_hooks_{task_id}_fix.md").write_text(
        "# Title\nCorrected spec: edit the target directly; catch a specific "
        "exception type. Keep the original task_id so dependents resolve.\n",
        encoding="utf-8",
    )


def _seed_ast_reason(state_dir: pathlib.Path, task_id: str) -> None:
    row = {
        "ts": "2026-06-03T00:00:00Z",
        "phase": "rejected",
        "task_id": task_id,
        "event": "ast_validation_failed",
        "detail": AST_REASON,
    }
    (state_dir / "impl_progress.jsonl").write_text(
        json.dumps(row) + "\n", encoding="utf-8"
    )


def _patch_workroot(monkeypatch, workroot: pathlib.Path) -> None:
    monkeypatch.setattr(_paths, "agent_workroot", lambda: workroot)
    if hasattr(d, "agent_workroot"):
        monkeypatch.setattr(d, "agent_workroot", lambda: workroot)


def test_selfheal_is_a_new_module() -> None:
    """REV25 §2 mandates the harvest/eligibility logic live in a NEW module
    harness/selfheal.py (not partial-edited into the 2400-line daemon)."""
    assert _new_module_exists(), (
        "harness/selfheal.py must exist (REV25 §2 new-module architecture)"
    )
    import importlib

    mod = importlib.import_module("harness.selfheal")
    for sym in ("_harvest_selfheal_briefs", "_selfheal_auto_promote_enabled",
                "_is_selfheal_brief"):
        assert hasattr(mod, sym), f"harness.selfheal must export {sym}"


def test_daemon_reexports_selfheal_helpers() -> None:
    """The daemon's import line must bring the helpers into the autowork_daemon
    namespace so the existing structural oracles + downstream callers resolve."""
    for sym in ("_harvest_selfheal_briefs", "_selfheal_auto_promote_enabled",
                "_is_selfheal_brief"):
        assert hasattr(d, sym), (
            f"autowork_daemon must re-export {sym} from harness.selfheal"
        )


def test_closed_loop_harvests_and_makes_eligible_when_flag_on(
    tmp_path, monkeypatch
) -> None:
    """END-TO-END on a correctable failure: with the flag ON, _auto_promote
    harvests the dead-letter brief into repo_root and the resulting
    selfheal_<task_id> slug is auto-promote-eligible WITHOUT touching the
    operator allowlist."""
    workroot = tmp_path / "agentwork"; workroot.mkdir()
    repo = tmp_path / "repo"; repo.mkdir()
    state = tmp_path / "state"; (state / "tasks").mkdir(parents=True)
    (state / "control" / "autowork").mkdir(parents=True)
    tid = CORRECTABLE_TASK_ID
    _seed_outbox(workroot, "claude", tid)
    _seed_ast_reason(state, tid)
    _patch_workroot(monkeypatch, workroot)
    cfg = {"autowork": {"selfheal_auto_promote": True}}

    # Drive the REAL daemon entrypoint (wiring check: harvest must be CALLED).
    d._auto_promote(repo, state, cfg)

    dest = repo / f"brief_hooks_selfheal_{tid}.md"
    assert dest.exists(), (
        "_auto_promote must harvest the diagnosing-agent dead-letter brief into "
        "repo_root so compute_brief_status discovers it (loop closes)"
    )

    # The harvested slug must be recognized as self-heal-originated and eligible
    # when the flag is on — WITHOUT the operator allowlist holding it.
    assert d._is_selfheal_brief(f"selfheal_{tid}") is True
    allow = state / "control" / "autowork" / "auto_promote.allowlist"
    assert not allow.exists(), "harvest must not write the operator allowlist"


def test_closed_loop_stays_open_when_flag_off(tmp_path, monkeypatch) -> None:
    """With the flag OFF the loop stays open: no harvest, repo_root untouched
    (byte-identical to today)."""
    workroot = tmp_path / "agentwork"; workroot.mkdir()
    repo = tmp_path / "repo"; repo.mkdir()
    state = tmp_path / "state"; (state / "tasks").mkdir(parents=True)
    (state / "control" / "autowork").mkdir(parents=True)
    tid = CORRECTABLE_TASK_ID
    _seed_outbox(workroot, "claude", tid)
    _seed_ast_reason(state, tid)
    _patch_workroot(monkeypatch, workroot)
    cfg = {"autowork": {"selfheal_auto_promote": False}}

    d._auto_promote(repo, state, cfg)

    assert not (repo / f"brief_hooks_selfheal_{tid}.md").exists(), (
        "flag-off must leave the loop open: no self-heal brief harvested"
    )
