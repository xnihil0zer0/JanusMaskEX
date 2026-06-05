"""Oracle for Brief 15b [SECURITY-GATED, owner-approved 2026-06-05]: epic-child
fast-path in the daemon's _auto_promote_brief_eligible gate.

RED on HEAD: _auto_promote_brief_eligible (the decisive per-brief gate the daemon
consults at autowork_daemon.py:1265 and :1388) admits a slug only if it is a
self-heal brief (flag+provenance) or literally present in auto_promote.allowlist.
An epic's child brief is neither, so the autonomous loop stalls on it. Owner
decision (2026-06-05): a child whose parent epic is allowlisted is admitted
WITHOUT a direct allowlist entry, gated by hierarchical_planning.enabled,
read-derived (the allowlist file is never written), fail-closed — mirroring the
existing self-heal fast-path. The lineage is reconstructed via
brief_status._resolve_allowlisted_child_slugs (Brief 15a).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from harness.autowork_daemon import _auto_promote_brief_eligible

CFG_ON = {"hierarchical_planning": {"enabled": True}}
CFG_OFF = {"hierarchical_planning": {"enabled": False}}


def _epic(repo: Path, epic_slug: str, child_slugs: list[str]) -> None:
    (repo / f"brief_hooks_{epic_slug}.md").write_text("# Title\n\nt\n", encoding="utf-8")
    (repo / f"plan_hooks_{epic_slug}.json").write_text(
        json.dumps({"plan_kind": "epic", "epic": True, "epic_slug": epic_slug,
                    "child_slugs": list(child_slugs)}),
        encoding="utf-8",
    )


def _allowlist(state: Path, slugs: list[str]) -> None:
    p = state / "control" / "autowork" / "auto_promote.allowlist"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(slugs) + "\n", encoding="utf-8")


def _setup(tmp_path):
    repo = tmp_path
    state = tmp_path / "state"
    state.mkdir(parents=True, exist_ok=True)
    _epic(repo, "epic_e", ["c1", "c2"])
    return repo, state


def _eligible(state, slug, repo, config, *, now=None, mtime=None):
    now = now if now is not None else time.time()
    mtime = mtime if mtime is not None else now
    return _auto_promote_brief_eligible(
        state, slug, mtime, now=now, max_age_sec=10_000, config=config, repo_root=repo)


# ---------------------------------------------------------------------------

def test_child_eligible_when_epic_allowlisted_and_flag_on(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["epic_e"])  # only the epic
    assert _eligible(state, "c1", repo, CFG_ON) is True
    assert _eligible(state, "c2", repo, CFG_ON) is True


def test_child_blocked_when_flag_off(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["epic_e"])
    assert _eligible(state, "c1", repo, CFG_OFF) is False


def test_child_blocked_when_config_none_backcompat(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["epic_e"])
    assert _eligible(state, "c1", repo, None) is False


def test_child_blocked_when_epic_not_allowlisted(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["other"])
    assert _eligible(state, "c1", repo, CFG_ON) is False


def test_directly_allowlisted_slug_still_eligible(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["epic_e", "plain_brief"])
    (repo / "brief_hooks_plain_brief.md").write_text("# Title\n\nt\n", encoding="utf-8")
    assert _eligible(state, "plain_brief", repo, CFG_ON) is True
    # and unchanged with no config at all
    assert _eligible(state, "plain_brief", repo, None) is True


def test_admitted_child_still_subject_to_age_gate(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["epic_e"])
    now = time.time()
    # child passes the allowlist fast-path but is too old => still blocked.
    assert _eligible(state, "c1", repo, CFG_ON, now=now, mtime=now - 99_999) is False


def test_empty_allowlist_deny_all_even_for_child(tmp_path):
    repo, state = _setup(tmp_path)
    _allowlist(state, ["# comment only"])  # deny-all
    assert _eligible(state, "c1", repo, CFG_ON) is False


def test_unrelated_slug_blocked_unchanged(tmp_path):
    # A slug that is neither directly allowlisted, a self-heal brief, nor an
    # epic child stays blocked (fail-closed, byte-identical to today).
    repo, state = _setup(tmp_path)
    _allowlist(state, ["epic_e"])
    assert _eligible(state, "random_other", repo, CFG_ON) is False
