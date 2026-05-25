import os
import shutil
import subprocess
from pathlib import Path
import pytest
import time

MARKER_ATTEMPTS = "# DEFERRED_WIRING: attempts_not_consumed"
MARKER_AMBIGUOUS = "# DEFERRED_WIRING: ambiguous_folded_into_failures"
SCRIPT_PATH = Path("scripts/check-deferred-wiring.sh").absolute()

@pytest.fixture
def repo_fixture(tmp_path):
    harness = tmp_path / "harness"
    harness.mkdir()
    scripts = tmp_path / "scripts"
    scripts.mkdir()
    tests = tmp_path / "tests"
    tests.mkdir()
    
    tr_path = harness / "track_record.py"
    tr_path.write_text(f"""
def attempts_func():
    {MARKER_ATTEMPTS}
    pass

def ambiguous_func():
    {MARKER_AMBIGUOUS}
    pass
""")
    yield tmp_path

def test_script_exits_zero_when_both_markers_present(repo_fixture):
    result = subprocess.run([SCRIPT_PATH], cwd=repo_fixture, capture_output=True, text=True)
    assert result.returncode == 0
    assert MARKER_ATTEMPTS in result.stdout
    assert MARKER_AMBIGUOUS in result.stdout

def test_script_exits_nonzero_when_attempts_marker_missing(repo_fixture):
    tr_path = repo_fixture / "harness" / "track_record.py"
    tr_path.write_text(f"""
def ambiguous_func():
    {MARKER_AMBIGUOUS}
    pass
""")
    result = subprocess.run([SCRIPT_PATH], cwd=repo_fixture, capture_output=True, text=True)
    assert result.returncode != 0

def test_script_exits_nonzero_when_ambiguous_marker_missing(repo_fixture):
    tr_path = repo_fixture / "harness" / "track_record.py"
    tr_path.write_text(f"""
def attempts_func():
    {MARKER_ATTEMPTS}
    pass
""")
    result = subprocess.run([SCRIPT_PATH], cwd=repo_fixture, capture_output=True, text=True)
    assert result.returncode != 0

def test_script_list_mode_zero_markers_ok(repo_fixture):
    tr_path = repo_fixture / "harness" / "track_record.py"
    tr_path.write_text("def no_markers(): pass")
    result = subprocess.run([SCRIPT_PATH, "--list"], cwd=repo_fixture, capture_output=True, text=True)
    assert result.returncode == 0
    assert "0 attempts_not_consumed" in result.stdout
    assert "0 ambiguous_folded_into_failures" in result.stdout

def test_script_is_read_only(repo_fixture):
    mtimes_before = {}
    for p in repo_fixture.rglob("*"):
        if p.is_file():
            mtimes_before[p] = p.stat().st_mtime
            
    time.sleep(0.01) # to ensure mtime would change if modified
    result = subprocess.run([SCRIPT_PATH], cwd=repo_fixture, capture_output=True, text=True)
    assert result.returncode == 0
    
    for p, mtime in mtimes_before.items():
        assert p.stat().st_mtime == mtime, f"{p} was modified"

def test_handler_for_all_event_types_covered(repo_fixture):
    from harness.track_record_events import append_track_event, EventValidationError
    import pytest
    with pytest.raises(ValueError):
        append_track_event(
            event_type="unknown_event_type_xyz",
            book="spec_authorship",
            agent="claude",
            type="some_type",
            task_id="123",
            delta={"failures": 1, "attempts": 1},
            state_dir=repo_fixture
        )
def test_script_ignores_markers_in_md_and_json_files(repo_fixture):
    # Create .md file with marker
    md_file = repo_fixture / "harness" / "plan.md"
    md_file.write_text(f"```python\n{MARKER_ATTEMPTS}\n```")
    
    # 1. With real .py file
    result = subprocess.run([SCRIPT_PATH], cwd=repo_fixture, capture_output=True, text=True)
    assert result.returncode == 0
    assert "plan.md" not in result.stdout
    assert "1 attempts_not_consumed" in result.stdout
    
    # 2. Without real .py file, only .md -> default mode fails
    (repo_fixture / "harness" / "track_record.py").unlink()
    result = subprocess.run([SCRIPT_PATH], cwd=repo_fixture, capture_output=True, text=True)
    assert result.returncode != 0
    
    # 3. List mode with only .md -> zero markers, exits 0
    result = subprocess.run([SCRIPT_PATH, "--list"], cwd=repo_fixture, capture_output=True, text=True)
    assert result.returncode == 0
    assert "0 attempts_not_consumed" in result.stdout

def test_script_against_real_repo_after_TR004():
    # Only run this if we are not in a mocked environment
    if not Path("harness/track_record.py").exists():
        pytest.skip("Not in real repo")
        
    result = subprocess.run([SCRIPT_PATH], capture_output=True, text=True)
    assert result.returncode == 0
    for line in result.stdout.splitlines():
        if MARKER_ATTEMPTS in line or MARKER_AMBIGUOUS in line:
            assert line.startswith("harness/track_record.py")

def test_spurious_marker_spelling_ignored(repo_fixture):
    tr_path = repo_fixture / "harness" / "track_record.py"
    tr_path.write_text(f"""
def attempts_func():
    # DEFERRED_WIRING: something_else
    pass

def ambiguous_func():
    {MARKER_AMBIGUOUS}
    pass
""")
    result = subprocess.run([SCRIPT_PATH], cwd=repo_fixture, capture_output=True, text=True)
    assert result.returncode != 0
    assert "0 attempts_not_consumed" in result.stdout
    assert "1 ambiguous_folded_into_failures" in result.stdout

def test_script_tolerates_missing_directories(repo_fixture):
    scripts_dir = repo_fixture / "scripts"
    if scripts_dir.exists():
        scripts_dir.rmdir()
    
    result = subprocess.run([SCRIPT_PATH], cwd=repo_fixture, capture_output=True, text=True)
    assert result.returncode == 0
    assert "1 attempts_not_consumed" in result.stdout
    assert "1 ambiguous_folded_into_failures" in result.stdout

def test_script_handles_multiple_files_with_markers(repo_fixture):
    tr_path2 = repo_fixture / "harness" / "track_record2.py"
    tr_path2.write_text(f"""
def attempts_func2():
    {MARKER_ATTEMPTS}
    pass
""")
    result = subprocess.run([SCRIPT_PATH], cwd=repo_fixture, capture_output=True, text=True)
    assert result.returncode == 0
    assert "2 attempts_not_consumed" in result.stdout
    assert "1 ambiguous_folded_into_failures" in result.stdout
