import json
import sys
import subprocess
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest
from hypothesis import given, strategies as st, settings, HealthCheck

import harness.planner.cli as cli
from harness.planner.cli import PlanPipelineError, _tracker

@pytest.fixture
def mock_pipeline(monkeypatch):
    # Reset tracker
    cli._tracker.call_order = []
    
    monkeypatch.setattr("harness.planner.brief_loader.load_brief", MagicMock())
    
    drafts_mock = MagicMock()
    drafts_mock.claude_draft = {"tasks": []}
    drafts_mock.gemini_draft = {"tasks": []}
    monkeypatch.setattr("harness.planner.blind_draft.run_blind_drafts", MagicMock(return_value=drafts_mock))
    
    monkeypatch.setattr("harness.planner.diff_extractor.extract_diff", MagicMock())
    
    recon_mock = MagicMock()
    recon_mock.merged_tasks = []
    monkeypatch.setattr("harness.planner.reconciliation.run_reconciliation", MagicMock(return_value=recon_mock))
    
    monkeypatch.setattr("harness.planner.attribution.stamp_attribution", MagicMock(return_value=[]))
    
    monkeypatch.setattr("harness.planner.adversarial_review.run_adversarial_review", MagicMock(return_value=Path("c.json")))
    
    amend_mock = MagicMock()
    amend_mock.amended_plan = {"tasks": []}
    monkeypatch.setattr("harness.planner.auto_amend.auto_amend", MagicMock(return_value=amend_mock))
    
    # We still need to mock persist_plan locally to assert paths easily without writing?
    # No, persist_plan correctly records the tracking and we want it to run.
    # We will just let it write to the test's tmp_path.
    
    monkeypatch.setattr("harness.planner.plan_validator.validate_plan", MagicMock(return_value=[]))

    return {
        "drafts": drafts_mock,
        "recon": recon_mock,
        "amend": amend_mock
    }


def write_dummy_config(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("planner:\n  auto_amend_enabled: true\n")

def write_dummy_brief(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w") as f:
        f.write("# Title\nData\n## Scope\nData\n## Non_goals\nData\n## Inputs\nData\n## Deliverables\nData\n")


def test_cli_parses_bootstrap_default(mock_pipeline, tmp_path):
    conf = tmp_path / "config.yaml"
    brief = tmp_path / "brief.json"
    write_dummy_config(conf)
    write_dummy_brief(brief)
    
    with pytest.raises(SystemExit) as exc:
        cli.main([str(brief), "--config", str(conf)])
    assert exc.value.code == 0
    
    import harness.planner.attribution
    harness.planner.attribution.stamp_attribution.assert_called_once()
    assert harness.planner.attribution.stamp_attribution.call_args[0][3] is True  # bootstrap


def test_cli_parses_non_bootstrap(mock_pipeline, tmp_path):
    conf = tmp_path / "config.yaml"
    brief = tmp_path / "brief.json"
    write_dummy_config(conf)
    write_dummy_brief(brief)
    
    with pytest.raises(SystemExit) as exc:
        cli.main([str(brief), "--config", str(conf), "--non-bootstrap"])
    assert exc.value.code == 0
    
    import harness.planner.attribution
    harness.planner.attribution.stamp_attribution.assert_called_once()
    assert harness.planner.attribution.stamp_attribution.call_args[0][3] is False


def test_dry_run_no_agent_spawn(mock_pipeline, tmp_path):
    brief = tmp_path / "brief.json"
    write_dummy_brief(brief)
    
    with pytest.raises(SystemExit) as exc:
        cli.main([str(brief), "--dry-run"])
    assert exc.value.code == 0
    
    import harness.planner.blind_draft
    harness.planner.blind_draft.run_blind_drafts.assert_not_called()
    assert cli._tracker.call_order == ["load_brief"]


def test_exit_code_brief_failure(tmp_path):
    brief = tmp_path / "does_not_exist.json"
    with pytest.raises(SystemExit) as exc:
        cli.main([str(brief), "--dry-run"])
    assert exc.value.code == 3


def test_exit_code_both_agents_crash(mock_pipeline, tmp_path):
    conf = tmp_path / "config.yaml"
    brief = tmp_path / "brief.json"
    write_dummy_config(conf)
    write_dummy_brief(brief)
    
    mock_pipeline["drafts"].claude_draft = None
    mock_pipeline["drafts"].gemini_draft = None
    
    with pytest.raises(SystemExit) as exc:
        cli.main([str(brief), "--config", str(conf)])
    assert exc.value.code == 2


def test_default_output_paths(mock_pipeline, tmp_path):
    conf = tmp_path / "config.yaml"
    brief = tmp_path / "brief.json"
    write_dummy_config(conf)
    write_dummy_brief(brief)
    
    with pytest.raises(SystemExit) as exc:
        cli.main([str(brief), "--config", str(conf)])
    assert exc.value.code == 0
    
    # Check persist_plan arg by looking for file
    assert Path("state/planning/merged_plan.json").exists()
    
    import harness.planner.auto_amend
    critique_path = harness.planner.auto_amend.auto_amend.call_args[0][1]
    assert str(critique_path).endswith("critique.json")


def test_cli_pipeline_sequence_is_fixed_order(mock_pipeline, tmp_path):
    conf = tmp_path / "config.yaml"
    brief = tmp_path / "brief.json"
    write_dummy_config(conf)
    write_dummy_brief(brief)
    
    with pytest.raises(SystemExit) as exc:
        cli.main([str(brief), "--config", str(conf)])
    assert exc.value.code == 0
        
    expected = [
        "load_brief",
        "blind_drafts",
        "diff",
        "reconciliation",
        "attribution_stamp",
        "adversarial_review",
        "auto_amend_gate",
        "persist_plan"
    ]
    assert cli._tracker.call_order == expected
    cli._tracker.verify(expected)


def test_full_cli_run_with_mocks(mock_pipeline, tmp_path):
    conf = tmp_path / "config.yaml"
    brief = tmp_path / "brief.json"
    write_dummy_config(conf)
    write_dummy_brief(brief)
    
    out_plan = tmp_path / "custom_merged.json"
    out_critique = tmp_path / "custom_critique.json"
    
    with pytest.raises(SystemExit) as exc:
        cli.main([str(brief), "--config", str(conf), "--output-plan", str(out_plan), "--output-critique", str(out_critique)])
    assert exc.value.code == 0
    
    assert out_plan.exists()
    
    import harness.planner.auto_amend
    assert harness.planner.auto_amend.auto_amend.call_args[0][1] == out_critique


def test_shell_wrapper_forwards_args(tmp_path):
    wrapper = Path("scripts/plan-draft.sh")
    if not wrapper.exists():
        pytest.skip("wrapper not found")
        
    # We will invoke the wrapper with --dry-run
    brief = tmp_path / "brief.json"
    write_dummy_brief(brief)
    
    res = subprocess.run([str(wrapper), str(brief), "--dry-run"], capture_output=True)
    assert res.returncode == 0


@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
@given(st.booleans())
def test_bootstrap_flag_preserved_across_layers(mock_pipeline, tmp_path, bootstrap_val):
    conf = tmp_path / "config.yaml"
    brief = tmp_path / "brief.json"
    write_dummy_config(conf)
    write_dummy_brief(brief)
    
    args = [str(brief), "--config", str(conf)]
    if not bootstrap_val:
        args.append("--non-bootstrap")
        
    with pytest.raises(SystemExit) as exc:
        cli.main(args)
    assert exc.value.code == 0
        
    import harness.planner.attribution
    assert harness.planner.attribution.stamp_attribution.call_args[0][3] is bootstrap_val


def test_non_bootstrap_without_track_record_exits_2(mock_pipeline, tmp_path, monkeypatch):
    conf = tmp_path / "config.yaml"
    brief = tmp_path / "brief.json"
    write_dummy_config(conf)
    write_dummy_brief(brief)
    
    # Mock find_spec to return None
    monkeypatch.setattr("importlib.util.find_spec", lambda x: None)
    
    with pytest.raises(SystemExit) as exc:
        cli.main([str(brief), "--config", str(conf), "--non-bootstrap"])
    assert exc.value.code == 2


def test_single_agent_draft_produces_merged_plan(mock_pipeline, tmp_path):
    conf = tmp_path / "config.yaml"
    brief = tmp_path / "brief.json"
    write_dummy_config(conf)
    write_dummy_brief(brief)
    
    mock_pipeline["drafts"].gemini_draft = None
    
    with pytest.raises(SystemExit) as exc:
        cli.main([str(brief), "--config", str(conf)])
    assert exc.value.code == 0
        
    import harness.planner.diff_extractor
    assert harness.planner.diff_extractor.extract_diff.call_args[0][1] == {"tasks": []}
