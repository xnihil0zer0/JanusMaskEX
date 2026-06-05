"""Oracle for Brief 15a [SECURITY-GATED, owner-approved 2026-06-05]: epic-child
transitive allowlist admission in brief_status (read-derived).

RED on HEAD: compute_autowork_eligibility marks any brief not literally in
auto_promote.allowlist as blocked (brief_status.py:106-107). When an epic emits
N child briefs, those children are blocked 'not_in_allowlist' and the subtree
stalls (area_C_verified.md §M3/§9). Owner decision (2026-06-05): admit a child
TRANSITIVELY — eligible iff (child in allowlist) OR (its parent epic, derived
from epic plan_hooks child_slugs, is allowlisted) — WITHOUT mutating the
allowlist file, gated by hierarchical_planning.enabled, fail-closed (config
absent / flag off => behavior byte-identical to today).
"""
from __future__ import annotations

import json
from pathlib import Path

from harness.brief_status import (
    compute_autowork_eligibility,
    compute_autowork_backlog,
    _resolve_allowlisted_child_slugs,
)

CFG_ON = {"hierarchical_planning": {"enabled": True}}
CFG_OFF = {"hierarchical_planning": {"enabled": False}}


# ---------------------------------------------------------------------------
# scaffolding: an epic + its children laid down in a tmp repo/state
# ---------------------------------------------------------------------------

def _brief(repo: Path, slug: str) -> None:
    (repo / f"brief_hooks_{slug}.md").write_text(
        "# Title\n\nt\n\n# Scope\n\ns\n\n# Non-Goals\n\nn\n\n# Inputs\n\ni\n\n# Deliverables\n\nd\n",
        encoding="utf-8",
    )


def _epic(repo: Path, epic_slug: str, child_slugs: list[str]) -> None:
    _brief(repo, epic_slug)
    (repo / f"plan_hooks_{epic_slug}.json").write_text(
        json.dumps({"plan_kind": "epic", "epic": True, "epic_slug": epic_slug,
                    "child_slugs": list(child_slugs)}),
        encoding="utf-8",
    )


def _child_with_work(repo: Path, slug: str) -> None:
    # A child brief that is unplanned (no plan yet) => unstaged work present.
    _brief(repo, slug)


def _allowlist(state: Path, slugs: list[str]) -> None:
    p = state / "control" / "autowork" / "auto_promote.allowlist"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(slugs) + "\n", encoding="utf-8")


def _setup(tmp_path):
    repo = tmp_path
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    _epic(repo, "epic_e", ["c1", "c2"])
    _child_with_work(repo, "c1")
    _child_with_work(repo, "c2")
    return repo, state


def _eligible_set(result) -> set[str]:
    return set(result["eligible"])


# ---------------------------------------------------------------------------
# _resolve_allowlisted_child_slugs unit
# ---------------------------------------------------------------------------

def test_resolve_admits_children_of_allowlisted_epic(tmp_path):
    repo, _ = _setup(tmp_path)
    assert _resolve_allowlisted_child_slugs(repo, {"epic_e"}) == {"c1", "c2"}


def test_resolve_empty_when_epic_not_allowlisted(tmp_path):
    repo, _ = _setup(tmp_path)
    assert _resolve_allowlisted_child_slugs(repo, {"unrelated"}) == set()


def test_resolve_empty_when_allow_is_falsy(tmp_path):
    repo, _ = _setup(tmp_path)
    assert _resolve_allowlisted_child_slugs(repo, set()) == set()
    assert _resolve_allowlisted_child_slugs(repo, None) == set()


def test_resolve_transitive_grandchildren(tmp_path):
    # epic_e -> c1 (c1 is itself an epic) -> g1 : allowlisting epic_e admits g1.
    repo, _ = _setup(tmp_path)
    _epic(repo, "c1", ["g1"])
    _child_with_work(repo, "g1")
    admitted = _resolve_allowlisted_child_slugs(repo, {"epic_e"})
    assert {"c1", "c2", "g1"} <= admitted


def test_resolve_cycle_safe(tmp_path):
    repo, _ = _setup(tmp_path)
    # epic_e <-> c1 mutually list each other; must not hang.
    _epic(repo, "c1", ["epic_e"])
    out = _resolve_allowlisted_child_slugs(repo, {"epic_e"})
    assert "c1" in out  # terminates, returns a finite set


# ---------------------------------------------------------------------------
# compute_autowork_eligibility: flag-gated transitive admission
# ---------------------------------------------------------------------------

def test_children_eligible_when_epic_allowlisted_and_flag_on(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["epic_e"])  # only the epic, NOT the children
    elig = _eligible_set(compute_autowork_eligibility(repo, state, config=CFG_ON))
    assert {"c1", "c2"} <= elig
    assert "epic_e" in elig


def test_children_blocked_when_flag_off(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["epic_e"])
    elig = _eligible_set(compute_autowork_eligibility(repo, state, config=CFG_OFF))
    assert "c1" not in elig and "c2" not in elig  # fail-closed
    assert "epic_e" in elig


def test_children_blocked_when_config_absent_backcompat(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["epic_e"])
    # No config kwarg => byte-identical to today => children blocked.
    elig = _eligible_set(compute_autowork_eligibility(repo, state))
    assert "c1" not in elig and "c2" not in elig


def test_children_blocked_when_epic_not_allowlisted(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["something_else"])  # epic not allowlisted
    elig = _eligible_set(compute_autowork_eligibility(repo, state, config=CFG_ON))
    assert "c1" not in elig and "c2" not in elig


def test_empty_allowlist_still_deny_all_with_flag_on(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["# comment only"])  # present but no real slugs => deny-all
    elig = _eligible_set(compute_autowork_eligibility(repo, state, config=CFG_ON))
    assert elig == set()


def test_backlog_threads_config_admits_children(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["epic_e"])
    backlog = compute_autowork_backlog(repo, state, config=CFG_ON)
    with_work = set(backlog["eligible_with_work"])
    assert {"c1", "c2"} <= with_work
