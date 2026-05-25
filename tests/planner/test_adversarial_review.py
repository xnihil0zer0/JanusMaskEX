import json
import pytest
from pathlib import Path
import copy
from hypothesis import given, strategies as st, settings, HealthCheck

from harness.planner.adversarial_review import run_adversarial_review, CritiqueSchema

def test_critique_schema_valid():
    data = {
        "findings": [
            {
                "finding_id": "123",
                "category": "test_heavy_violation",
                "severity": "warn",
                "message": "Need more tests",
                "suggested_patch": {"op": "increase_test_count", "delta": 2}
            }
        ]
    }
    violations = CritiqueSchema.validate(data)
    assert not violations, f"Expected valid, got {violations}"

def test_critique_schema_unknown_category():
    data = {
        "findings": [
            {
                "finding_id": "123",
                "category": "not_a_category",
                "severity": "warn",
                "message": "bad"
            }
        ]
    }
    violations = CritiqueSchema.validate(data)
    assert violations
    assert any("invalid category" in v for v in violations)

def test_empty_findings_preserved():
    data = {"findings": []}
    violations = CritiqueSchema.validate(data)
    assert not violations

def test_malformed_json_yields_synthetic_critique(tmp_path, monkeypatch):
    import harness.planner.adversarial_review
    
    class MockProc:
        def poll(self): return 0
    
    def mock_spawn(*args, **kwargs):
        reviewer_dir = tmp_path / "planning" / "sessions" / "claude"
        sessions_dir = reviewer_dir / "planning" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        with open(sessions_dir / "claude_reconciliation.json", "w") as f:
            f.write("not json")
        return MockProc()
        
    monkeypatch.setattr(harness.planner.adversarial_review, "spawn_agent", mock_spawn)
    monkeypatch.setattr(harness.planner.adversarial_review, "kill_agent", lambda x: None)

    plan = {"tasks": [{"task_id": "T1"}]}
    config = {}
    critique_path = run_adversarial_review(plan, config, tmp_path, reviewer="claude")
    assert critique_path.exists()
    
    with open(critique_path, "r") as f:
        data = json.load(f)
    assert len(data["findings"]) == 1
    assert data["findings"][0]["finding_id"] == "synthetic_failure"

def test_agent_timeout_yields_synthetic_critique(tmp_path, monkeypatch):
    import harness.planner.adversarial_review
    
    class MockProc:
        def poll(self): return None
        
    def mock_spawn(*args, **kwargs):
        return MockProc()
        
    monkeypatch.setattr(harness.planner.adversarial_review, "spawn_agent", mock_spawn)
    monkeypatch.setattr(harness.planner.adversarial_review, "kill_agent", lambda *a, **k: None)

    plan = {"tasks": [{"task_id": "T1"}]}
    config = {"planning_timeout_seconds": 0.1}
    critique_path = run_adversarial_review(plan, config, tmp_path, reviewer="claude")
    assert critique_path.exists()
    
    with open(critique_path, "r") as f:
        data = json.load(f)
    assert data["findings"][0]["finding_id"] == "synthetic_failure"
    assert "timed out" in data["findings"][0]["message"]

def test_adversarial_review_with_mock_agent(tmp_path, monkeypatch):
    import harness.planner.adversarial_review
    
    class MockProc:
        def poll(self): return 0
        
    def mock_spawn(*args, **kwargs):
        reviewer_dir = tmp_path / "planning" / "sessions" / "claude"
        sessions_dir = reviewer_dir / "planning" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        valid_data = {
            "findings": [
                {
                    "finding_id": "1",
                    "category": "missing_edge_case",
                    "severity": "warn",
                    "message": "missed this"
                }
            ]
        }
        with open(sessions_dir / "claude_reconciliation.json", "w") as f:
            json.dump(valid_data, f)
        return MockProc()

    monkeypatch.setattr(harness.planner.adversarial_review, "spawn_agent", mock_spawn)
    monkeypatch.setattr(harness.planner.adversarial_review, "kill_agent", lambda x: None)
    
    plan = {"tasks": []}
    critique_path = run_adversarial_review(plan, {}, tmp_path, reviewer="claude")
    assert critique_path.exists()
    with open(critique_path, "r") as f:
        data = json.load(f)
    assert data["findings"][0]["finding_id"] == "1"

@st.composite
def plan_dict(draw):
    tasks = draw(st.lists(st.fixed_dictionaries({"task_id": st.text()}), max_size=2))
    return {"tasks": tasks}

@given(plan=plan_dict())
@settings(suppress_health_check=[HealthCheck.function_scoped_fixture])
def test_never_mutates_input_plan(plan, tmp_path, monkeypatch):
    import harness.planner.adversarial_review
    
    class MockProc:
        def poll(self): return 0
    def mock_spawn(*args, **kwargs):
        reviewer_dir = tmp_path / "planning" / "sessions" / "claude"
        sessions_dir = reviewer_dir / "planning" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        with open(sessions_dir / "claude_reconciliation.json", "w") as f:
            json.dump({"findings": []}, f)
        return MockProc()
    monkeypatch.setattr(harness.planner.adversarial_review, "spawn_agent", mock_spawn)
    monkeypatch.setattr(harness.planner.adversarial_review, "kill_agent", lambda x: None)
    
    plan_copy = copy.deepcopy(plan)
    run_adversarial_review(plan, {"planning_timeout_seconds": 0.1}, tmp_path, reviewer="claude")
    
    assert plan == plan_copy

def test_gemini_unavailable_synthetic_failure(tmp_path):
    config = {
        "agents": {
            "gemini": {
                "command": "this_cmd_does_not_exist_at_all"
            }
        }
    }
    critique_path = run_adversarial_review({"tasks": []}, config, tmp_path, reviewer="gemini")
    assert critique_path.exists()
    with open(critique_path, "r") as f:
        data = json.load(f)
    assert data["findings"][0]["finding_id"] == "synthetic_failure"
    assert "Command not found" in data["findings"][0]["message"]

def test_empty_plan_does_not_crash(tmp_path, monkeypatch):
    import harness.planner.adversarial_review
    class MockProc:
        def poll(self): return 0
    def mock_spawn(*args, **kwargs):
        reviewer_dir = tmp_path / "planning" / "sessions" / "claude"
        sessions_dir = reviewer_dir / "planning" / "sessions"
        sessions_dir.mkdir(parents=True, exist_ok=True)
        with open(sessions_dir / "claude_reconciliation.json", "w") as f:
            json.dump({"findings": []}, f)
        return MockProc()
    monkeypatch.setattr(harness.planner.adversarial_review, "spawn_agent", mock_spawn)
    monkeypatch.setattr(harness.planner.adversarial_review, "kill_agent", lambda x: None)
    
    critique_path = run_adversarial_review({"tasks": []}, {}, tmp_path, reviewer="claude")
    assert critique_path.exists()
