import os
import json
import pytest
import subprocess
from pathlib import Path
from scripts._audit_test_coverage import audit_coverage, get_tests_from_ast

@pytest.fixture
def mock_tests_dir(tmp_path):
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir()
    
    # Create some dummy tests
    file1 = tests_dir / "test_a.py"
    file1.write_text("def test_feature_a(): pass\ndef test_feature_b(): pass\ndef test_feature_c(): pass\n")
    
    file2 = tests_dir / "test_b.py"
    file2.write_text("def test_meta_exempt(): pass\nclass TestClass:\n    def test_in_class(self): pass\n")
    
    file3 = tests_dir / "test_under.py"
    file3.write_text("def test_under_a(): pass\ndef test_under_b(): pass\ndef test_under_c(): pass\n")
    
    # Create fixtures dir to test ignoring
    fixtures_dir = tests_dir / "fixtures" / "plans"
    fixtures_dir.mkdir(parents=True)
    fixture_file = fixtures_dir / "test_fixture.py"
    fixture_file.write_text("def test_fixture_should_be_ignored(): pass\n")
    
    return tests_dir

def test_audit_parses_sample_plan(mock_tests_dir):
    plan_path = "tests/fixtures/plans/sample_plan.json"
    report, all_ok = audit_coverage([plan_path], str(mock_tests_dir))
    
    assert "T-001" in report["tasks"]
    assert report["tasks"]["T-001"]["minimum_test_count"] == 2
    assert report["tasks"]["T-001"]["status"] == "OK"

def test_audit_reports_gap_when_under_count(mock_tests_dir):
    plan_path = "tests/fixtures/plans/sample_plan_with_gap.json"
    report, all_ok = audit_coverage([plan_path], str(mock_tests_dir))
    
    assert "T-004" in report["tasks"]
    assert report["tasks"]["T-004"]["status"] == "UNDER"
    assert report["tasks"]["T-004"]["gap"] == 2
    assert not all_ok

def test_audit_reports_missing_when_no_tests(mock_tests_dir):
    plan_path = "tests/fixtures/plans/sample_plan_with_gap.json"
    report, all_ok = audit_coverage([plan_path], str(mock_tests_dir))
    
    assert "T-005" in report["tasks"]
    assert report["tasks"]["T-005"]["status"] == "MISSING"

def test_audit_flags_typo_in_listed_test_name(mock_tests_dir):
    plan_path = "tests/fixtures/plans/sample_plan_with_gap.json"
    report, all_ok = audit_coverage([plan_path], str(mock_tests_dir))
    
    assert "T-006" in report["tasks"]
    assert "typo_suspected" in report["tasks"]["T-006"]
    assert "test_missing_typo" in report["tasks"]["T-006"]["typo_suspected"]

def test_audit_exempts_test_star_meta_types(mock_tests_dir):
    plan_path = "tests/fixtures/plans/sample_plan.json"
    report, all_ok = audit_coverage([plan_path], str(mock_tests_dir))
    
    assert "T-002" in report["tasks"]
    assert report["tasks"]["T-002"]["status"] == "EXEMPT_RATIO"

def test_audit_handles_missing_plan_file(mock_tests_dir):
    report, all_ok = audit_coverage(["non_existent_plan.json"], str(mock_tests_dir))
    # Should not crash, just empty report
    assert report["tasks"] == {}
    assert all_ok

def test_audit_ast_finds_class_methods(mock_tests_dir):
    tests = get_tests_from_ast(str(mock_tests_dir))
    assert "test_in_class" in tests

def test_audit_writes_json_log(tmp_path, mock_tests_dir):
    log_file = tmp_path / "logs" / "test_coverage_audit.json"
    script = Path("scripts/_audit_test_coverage.py").resolve()
    subprocess.run(["python3", str(script), "tests/fixtures/plans/sample_plan.json", "--tests-dir", str(mock_tests_dir), "--log-file", str(log_file)], check=True)
    assert log_file.exists()
    
    with open(log_file, "r") as f:
        data = json.load(f)
    assert "tasks" in data

def test_audit_reports_running_total_matches_plan_minimums(mock_tests_dir):
    plan_path = "tests/fixtures/plans/sample_plan.json"
    report, all_ok = audit_coverage([plan_path], str(mock_tests_dir))
    
    assert "totals" in report
    assert isinstance(report["totals"]["found"], int)
    assert isinstance(report["totals"]["required"], int)
    
    # T-001 (min 2, found 2), T-003 (min 1, found 1). T-002 is exempt.
    # required = 2 + 1 = 3
    assert report["totals"]["required"] == 3
    assert report["totals"]["found"] == 3

def test_audit_end_to_end_against_fixture_repo(tmp_path):
    # Setup a mini repo in tmp_path
    repo_dir = tmp_path / "repo"
    repo_dir.mkdir()
    
    tests_dir = repo_dir / "tests"
    tests_dir.mkdir()
    (tests_dir / "test_sample.py").write_text("def test_feature_a(): pass\n")
    
    plan_path = repo_dir / "plan.json"
    plan_path.write_text("""
    {
      "tasks": [
        {
          "task_id": "T-E2E",
          "meta_task_type": "feature",
          "test_spec": {
            "minimum_test_count": 1,
            "unit_tests": [{"name": "test_feature_a"}]
          }
        }
      ]
    }
    """)
    
    # Run bash wrapper simulating end-to-end
    wrapper = Path("scripts/audit-test-coverage.sh").resolve()
    result = subprocess.run([str(wrapper), str(plan_path), "--tests-dir", str(tests_dir)], cwd=str(repo_dir), capture_output=True, text=True)
    
    assert result.returncode == 0
    assert "Audit passed" in result.stdout

def test_regression_audit_does_not_count_tests_in_fixtures(mock_tests_dir):
    tests = get_tests_from_ast(str(mock_tests_dir))
    assert "test_fixture_should_be_ignored" not in tests
