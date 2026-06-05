"""Oracle for the webui eligibility config-threading fix (Brief 15 follow-up).

RED on HEAD: ControlHandlers.get_autowork_status calls
compute_autowork_eligibility(self.repo_root, self.state_dir) WITHOUT a config,
so the webui status panel never sees hierarchical_planning.enabled and reports
an epic's children as blocked ('not_in_allowlist') even though the daemon
(via _auto_promote_brief_eligible) is actively admitting and dispatching them.
The fix reads harness/config.yaml (best-effort, mirroring the cap read already
in the method) and threads it to compute_autowork_eligibility so the panel
matches the daemon's actual eligibility.
"""
from __future__ import annotations

import json
from pathlib import Path

from tools.webui_control import ControlHandlers


def _setup(tmp_path: Path, enabled: bool) -> ControlHandlers:
    repo = tmp_path
    state = tmp_path / "state"
    (state / "control" / "autowork").mkdir(parents=True)

    # epic + two children (brief_hooks + epic plan_hooks listing the children)
    for slug in ("epic_e", "c1", "c2"):
        (repo / f"brief_hooks_{slug}.md").write_text("# Title\n\nt\n", encoding="utf-8")
    (repo / "plan_hooks_epic_e.json").write_text(
        json.dumps({"plan_kind": "epic", "epic": True, "epic_slug": "epic_e",
                    "child_slugs": ["c1", "c2"]}),
        encoding="utf-8",
    )
    # allowlist trusts ONLY the epic
    (state / "control" / "autowork" / "auto_promote.allowlist").write_text(
        "epic_e\n", encoding="utf-8")
    # config.yaml with the flag
    (repo / "harness").mkdir(parents=True, exist_ok=True)
    (repo / "harness" / "config.yaml").write_text(
        f"hierarchical_planning:\n  enabled: {str(enabled).lower()}\n", encoding="utf-8")

    return ControlHandlers(state_dir=state, logs_dir=tmp_path / "logs", repo_root=repo)


def test_status_admits_children_when_flag_enabled(tmp_path):
    h = _setup(tmp_path, True)
    st, body = h.get_autowork_status()
    assert st == 200
    elig = body["eligibility"]["eligible"]
    assert "c1" in elig and "c2" in elig
    assert "epic_e" in elig


def test_status_blocks_children_when_flag_disabled(tmp_path):
    h = _setup(tmp_path, False)
    st, body = h.get_autowork_status()
    assert st == 200
    elig = body["eligibility"]["eligible"]
    assert "c1" not in elig and "c2" not in elig
    assert "epic_e" in elig  # epic itself is directly allowlisted


def test_status_eligibility_has_no_error_key(tmp_path):
    # The eligibility surface must compute cleanly (no swallowed exception).
    h = _setup(tmp_path, True)
    _, body = h.get_autowork_status()
    assert "error" not in body["eligibility"]


def test_status_missing_config_is_safe(tmp_path):
    # No harness/config.yaml at all -> best-effort empty config -> children
    # blocked (fail-closed), status still 200 with a real eligibility surface.
    repo = tmp_path
    state = tmp_path / "state"
    (state / "control" / "autowork").mkdir(parents=True)
    (repo / "brief_hooks_epic_e.md").write_text("# Title\n\nt\n", encoding="utf-8")
    (repo / "plan_hooks_epic_e.json").write_text(
        json.dumps({"plan_kind": "epic", "epic": True, "epic_slug": "epic_e",
                    "child_slugs": ["c1"]}), encoding="utf-8")
    (repo / "brief_hooks_c1.md").write_text("# Title\n\nt\n", encoding="utf-8")
    (state / "control" / "autowork" / "auto_promote.allowlist").write_text("epic_e\n", encoding="utf-8")
    h = ControlHandlers(state_dir=state, logs_dir=tmp_path / "logs", repo_root=repo)
    st, body = h.get_autowork_status()
    assert st == 200
    assert "error" not in body["eligibility"]
    assert "c1" not in body["eligibility"]["eligible"]
