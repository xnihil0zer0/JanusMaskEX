"""Adversarial bar for autowork_eligibility_surface.

xfail-strict until the autowork_eligibility_surface dispatch adds
``compute_autowork_eligibility`` to ``harness/brief_status.py``. On accept,
drop the xfail markers so these become regression guards.

The helper reproduces (does not import) the daemon's age + allowlist gate
from ``harness/autowork_daemon.py:_auto_promote_brief_eligible`` so the WebUI
can report which briefs are autowork-eligible and why the rest are blocked.

Imports of the not-yet-existing symbol are deferred INTO the test bodies so
pre-dispatch the failure surfaces as xfail (not a collection error).
"""

from __future__ import annotations

import pathlib
import tempfile

import pytest


def _seed_brief(repo_root: pathlib.Path, slug: str) -> None:
    (repo_root / f"brief_hooks_{slug}.md").write_text("# Title\ndemo\n", encoding="utf-8")


def test_no_allowlist_denies_all():
    """REPL-1/G-EMPTYALLOW: a missing allowlist is a DENY-ALL safety boundary,
    not allow-all. A fresh brief with no allowlist file must be blocked with
    reason 'allowlist_missing' so a fresh clone never auto-dispatches every brief.
    """
    from harness.brief_status import compute_autowork_eligibility

    r = pathlib.Path(tempfile.mkdtemp())
    s = pathlib.Path(tempfile.mkdtemp())
    _seed_brief(r, "demo_slug")
    res = compute_autowork_eligibility(r, s)
    assert "demo_slug" not in res["eligible"], res
    assert res["allowlist_present"] is False, res
    assert res["allowlist_slugs"] == [], res
    assert res["eligible_count"] == 0, res
    assert any(b["slug"] == "demo_slug" and b["reason"] == "allowlist_missing" for b in res["blocked"]), res


def test_allowlist_blocks_unlisted():
    from harness.brief_status import compute_autowork_eligibility

    r = pathlib.Path(tempfile.mkdtemp())
    s = pathlib.Path(tempfile.mkdtemp())
    _seed_brief(r, "demo_slug")
    aw = s / "control" / "autowork"
    aw.mkdir(parents=True)
    (aw / "auto_promote.allowlist").write_text("other_slug\n# a comment\n", encoding="utf-8")
    res = compute_autowork_eligibility(r, s)
    assert res["allowlist_present"] is True, res
    assert res["allowlist_slugs"] == ["other_slug"], res
    assert any(b["slug"] == "demo_slug" and b["reason"] == "not_in_allowlist" for b in res["blocked"]), res


def test_stale_brief_blocked():
    from harness.brief_status import compute_autowork_eligibility

    r = pathlib.Path(tempfile.mkdtemp())
    s = pathlib.Path(tempfile.mkdtemp())
    _seed_brief(r, "demo_slug")
    # now far in the future -> brief is older than max_age_sec -> stale
    res = compute_autowork_eligibility(r, s, now=10 ** 12)
    assert any(b["slug"] == "demo_slug" and b["reason"] == "stale" for b in res["blocked"]), res


def test_return_shape_keys():
    from harness.brief_status import compute_autowork_eligibility

    r = pathlib.Path(tempfile.mkdtemp())
    s = pathlib.Path(tempfile.mkdtemp())
    res = compute_autowork_eligibility(r, s)
    expected = {
        "eligible",
        "blocked",
        "eligible_count",
        "blocked_count",
        "allowlist_present",
        "allowlist_slugs",
        "max_age_sec",
        "dispatchable",
        "parked",
    }
    assert expected <= set(res), res
    assert res["max_age_sec"] == 604800, res
    assert isinstance(res["dispatchable"], list) and isinstance(res["parked"], dict), res


def _seed_plan(repo_root: pathlib.Path, slug: str, task_ids: list[str]) -> None:
    import json

    (repo_root / f"plan_hooks_{slug}.json").write_text(
        json.dumps({"tasks": [{"task_id": t} for t in task_ids]}), encoding="utf-8"
    )


def test_parked_surfaces_zombie_processed_tasks():
    """WUI-2: a task parked in processed/ unaccepted (a zombie) shows up under
    ``parked[slug]`` regardless of allowlist eligibility, so the panel can badge
    it instead of silently presenting the brief as idle/eligible."""
    import json

    from harness.brief_status import compute_autowork_eligibility

    r = pathlib.Path(tempfile.mkdtemp())
    s = pathlib.Path(tempfile.mkdtemp())
    _seed_brief(r, "zslug")
    _seed_plan(r, "zslug", ["ZT1"])
    proc = s / "tasks" / "processed"
    proc.mkdir(parents=True)
    (proc / "ZT1.json").write_text(json.dumps({"task_id": "ZT1"}), encoding="utf-8")
    res = compute_autowork_eligibility(r, s)
    assert res["parked"].get("zslug") == ["ZT1"], res


def test_dispatchable_is_eligible_with_unstaged_work():
    """WUI-2: ``dispatchable`` = allowlisted + fresh + has unstaged plan work.
    An allowlisted brief whose plan task is not staged anywhere is dispatchable;
    a parked-only brief is NOT."""
    from harness.brief_status import compute_autowork_eligibility

    r = pathlib.Path(tempfile.mkdtemp())
    s = pathlib.Path(tempfile.mkdtemp())
    _seed_brief(r, "dslug")
    _seed_plan(r, "dslug", ["DT1"])
    aw = s / "control" / "autowork"
    aw.mkdir(parents=True)
    (aw / "auto_promote.allowlist").write_text("dslug\n", encoding="utf-8")
    res = compute_autowork_eligibility(r, s)
    assert "dslug" in res["eligible"], res
    assert "dslug" in res["dispatchable"], res
