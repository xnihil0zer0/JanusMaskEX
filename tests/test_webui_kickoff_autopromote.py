"""Oracle for the kickoff-autopromote feature.

RED on HEAD: ``ControlHandlers.post_planner_kickoff`` spawns the planner but does
NOT opt the brief into the autowork auto-promote allowlist, so a running daemon
will not auto-extract/dispatch a freshly kicked-off brief.

GREEN after fix: post_planner_kickoff appends the brief slug to
``state/control/autowork/auto_promote.allowlist`` (idempotent, preserves existing
entries/comments, best-effort under OSError) and reports
``auto_promote_allowlisted`` in its 200 response. An authenticated kickoff thus
authorizes hands-off autowork completion without weakening the deny-all default
for briefs that were never kicked off.
"""
from pathlib import Path

from tools import webui_control


def _handler(tmp_path, slug="demo"):
    repo = tmp_path / "repo"
    state = tmp_path / "state"
    logs = tmp_path / "logs"
    for d in (repo, state, logs):
        d.mkdir(parents=True, exist_ok=True)
    (repo / f"brief_hooks_{slug}.md").write_text("# Title\nx\n", encoding="utf-8")
    h = webui_control.ControlHandlers(state_dir=state, logs_dir=logs, repo_root=repo)
    # never actually spawn a planner
    h._spawn_tracked = lambda *a, **k: {"job_id": "j", "pid": 0}
    return h, state


def _allowlist_slugs(state: Path):
    p = state / "control" / "autowork" / "auto_promote.allowlist"
    if not p.exists():
        return None
    return [s.strip() for s in p.read_text(encoding="utf-8").splitlines()
            if s.strip() and not s.strip().startswith("#")]


def test_kickoff_allowlists_brief(tmp_path):
    h, state = _handler(tmp_path, "demo")
    status, body = h.post_planner_kickoff({"brief_slug": "demo"})
    assert status == 200, body
    assert body.get("auto_promote_allowlisted") is True
    assert "demo" in (_allowlist_slugs(state) or [])


def test_kickoff_allowlist_idempotent(tmp_path):
    h, state = _handler(tmp_path, "demo")
    h.post_planner_kickoff({"brief_slug": "demo"})
    h.post_planner_kickoff({"brief_slug": "demo"})
    slugs = _allowlist_slugs(state) or []
    assert slugs.count("demo") == 1


def test_kickoff_allowlist_preserves_existing(tmp_path):
    h, state = _handler(tmp_path, "demo")
    al = state / "control" / "autowork" / "auto_promote.allowlist"
    al.parent.mkdir(parents=True, exist_ok=True)
    al.write_text("# keep this comment\nother_slug\n", encoding="utf-8")
    status, body = h.post_planner_kickoff({"brief_slug": "demo"})
    assert status == 200, body
    text = al.read_text(encoding="utf-8")
    assert "# keep this comment" in text
    slugs = _allowlist_slugs(state) or []
    assert "other_slug" in slugs and "demo" in slugs


def test_kickoff_invalid_slug_rejected_regression(tmp_path):
    # Invalid slug must 400 BEFORE any allowlist write (no allowlist created).
    h, state = _handler(tmp_path, "demo")
    status, body = h.post_planner_kickoff({"brief_slug": "Bad Slug!"})
    assert status == 400
    assert _allowlist_slugs(state) is None
