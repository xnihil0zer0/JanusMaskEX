import os
from pathlib import Path
import pytest
from harness.test_scoper import get_relevant_test_files

def test_get_relevant_test_files_with_direct_imports(tmp_path):
    # Setup mock repository structure
    # Source file
    src_dir = tmp_path / "harness"
    src_dir.mkdir(parents=True)
    src_file = src_dir / "orchestrator.py"
    src_file.write_text("def run(): pass")

    # Test directory
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    
    # Test file that imports the source file directly
    test_file = tests_dir / "test_orchestrator.py"
    test_file.write_text("import harness.orchestrator\ndef test_run(): pass")

    # Test file that imports another file
    other_test = tests_dir / "test_other.py"
    other_test.write_text("import os\ndef test_os(): pass")

    # Call scoper
    result = get_relevant_test_files(tmp_path, ["harness/orchestrator.py"])
    
    assert "tests/test_orchestrator.py" in result
    assert "tests/test_other.py" not in result


def test_get_relevant_test_files_with_naming_convention(tmp_path):
    # Setup mock layout
    src_dir = tmp_path / "harness"
    src_dir.mkdir(parents=True)
    src_file = src_dir / "ast_enforcer.py"
    src_file.write_text("class ASTEnforcer: pass")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    
    # Test file matches naming convention (test_<module_name>.py) but has no AST imports
    test_file = tests_dir / "test_ast_enforcer.py"
    test_file.write_text("def test_nothing(): pass")

    result = get_relevant_test_files(tmp_path, ["harness/ast_enforcer.py"])
    
    assert "tests/test_ast_enforcer.py" in result


def test_get_relevant_test_files_fallback_to_import_check(tmp_path):
    # Setup mock layout
    src_dir = tmp_path / "harness"
    src_dir.mkdir(parents=True)
    src_file = src_dir / "unknown.py"
    src_file.write_text("pass")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_import.py").write_text("pass")
    
    # No matching test files or imports exist
    result = get_relevant_test_files(tmp_path, ["harness/unknown.py"])
    
    assert result == ["tests/test_import.py"]


def test_get_relevant_test_files_with_malformed_syntax(tmp_path):
    # Setup mock layout
    src_dir = tmp_path / "harness"
    src_dir.mkdir(parents=True)
    src_file = src_dir / "orchestrator.py"
    src_file.write_text("pass")

    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    (tests_dir / "test_import.py").write_text("pass")
    
    # Malformed syntax in a test file should be skipped gracefully
    malformed_test = tests_dir / "test_malformed.py"
    malformed_test.write_text("def malformed_syntax_error(:")

    result = get_relevant_test_files(tmp_path, ["harness/orchestrator.py"])
    
    # Should complete without raising SyntaxError, falling back to import check
    assert result == ["tests/test_import.py"]


def test_get_relevant_test_files_with_test_file_touched(tmp_path):
    # Setup mock layout
    tests_dir = tmp_path / "tests"
    tests_dir.mkdir(parents=True)
    test_file = tests_dir / "test_scoper.py"
    test_file.write_text("def test_scoper(): pass")

    # If the touched file is a test file, it should be returned directly
    result = get_relevant_test_files(tmp_path, ["tests/test_scoper.py"])
    
    assert "tests/test_scoper.py" in result
