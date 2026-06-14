"""RED oracle: collect_agent_draft must stamp the brief's ``working_dir`` onto a
plan draft BEFORE validating it, so an EXTERNAL-target EDIT leaf is not falsely
flagged ``missing_wiring_oracle``.

Root cause this pins: the blind-draft submission collector validates the raw
``plan_draft.json`` (which carries no ``working_dir``) via ``validate_plan``.
``_is_module_creating`` resolves file existence against ``effective_target_root
(plan['working_dir'])`` -> with no working_dir it falls back to the JanusMask
PROJECT_ROOT. For an external (NobleGreedv2) EDIT leaf whose file exists under
the EXTERNAL root but not under JanusMask, the file reads as ABSENT -> the task
is misclassified as module-CREATING -> the validator demands a ``*_wired``
oracle the edit leaf cannot have -> the draft is rejected -> empty_plan ->
``planner_hallucination_discarded``. Stamping the brief's working_dir onto the
draft before validation makes the existence check resolve against the real
external target, so a genuine edit leaf validates clean.
"""
from __future__ import annotations

import json
from pathlib import Path

from harness.planner.blind_draft import collect_agent_draft


def _external_edit_draft(rel_module: str) -> dict:
    """A fully-valid leaf draft (data_model edit) whose ONLY potential violation
    is the module-creating/wiring false-positive when working_dir is absent."""
    return {
        "tasks": [
            {
                "task_id": "ext-edit-leaf",
                "title": "edit existing external module",
                "meta_task_type": "data_model",
                "priority": "high",
                "dependencies": [],
                "files_touched": [rel_module],
                "acceptance_criteria": ["field attached"],
                "spec_author": None,
                "estimated_complexity": "low",
                "verification_command": "python -m pytest tests/test_thing.py -q",
                "spec": {
                    "objective": "attach a field",
                    "functional_requirements": ["attach field", "carry field"],
                    "interfaces": "edit existing funcs",
                    "edge_cases": ["absent input", "determinism"],
                    "non_goals": ["integration"],
                    "implementation_notes": "additive edit",
                },
                "test_spec": {
                    "unit_tests": [{"name": "a"}, {"name": "b"}],
                    "integration_tests": [],
                    "property_tests": [],
                    "regression_tests": [{"name": "r1"}, {"name": "r2"}],
                    "minimum_test_count": 3,
                    "test_data_requirements": "fixture",
                },
                "token_budget_ratio": {
                    "implementation_tokens": 100,
                    "test_tokens": 200,
                    "note": "n",
                },
                "attribution_metadata": {
                    "proposed_by": "agent",
                    "reconciled": False,
                    "diff_resolution": "",
                },
            }
        ]
    }


def _setup(tmp_path: Path):
    # External target with an EXISTING module file (the edit target).
    ext = tmp_path / "ext_target"
    (ext / "pkg").mkdir(parents=True)
    (ext / "pkg" / "mod.py").write_text("VALUE = 1\n", encoding="utf-8")
    # Agent draft (no working_dir) editing that existing external module.
    agent_dir = tmp_path / "agent"
    sessions = agent_dir / "planning" / "sessions"
    sessions.mkdir(parents=True)
    (sessions / "claude_draft.json").write_text(
        json.dumps(_external_edit_draft("pkg/mod.py")), encoding="utf-8"
    )
    state_dir = tmp_path / "state"
    state_dir.mkdir()
    return ext, agent_dir, state_dir


def test_without_working_dir_external_edit_is_falsely_invalid(tmp_path):
    _ext, agent_dir, state_dir = _setup(tmp_path)
    draft, status = collect_agent_draft(
        "claude", agent_dir, state_dir, elapsed=20.0, timeout=300.0,
        spawn_start_epoch=None,
    )
    # Documents the bug: without working_dir the external edit leaf is rejected.
    assert status == "invalid"
    assert draft is None


def test_with_working_dir_external_edit_validates_ok(tmp_path):
    ext, agent_dir, state_dir = _setup(tmp_path)
    draft, status = collect_agent_draft(
        "claude", agent_dir, state_dir, elapsed=20.0, timeout=300.0,
        spawn_start_epoch=None, working_dir=str(ext),
    )
    assert status == "ok", (
        "stamping the brief working_dir must let an external EDIT leaf validate "
        "clean (the edited module exists under the external root)"
    )
    assert isinstance(draft, dict)
    assert draft.get("working_dir") == str(ext)


def test_existing_working_dir_on_draft_is_not_overwritten(tmp_path):
    ext, agent_dir, state_dir = _setup(tmp_path)
    # Pre-stamp a working_dir on the draft; collector must not clobber it.
    p = agent_dir / "planning" / "sessions" / "claude_draft.json"
    d = json.loads(p.read_text())
    d["working_dir"] = str(ext)
    p.write_text(json.dumps(d), encoding="utf-8")
    draft, status = collect_agent_draft(
        "claude", agent_dir, state_dir, elapsed=20.0, timeout=300.0,
        spawn_start_epoch=None, working_dir="/some/other/root",
    )
    assert status == "ok"
    assert draft.get("working_dir") == str(ext)
