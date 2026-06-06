"""Oracle for failure-propagation epic status (child failure_propagation_status).

Validates the impl committed at eedfd29 against its REAL interfaces:

  * ``epic_has_failed_descendant(epic_slug, epic_children, status_index) -> bool``
    is a PURE transitive walk of the epic->child map consulting a slug->state
    index; True iff any transitive descendant is in a failed state
    ({'blocked','zombie'}); cycle-safe; empty/blank inputs -> False.
  * ``compute_epic_status(repo_root, state_dir, config) -> list[dict]`` reads epic
    ``plan_hooks_*.json`` from disk and, ONLY when
    ``config['hierarchical_planning']['failure_propagation']`` is truthy, blocks an
    epic that has a TRANSITIVE (multi-level) failed descendant — whereas with the
    flag off it keeps exact Phase-1 behaviour (direct children only).

Hermetic: epic_has_failed_descendant is pure; the compute_epic_status cases build
a fake repo under tmp_path and monkeypatch compute_brief_status to control the
slug->state index, so no real repo state is read.
"""
import json

import pytest

import harness.brief_status as bs


# --------------------------------------------------------------------------- #
# epic_has_failed_descendant  (pure)
# --------------------------------------------------------------------------- #

def test_transitive_failed_descendant_detected():
    children = {"root": ["mid"], "mid": ["leaf"]}
    index = {"mid": "in_flight", "leaf": "blocked"}
    assert bs.epic_has_failed_descendant("root", children, index) is True


def test_zombie_descendant_also_counts_as_failed():
    children = {"root": ["leaf"]}
    index = {"leaf": "zombie"}
    assert bs.epic_has_failed_descendant("root", children, index) is True


def test_no_failed_descendant_returns_false():
    children = {"root": ["mid"], "mid": ["leaf"]}
    index = {"mid": "in_flight", "leaf": "complete"}
    assert bs.epic_has_failed_descendant("root", children, index) is False


def test_blank_or_unknown_epic_slug_returns_false():
    assert bs.epic_has_failed_descendant("", {"x": ["y"]}, {"y": "blocked"}) is False
    assert bs.epic_has_failed_descendant("absent", {}, {}) is False


def test_cycle_in_child_map_is_safe():
    # root -> mid -> root (cycle); no failed state anywhere -> must terminate False.
    children = {"root": ["mid"], "mid": ["root"]}
    index = {"root": "in_flight", "mid": "in_flight"}
    assert bs.epic_has_failed_descendant("root", children, index) is False


# --------------------------------------------------------------------------- #
# compute_epic_status  (disk-reading; flag-gated transitive propagation)
# --------------------------------------------------------------------------- #

def _write_epic(repo_root, epic_slug, child_slugs):
    rec = {"plan_kind": "epic", "epic_slug": epic_slug, "child_slugs": list(child_slugs)}
    (repo_root / f"plan_hooks_{epic_slug}.json").write_text(json.dumps(rec), encoding="utf-8")


def _epic_entry(result, epic_slug):
    for r in result:
        if r.get("epic_slug") == epic_slug:
            return r
    raise AssertionError("epic %r not in %r" % (epic_slug, [r.get("epic_slug") for r in result]))


def _two_level_repo(tmp_path, monkeypatch):
    """root(epic) -> mid(epic) -> leaf(blocked). 'mid' itself is in_flight."""
    repo = tmp_path
    _write_epic(repo, "root", ["mid"])
    _write_epic(repo, "mid", ["leaf"])
    # Control the slug->state index that compute_epic_status derives.
    records = [
        {"slug": "root", "state": "planned"},
        {"slug": "mid", "state": "in_flight"},
        {"slug": "leaf", "state": "blocked"},
    ]
    monkeypatch.setattr(bs, "compute_brief_status", lambda repo_root, state_dir: records)
    return repo


def test_flag_on_transitive_failure_blocks_epic(tmp_path, monkeypatch):
    repo = _two_level_repo(tmp_path, monkeypatch)
    cfg = {"hierarchical_planning": {"failure_propagation": True}}
    result = bs.compute_epic_status(repo, tmp_path / "state", cfg)
    # 'root' has no DIRECT failed child (mid is in_flight) but a TRANSITIVE failed
    # descendant (leaf blocked) -> with the flag on it must be blocked.
    assert _epic_entry(result, "root")["state"] == "blocked"


def test_flag_off_keeps_phase1_behaviour(tmp_path, monkeypatch):
    repo = _two_level_repo(tmp_path, monkeypatch)
    cfg = {"hierarchical_planning": {"failure_propagation": False}}
    result = bs.compute_epic_status(repo, tmp_path / "state", cfg)
    # Flag off: only direct children matter. 'root's direct child 'mid' is
    # in_flight (not blocked) -> root is NOT blocked.
    assert _epic_entry(result, "root")["state"] != "blocked"
    assert _epic_entry(result, "root")["state"] == "in_flight"


def test_missing_failure_propagation_key_treated_as_off(tmp_path, monkeypatch):
    repo = _two_level_repo(tmp_path, monkeypatch)
    result = bs.compute_epic_status(repo, tmp_path / "state", {"hierarchical_planning": {}})
    assert _epic_entry(result, "root")["state"] == "in_flight"


def test_flag_on_non_vacuity_changes_root_outcome(tmp_path, monkeypatch):
    """The flag must MATTER: same fixture, on vs off -> different root state."""
    repo = _two_level_repo(tmp_path, monkeypatch)
    off = _epic_entry(bs.compute_epic_status(repo, tmp_path / "state", {"hierarchical_planning": {"failure_propagation": False}}), "root")["state"]
    on = _epic_entry(bs.compute_epic_status(repo, tmp_path / "state", {"hierarchical_planning": {"failure_propagation": True}}), "root")["state"]
    assert off != on
    assert on == "blocked" and off == "in_flight"


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
