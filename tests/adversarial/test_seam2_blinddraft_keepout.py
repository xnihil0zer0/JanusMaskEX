"""Adversarial oracle for PHASE_SEAM2_BLINDDRAFT_KEEPOUT.

This test serves as a regression-guard asserting that the 'working_dir' field
on PlanningBrief is NOT serialized into the structured whitelist JSON dump
at planning/brief.json during run_blind_drafts(), while raw_text remains present.
"""
import json
from pathlib import Path
from unittest.mock import patch
import pytest

from harness.planner.blind_draft import run_blind_drafts
from harness.planner.brief_loader import PlanningBrief


def test_blind_draft_structured_dump_keepout(tmp_path: Path):
    # Build a PlanningBrief with working_dir set to a path
    brief = PlanningBrief(
        title="Test Title",
        scope="Test Scope",
        non_goals="Test Non-Goals",
        inputs="Test Inputs",
        deliverables="Test Deliverables",
        raw_text="Test Raw Text with working_dir: /tmp/evil_target",
        source_path="path/to/source",
        sha256="fake_sha256",
        working_dir="/tmp/evil_target"
    )

    base_config = {
        "agents": {
            "claude": {"env": {}},
            "gemini": {"env": {}}
        },
        "synthesis": {
            "timeout_seconds": 10
        }
    }

    # Patch harness.planner.blind_draft.run_both_agents to return (None, None)
    with patch("harness.planner.blind_draft.run_both_agents", return_value=(None, None)):
        run_blind_drafts(brief, base_config, tmp_path)

    brief_json_path = tmp_path / "planning" / "brief.json"
    assert brief_json_path.exists()

    with open(brief_json_path, "r", encoding="utf-8") as f:
        dumped_data = json.load(f)

    # Assert "working_dir" NOT in the top-level dict keys (keep-out guard)
    assert "working_dir" not in dumped_data, (
        f"regression guard failed: 'working_dir' was elevated to the structured dump: {dumped_data.keys()}"
    )

    # Assert "raw_text" IS in the dump (documents that raw_text leak is intentional / seam-4 scope)
    assert "raw_text" in dumped_data, "expected 'raw_text' to be present in structured dump"


def test_keepout_non_vacuity_monkeypatch(tmp_path: Path):
    # Prove that IF working_dir were added to the structured dump, the guard WOULD fire.
    brief = PlanningBrief(
        title="Test Title",
        scope="Test Scope",
        non_goals="Test Non-Goals",
        inputs="Test Inputs",
        deliverables="Test Deliverables",
        raw_text="Test Raw Text with working_dir: /tmp/evil_target",
        source_path="path/to/source",
        sha256="fake_sha256",
        working_dir="/tmp/evil_target"
    )

    base_config = {
        "agents": {
            "claude": {"env": {}},
            "gemini": {"env": {}}
        },
        "synthesis": {
            "timeout_seconds": 10
        }
    }

    original_dump = json.dump

    def evil_json_dump(obj, fp, **kwargs):
        # Inject working_dir if it is the brief structured dump object
        if isinstance(obj, dict) and "title" in obj and "scope" in obj:
            obj = dict(obj)
            obj["working_dir"] = "/tmp/evil_target"
        return original_dump(obj, fp, **kwargs)

    # Run the setup but with a monkeypatched json.dump that injects working_dir
    with patch("harness.planner.blind_draft.run_both_agents", return_value=(None, None)):
        with patch("json.dump", side_effect=evil_json_dump):
            run_blind_drafts(brief, base_config, tmp_path)

    # Verify that loading the written brief.json and asserting "working_dir"
    # not in keys correctly raises an AssertionError.
    brief_json_path = tmp_path / "planning" / "brief.json"
    with open(brief_json_path, "r", encoding="utf-8") as f:
        dumped_data = json.load(f)

    with pytest.raises(AssertionError) as exc_info:
        assert "working_dir" not in dumped_data, (
            f"regression guard failed: 'working_dir' was elevated to the structured dump: {dumped_data.keys()}"
        )
    
    assert "working_dir" in str(exc_info.value)


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q", "-p", "no:cacheprovider"]))
